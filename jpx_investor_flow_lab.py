#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投資部門別売買状況(海外投資家の週次フロー)による1306/TOPIXの予測力 検証ラボ
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。調査待ちキュー#16の検証。

データ: JPX公式「投資部門別売買状況(株式・週間)」の金額版Excel(2016〜2026、557週分、
`_tmp_jpx/weekly/`に取得済み・.gitignore対象・再配布しない)。TOPIX/1306に近い市場として
2022年3月まで「TSE 1st」、2022年4月以降「TSE Prime」シートを使う。

シグナル: 海外投資家の週間ネット売買(購入-売却)を、その週の市場全体売買金額(現物合計)で
正規化した比率。JPXは毎週第4営業日(通常木曜)にその週(金曜まで)のデータを公表するため、
**公表時点で少なくとも1週間の遅れがある**。先読み防止のため、週W(金曜終わり)の
フローを使えるのは翌週(W+1)の途中からであり、影響を受けていない一番安全なリターンは
週W+2の1306リターンとする(W+1は「公表直後から使える早耳版」として参考表示)。

使い方: python jpx_investor_flow_lab.py
"""
from __future__ import annotations
import datetime as dt
import glob
import json
import math
import os
import re
import statistics as pystats
from collections import defaultdict

import pandas as pd
import yfinance as yf
from scipy import stats

WEEKLY_DIR = "_tmp_jpx/weekly"
CACHE = "jpx_investor_flow_cache.json"
RET_CAP = 0.15


def sheet_for_year(year: int) -> list[str]:
    return ["TSE 1st", "TSE Prime"] if year in (2022,) else (["TSE 1st"] if year < 2022 else ["TSE Prime"])


def parse_period_end(text: str, file_year: int) -> dt.date | None:
    # 例: '01/04～01/06' -> 月/日の範囲、終わりの月日を採用。年またぎはfile_yearを基準に補正。
    m = re.search(r"(\d{2})/(\d{2}).?\s*[~～]\s*(\d{2})/(\d{2})", text)
    if not m:
        return None
    m1, d1, m2, d2 = map(int, m.groups())
    year = file_year
    if m1 == 12 and m2 == 1:
        pass  # 開始が前年12月、終了が当年1月というケースはfile_year側(終了年)をそのまま使う
    try:
        return dt.date(year, m2, d2)
    except ValueError:
        return None


def parse_file(path: str) -> dict | None:
    fname = os.path.basename(path)
    m = re.search(r"stock_val_1_(\d{2})(\d{2})(\d{2})\.xls", fname)
    if not m:
        return None
    yy, mm, dd = m.groups()
    file_year = 2000 + int(yy)

    for sheet in sheet_for_year(file_year):
        try:
            df = pd.read_excel(path, sheet_name=sheet, header=None)
        except Exception:
            continue
        if df.shape[0] < 32:
            continue
        try:
            period_text = str(df.iloc[10, 7])
            period_end = parse_period_end(period_text, file_year)
            total_sales = float(str(df.iloc[18, 8]).replace(",", ""))
            total_purch = float(str(df.iloc[19, 8]).replace(",", ""))
            f_sales = float(str(df.iloc[29, 8]).replace(",", ""))
            f_purch = float(str(df.iloc[30, 8]).replace(",", ""))
        except Exception:
            continue
        if period_end is None or total_sales <= 0:
            continue
        total_value = total_sales + total_purch
        net = f_purch - f_sales
        return {"file": fname, "sheet": sheet, "period_end": period_end.isoformat(),
                "foreign_net": net, "total_value": total_value,
                "net_ratio": net / total_value if total_value else None}
    return None


def build_cache() -> list[dict]:
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))
    files = sorted(glob.glob(os.path.join(WEEKLY_DIR, "stock_val_1_*.xls")))
    print(f"{len(files)}件のExcelを解析中...")
    rows = []
    for i, f in enumerate(files, 1):
        r = parse_file(f)
        if r:
            rows.append(r)
        if i % 100 == 0:
            print(f"  {i}/{len(files)}件処理済み...")
    rows.sort(key=lambda r: r["period_end"])
    json.dump(rows, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"解析完了: 有効{len(rows)}/{len(files)}件")
    return rows


def fetch_1306():
    """fetch_yf.pyと同じ『分割の断崖チェック』方式(スキップではなく遡って係数補正)。"""
    df = yf.Ticker("1306.T").history(period="max", auto_adjust=True).dropna(subset=["Close"])
    dates = [idx.date() for idx in df.index]
    px_list = [float(x) for x in df["Close"].tolist()]
    for i in range(1, len(px_list)):
        r = px_list[i] / px_list[i - 1]
        if r < 0.7:
            factor = round(1 / r)
            if factor >= 2:
                for k in range(i):
                    px_list[k] /= factor
        elif r > 1.4:
            factor = round(r)
            if factor >= 2:
                for k in range(i):
                    px_list[k] *= factor
    return dict(zip(dates, px_list))


def week_return(closes: dict, start: dt.date, days: int = 7) -> tuple[float | None, dt.date | None]:
    """start(exclusive)から後の最初の価格を基準に、daysカレンダー日後の直近価格までのリターン。"""
    keys = sorted(closes)
    after_start = [d for d in keys if d > start]
    if not after_start:
        return None, None
    p0_date = after_start[0]
    target = p0_date + dt.timedelta(days=days)
    candidates = [d for d in keys if p0_date < d <= target]
    if not candidates:
        return None, None
    p1_date = candidates[-1]
    return closes[p1_date] / closes[p0_date] - 1, p1_date


def tstat(xs):
    n = len(xs)
    if n < 3:
        return 0.0
    sd = pystats.stdev(xs)
    return pystats.mean(xs) / (sd / math.sqrt(n)) if sd > 0 else 0.0


def main():
    rows = build_cache()
    closes = fetch_1306()
    print(f"1306価格: {min(closes)}〜{max(closes)} ({len(closes)}日)\n")

    for r in rows:
        r["period_end_d"] = dt.date.fromisoformat(r["period_end"])

    # 週W+1(公表直後から使える早耳版)とW+2(安全版)のリターンを付与
    for lag_weeks, key in [(1, "ret_w1"), (2, "ret_w2")]:
        for r in rows:
            start = r["period_end_d"] + dt.timedelta(days=7 * (lag_weeks - 1))
            ret, _ = week_return(closes, start, days=7)
            r[key] = ret

    valid = [r for r in rows if r["net_ratio"] is not None]
    print(f"有効な週次観測: {len(valid)}/{len(rows)}\n")

    for label, key in [("W+1(早耳・参考)", "ret_w1"), ("W+2(公表後1週間以上の遅れ、安全版)", "ret_w2")]:
        rs = [r for r in valid if r[key] is not None]
        print("=" * 78)
        print(f"{label}: n={len(rs)}")
        print("=" * 78)
        xs = [r["net_ratio"] for r in rs]
        ys = [r[key] for r in rs]
        rho, p_corr = stats.spearmanr(xs, ys)
        print(f"スピアマン相関(海外ネット比率 vs 翌{label.split('(')[0]}リターン): rho={rho:+.3f} p={p_corr:.4f}")

        rs_sorted = sorted(rs, key=lambda r: r["net_ratio"])
        n = len(rs_sorted)
        t3 = n // 3
        bot, top = rs_sorted[:t3], rs_sorted[-t3:]
        bot_ret = [r[key] for r in bot]
        top_ret = [r[key] for r in top]
        diff = (pystats.mean(top_ret) - pystats.mean(bot_ret)) * 100
        t_stat, p_val = stats.ttest_ind(top_ret, bot_ret, equal_var=False)
        print(f"三分位スプレッド(海外ネット買い上位1/3 - 下位1/3): "
              f"上位{pystats.mean(top_ret)*100:+.2f}% / 下位{pystats.mean(bot_ret)*100:+.2f}% / "
              f"差{diff:+.2f}pt / t={t_stat:+.2f} p={p_val:.4f}")

        by_year = defaultdict(list)
        for r in rs:
            by_year[r["period_end_d"].year].append(r)
        yearly_diff = {}
        for y, yr in by_year.items():
            if len(yr) < 20:
                continue
            ys_sorted = sorted(yr, key=lambda r: r["net_ratio"])
            t3y = max(3, len(ys_sorted) // 3)
            b = pystats.mean([r[key] for r in ys_sorted[:t3y]])
            t = pystats.mean([r[key] for r in ys_sorted[-t3y:]])
            yearly_diff[y] = (t - b) * 100
        pos = sum(1 for v in yearly_diff.values() if v > 0)
        print(f"年度別スプレッド: " + "  ".join(f"{y}:{v:+.1f}" for y, v in sorted(yearly_diff.items())))
        print(f"→ プラスの年度 {pos}/{len(yearly_diff)}、年度間t={tstat(list(yearly_diff.values())):+.2f}")
        print()

    print("注意: 海外投資家の『比率』は市場規模の変化で正規化した簡易指標。個別銘柄ではなく")
    print("市場全体(TSE1部/プライム)集計であり1306の1銘柄シグナルとしての実務適用は別途検討要。")


if __name__ == "__main__":
    main()
