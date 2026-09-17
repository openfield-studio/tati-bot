#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキューに溜まった3つの新規ファクター候補を一括検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

FACTOR_RESEARCH_LOG.mdの調査待ちキューにあった3候補を、日経225ユニバース・
yfinanceで取得可能な範囲でまとめて検証する(academic_factors_lab.pyと同じ
「一括データ収集→まとめて分析」方式、チェックポイントつき):

  1. 粗利益収益性アノマリー(Gross Profitability, Novy-Marx 2013):
     粗利益 / 総資産が高い銘柄ほどその後のリターンが高い。
  2. アクルーアル・アノマリー(Accruals Anomaly, Sloan 1996):
     (純利益 - 営業キャッシュフロー) / 総資産が低い(利益の「質」が高い)
     銘柄ほどその後のリターンが高い(簡易版アクルーアル)。
  3. 資産成長アノマリー(Asset Growth Anomaly, Cooper, Gulen & Schill 2008):
     総資産の対前年成長率が低い銘柄ほどその後のリターンが高い
     (過剰投資への市場の過小反応)。

individual_value_backtest.pyと同じ先読みバイアス対策(決算期末+60日後の
株価を使用)・年度内クロスセクショナル比較(下位1/3 vs 上位1/3)を採用。

使い方: python new_factors_lab.py
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import os
import sys
import statistics as pystats
from collections import defaultdict

import yfinance as yf

CHECKPOINT_EVERY = 25
FORWARD_MONTHS = [6, 12]
REPORT_LAG_DAYS = 60


def load_universe() -> list[tuple[str, str]]:
    """デフォルトは日経225。 `python new_factors_lab.py --prime` で
    東証プライム全銘柄(tse_prime_universe.csv)を使う。"""
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def to_price_map(hist) -> dict:
    return {idx.date(): float(row["Close"]) for idx, row in hist.iterrows()}


def nearest_price(price_map: dict, target_date):
    for offset in range(10):
        d = (target_date + dt.timedelta(days=offset)).date()
        if d in price_map:
            return price_map[d]
    return None


