#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
粗利益収益性・アクルーアル・資産成長率の「下げ相場限定」検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

new_factors_lab.py --prime の検証期間(2021〜2026年度)が記録的な上げ相場に
偏っていたため、粗利益収益性・アクルーアルが学術研究と逆方向になった可能性を
検証する。defensive_stock_lab.py と同じ2つの実際の急落局面に限定して、
3ファクターが「下げ相場での防御力」を持つかを見る。

★先読みバイアス対策★
各急落局面の開始(peak)より前に確定していた決算データ(fiscal_year_end+60日の
開示ラグを考慮)だけを使う。日本企業の大半が3月期決算であることを踏まえ、
fiscal_year(整数)を「その年の3月末決算、5月末開示」と近似する
(individual_value_backtest.pyの実測パターンと整合)。

対象の下落局面(defensive_stock_lab.pyと同じ):
  2024年8月急落: 2024-07-11(高値)〜2024-08-05(底)
  2025年4月急落: 2024-12-27(高値)〜2025-04-07(底)

使い方: python new_factors_crash_lab.py --prime
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import os
import sys
import statistics as pystats

import yfinance as yf

CHECKPOINT_EVERY = 25

CRASHES = [
    {"name": "2024年8月急落", "peak": "2024-07-11", "trough": "2024-08-05"},
    {"name": "2025年4月急落(2024年末からの続落)", "peak": "2024-12-27", "trough": "2025-04-07"},
]

FACTORS = [
    ("gross_profitability", "粗利益収益性(高い方が良いはず)", False),
    ("accruals", "アクルーアル(低い方が良いはず)", True),
    ("asset_growth", "資産成長率(低い方が良いはず)", True),
]


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def crash_return(ticker_obj, peak: str, trough: str) -> float | None:
    end = (dt.date.fromisoformat(trough) + dt.timedelta(days=3)).isoformat()
    try:
        df = ticker_obj.history(start=peak, end=end, interval="1d")
    except Exception:
        return None
    if df.empty or len(df) < 2:
        return None
    trough_date = dt.date.fromisoformat(trough)
    df_up_to_trough = df[df.index.date <= trough_date]
    if df_up_to_trough.empty:
        return None
    return float(df_up_to_trough["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1


def g(df, key, col):
    try:
        v = df.loc[key, col]
        return float(v) if v == v else None
    except (KeyError, TypeError):
        return None


def latest_known_factors(bs, inc, cf, cutoff_date: dt.date) -> dict:
    """cutoff_date(急落開始日)より前に開示済み(FYE+60日 <= cutoff)の
    最新の決算データから3ファクターを計算する。"""
    bs_cols = sorted(bs.columns)
    best = None
    for i, fye in enumerate(bs_cols):
        reveal = fye.to_pydatetime().date() + dt.timedelta(days=60)
        if reveal > cutoff_date:
            continue
        ta_cur = g(bs, "Total Assets", fye)
        if ta_cur is None or ta_cur == 0:
            continue
        out = {}
        gp = g(inc, "Gross Profit", fye) if fye in inc.columns else None
        if gp is not None:
            out["gross_profitability"] = gp / ta_cur
        ni = g(inc, "Net Income", fye) if fye in inc.columns else None
        ocf = g(cf, "Operating Cash Flow", fye) if fye in cf.columns else None
        if ni is not None and ocf is not None:
            out["accruals"] = (ni - ocf) / ta_cur
        if i > 0:
            ta_prev = g(bs, "Total Assets", bs_cols[i - 1])
            if ta_prev and ta_prev > 0:
                out["asset_growth"] = ta_cur / ta_prev - 1
        if out:
            best = (reveal, out)  # 一番新しい(=cutoff直前)ものを残す
    return best[1] if best else {}


def collect(code: str) -> dict:
    """{crash_name: {factor: value, ...}} を返す。"""
    result = {}
    try:
        t = yf.Ticker(f"{code}.T")
        bs, inc, cf = t.balance_sheet, t.income_stmt, t.cashflow
    except Exception:
        return result
    if bs is None or inc is None or cf is None or bs.empty:
        return result

    for crash in CRASHES:
        cutoff = dt.date.fromisoformat(crash["peak"])
        factors = latest_known_factors(bs, inc, cf, cutoff)
        if not factors:
            continue
        cret = crash_return(yf.Ticker(f"{code}.T"), crash["peak"], crash["trough"])
        if cret is None:
            continue
        result[crash["name"]] = {**factors, "crash_return": cret}
    return result


def main() -> None:
    universe = load_universe()
    tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"new_factors_crash_checkpoint_{tag}.json"
    cache_path = f"new_factors_crash_cache_{tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        all_data = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            saved = json.load(open(checkpoint_path, encoding="utf-8"))
            all_data = saved["data"]
            done_codes = set(saved["done_codes"])
            print(f"チェックポイントから再開: {len(done_codes)}銘柄処理済み")
        else:
            all_data = {}
            done_codes = set()

        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{tag}、残り{len(todo)}/{len(universe)}銘柄を処理中...")
        for i, (code, name) in enumerate(todo, 1):
            r = collect(code)
            if r:
                all_data[code] = r
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"data": all_data, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(有効銘柄 累計{len(all_data)})...")

        json.dump(all_data, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n有効銘柄数: {len(all_data)}\n")

    for crash in CRASHES:
        cname = crash["name"]
        print(f"\n{'='*70}\n=== {cname}({crash['peak']}〜{crash['trough']}) ===\n{'='*70}")
        try:
            mkt_ret = crash_return(yf.Ticker("^N225"), crash["peak"], crash["trough"])
            print(f"日経225自体の下落率: {mkt_ret*100:+.1f}%" if mkt_ret else "日経225下落率: 取得失敗")
        except Exception:
            pass

        for key, label, low_is_good in FACTORS:
            rows = [(code, d[cname][key], d[cname]["crash_return"])
                    for code, d in all_data.items() if cname in d and key in d[cname]]
            if len(rows) < 15:
                print(f"\n--- {label}: サンプル不足(n={len(rows)}) ---")
                continue
            rows.sort(key=lambda r: r[1])
            n = len(rows)
            tercile = n // 3
            low_group = rows[:tercile]
            high_group = rows[-tercile:]
            good, bad = (low_group, high_group) if low_is_good else (high_group, low_group)
            good_avg = pystats.mean([r[2] for r in good])
            bad_avg = pystats.mean([r[2] for r in bad])
            print(f"\n--- {label}(n={n}) ---")
            print(f"  良い質群平均: {good_avg*100:+.1f}%(n={len(good)}) / "
                  f"悪い質群平均: {bad_avg*100:+.1f}%(n={len(bad)}) / "
                  f"差={((good_avg-bad_avg)*100):+.1f}pt(プラスなら質の良い方が下げに強かった)")

    print("\n注意: 2局面とも同じ2024年マクロショック由来の可能性があり完全独立ではない。"
          "n数が少ないため統計的なブレが大きい点に留意。")


if __name__ == "__main__":
    main()