def collect_observations(code: str) -> list[dict]:
    try:
        t = yf.Ticker(f"{code}.T")
        inc = t.income_stmt
        bs = t.balance_sheet
        cf = t.cashflow
        hist = t.history(period="7y")
    except Exception:
        return []
    if inc is None or bs is None or cf is None or hist.empty:
        return []
    price_map = to_price_map(hist)

    def g(df, key, col):
        try:
            v = df.loc[key, col]
            return float(v) if v == v else None  # NaNチェック
        except (KeyError, TypeError):
            return None

    bs_cols = sorted(bs.columns)
    out = []
    for i, fye in enumerate(bs_cols):
        ta_cur = g(bs, "Total Assets", fye)
        if ta_cur is None or ta_cur == 0:
            continue

        reveal_date = fye.to_pydatetime() + dt.timedelta(days=REPORT_LAG_DAYS)
        price0 = nearest_price(price_map, reveal_date)
        if price0 is None:
            continue
        rets = {}
        for m in FORWARD_MONTHS:
            target = reveal_date + dt.timedelta(days=int(m * 30.4))
            p1 = nearest_price(price_map, target)
            rets[m] = (p1 / price0 - 1) if p1 else None

        obs = {"code": code, "fiscal_year": fye.year,
               **{f"ret{m}": rets[m] for m in FORWARD_MONTHS}}

        # 1. 粗利益収益性 = 粗利益 / 総資産
        gp = g(inc, "Gross Profit", fye) if fye in inc.columns else None
        if gp is not None:
            obs["gross_profitability"] = gp / ta_cur

        # 2. アクルーアル(簡易版) = (純利益 - 営業CF) / 総資産
        ni = g(inc, "Net Income", fye) if fye in inc.columns else None
        ocf = g(cf, "Operating Cash Flow", fye) if fye in cf.columns else None
        if ni is not None and ocf is not None:
            obs["accruals"] = (ni - ocf) / ta_cur

        # 3. 資産成長率 = 総資産(当期)/総資産(前期) - 1 (前年度データが必要)
        if i > 0:
            ta_prev = g(bs, "Total Assets", bs_cols[i - 1])
            if ta_prev and ta_prev > 0:
                obs["asset_growth"] = ta_cur / ta_prev - 1

        if any(k in obs for k in ("gross_profitability", "accruals", "asset_growth")):
            out.append(obs)
    return out


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"new_factors_checkpoint_{universe_tag}.json"
    cache_path = f"new_factors_cache_{universe_tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        all_obs = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            saved = json.load(open(checkpoint_path, encoding="utf-8"))
            all_obs = saved["observations"]
            done_codes = set(saved["done_codes"])
            print(f"チェックポイントから再開: {len(done_codes)}銘柄処理済み、観測数 累計{len(all_obs)}")
        else:
            all_obs = []
            done_codes = set()

        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{universe_tag}、残り{len(todo)}/{len(universe)}銘柄の決算データ+株価を取得中...")
        for i, (code, name) in enumerate(todo, 1):
            all_obs += collect_observations(code)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"observations": all_obs, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(観測数 累計{len(all_obs)}、チェックポイント保存)...")

        json.dump(all_obs, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n合計観測数: {len(all_obs)}\n")

    factors = [
        ("gross_profitability", "粗利益収益性(Gross Profitability)", False),  # False=高い方が良い
        ("accruals", "アクルーアル(低い方が利益の質が高い)", True),           # True=低い方が良い
        ("asset_growth", "資産成長率(低い方が良いとされる)", True),
    ]

    for key, label, low_is_good in factors:
        print(f"\n{'='*70}\n=== {label} ===\n{'='*70}")
        obs_with_key = [o for o in all_obs if key in o]
        years = sorted(set(o["fiscal_year"] for o in obs_with_key))
        pooled_good = defaultdict(list)
        pooled_bad = defaultdict(list)
        for year in years:
            yr_obs = [o for o in obs_with_key if o["fiscal_year"] == year]
            yr_sorted = sorted(yr_obs, key=lambda o: o[key])
            n = len(yr_sorted)
            tercile = n // 3
            if tercile < 5:
                continue
            low_group = yr_sorted[:tercile]
            high_group = yr_sorted[-tercile:]
            good, bad = (low_group, high_group) if low_is_good else (high_group, low_group)
            for m in FORWARD_MONTHS:
                g_r = [o[f"ret{m}"] for o in good if o.get(f"ret{m}") is not None]
                b_r = [o[f"ret{m}"] for o in bad if o.get(f"ret{m}") is not None]
                pooled_good[m] += g_r
                pooled_bad[m] += b_r

        print(f"対象年度: {years} / 有効観測数: {len(obs_with_key)}")
        for m in FORWARD_MONTHS:
            g, b = pooled_good[m], pooled_bad[m]
            if g and b:
                diff = (pystats.mean(g) - pystats.mean(b)) * 100
                print(f"  {m}ヶ月後: 良い群平均={pystats.mean(g)*100:+.1f}%(中央値{pystats.median(g)*100:+.1f}%, n={len(g)}) / "
                      f"悪い群平均={pystats.mean(b)*100:+.1f}%(中央値{pystats.median(b)*100:+.1f}%, n={len(b)}) / "
                      f"平均差={diff:+.1f}pt")
            else:
                print(f"  {m}ヶ月後: サンプル不足")

        # 外れ値除外版
        CAP = 2.0
        print("  --- |r|>200%除外 ---")
        for m in FORWARD_MONTHS:
            g = [r for r in pooled_good[m] if abs(r) <= CAP]
            b = [r for r in pooled_bad[m] if abs(r) <= CAP]
            if g and b:
                diff = (pystats.mean(g) - pystats.mean(b)) * 100
                print(f"  {m}ヶ月後: 良い群={pystats.mean(g)*100:+.1f}%(n={len(g)}) / "
                      f"悪い群={pystats.mean(b)*100:+.1f}%(n={len(b)}) / 差={diff:+.1f}pt")

    universe_label = "東証プライム全銘柄" if universe_tag == "prime" else "日経225(大型株中心)"
    print(f"\n注意: {universe_label}のみでの検証。決算発表タイミングは+60日で近似。"
          "生存バイアス(現行構成銘柄のみ)・DSR等の多重検定補正は未実施。")


if __name__ == "__main__":
    main()
