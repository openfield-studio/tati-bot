#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
value_screener.pyのランキングに資産成長率を加えたらどう変わるかのシミュレーション
=====================================================================
※本体(value_screener.py)には組み込まない。「試したらどうなるか」の記録。

new_factors_lab.py --prime の検証で資産成長アノマリー(総資産成長率が低い銘柄が
その後のリターンで優位)が4つの角度すべてでプラスだったことを受け、実際の
value_screener.py(日経225・割安スコア+反発スコアの1:1平均)に資産成長率を
「質スコア」として第3の柱で加えた場合、TOP10ランキングがどう変わるかを見る。

value_screener.py本体は一切変更せず、別ファイルとして比較シミュレーションのみ行う。

現在の総合スコア = (割安スコア + 反発スコア) / 2
今回の試算スコア = (割安スコア + 反発スコア + 資産成長スコア) / 3
  (資産成長スコアは総資産成長率が低いほど高得点になるパーセンタイル)

使い方: python value_screener_asset_growth_sim.py
"""
from __future__ import annotations
import time

import yfinance as yf

from value_screener import (
    NIKKEI225, fetch_metrics, fetch_turnaround_signals, percentile_rank,
    OVERBOUGHT_RSI,
)


def fetch_asset_growth(code: str) -> float | None:
    """直近2期の総資産から資産成長率を計算(new_factors_lab.pyと同じ定義)。"""
    try:
        bs = yf.Ticker(f"{code}.T").balance_sheet
    except Exception:
        return None
    if bs is None or bs.empty or "Total Assets" not in bs.index:
        return None
    cols = sorted(bs.columns)
    if len(cols) < 2:
        return None
    try:
        ta_cur = float(bs.loc["Total Assets", cols[-1]])
        ta_prev = float(bs.loc["Total Assets", cols[-2]])
    except (KeyError, TypeError, ValueError):
        return None
    if ta_prev is None or ta_prev != ta_prev or ta_prev <= 0:
        return None
    if ta_cur is None or ta_cur != ta_cur:
        return None
    return ta_cur / ta_prev - 1


def main() -> None:
    print(f"日経225、{len(NIKKEI225)}銘柄のデータを取得中(yfinance)...")
    rows = []
    for i, (code, name) in enumerate(NIKKEI225, 1):
        m = fetch_metrics(code, name)
        if m:
            rows.append(m)
        if i % 30 == 0:
            print(f"  {i}/{len(NIKKEI225)}件処理済み...")
        time.sleep(0.1)
    print(f"質フィルター後: {len(rows)}/{len(NIKKEI225)}銘柄")

    per_scores = percentile_rank([r["per"] for r in rows])
    pbr_scores = percentile_rank([r["pbr"] for r in rows])
    div_scores = percentile_rank([r["dividend_yield"] for r in rows], reverse=True)
    for r, ps, bs, ds in zip(rows, per_scores, pbr_scores, div_scores):
        r["value_score"] = round((ps + bs + ds) / 3, 4)

    print("反発シグナルを取得中...")
    ta_rows = []
    for i, r in enumerate(rows, 1):
        ta = fetch_turnaround_signals(r["code"])
        if ta:
            r.update(ta)
            ta_rows.append(r)
        if i % 30 == 0:
            print(f"  {i}/{len(rows)}件処理済み...")
        time.sleep(0.1)

    is_overbought = lambda r: r["rsi14"] is not None and r["rsi14"] >= OVERBOUGHT_RSI
    eligible = [r for r in ta_rows if not is_overbought(r)]

    off_low_scores = percentile_rank([r["off_low_pct"] for r in eligible], reverse=True)
    trend_scores = percentile_rank([r["trend_pct"] for r in eligible], reverse=True)
    decel_scores = percentile_rank([r["decel_pct"] for r in eligible], reverse=True)
    for r, o, t, d in zip(eligible, off_low_scores, trend_scores, decel_scores):
        r["turnaround_score"] = round((o + t + d) / 3, 4)
        r["combined_score_current"] = round((r["value_score"] + r["turnaround_score"]) / 2, 4)

    print(f"資産成長率(直近決算)を取得中... ({len(eligible)}銘柄)")
    for i, r in enumerate(eligible, 1):
        r["asset_growth"] = fetch_asset_growth(r["code"])
        if i % 30 == 0:
            print(f"  {i}/{len(eligible)}件処理済み...")
        time.sleep(0.1)

    with_growth = [r for r in eligible if r["asset_growth"] is not None]
    print(f"資産成長率取得できた銘柄: {len(with_growth)}/{len(eligible)}")

    growth_scores = percentile_rank([r["asset_growth"] for r in with_growth])  # 低いほど高得点
    for r, g in zip(with_growth, growth_scores):
        r["growth_score"] = round(g, 4)
        r["combined_score_new"] = round(
            (r["value_score"] + r["turnaround_score"] + r["growth_score"]) / 3, 4)

    current_top10 = sorted(with_growth, key=lambda r: r["combined_score_current"], reverse=True)[:10]
    new_top10 = sorted(with_growth, key=lambda r: r["combined_score_new"], reverse=True)[:10]

    print("\n=== 現行スコア(割安+反発、1:1) TOP10 ===")
    for i, r in enumerate(current_top10, 1):
        print(f"  {i:2d}. {r['code']} {r['name']:12s} 総合{r['combined_score_current']:.3f} "
              f"(割安{r['value_score']:.2f} 反発{r['turnaround_score']:.2f} "
              f"資産成長率{r['asset_growth']*100:+.1f}%)")

    print("\n=== 試算スコア(割安+反発+資産成長、1:1:1) TOP10 ===")
    for i, r in enumerate(new_top10, 1):
        print(f"  {i:2d}. {r['code']} {r['name']:12s} 総合{r['combined_score_new']:.3f} "
              f"(割安{r['value_score']:.2f} 反発{r['turnaround_score']:.2f} "
              f"資産成長{r['growth_score']:.2f}=率{r['asset_growth']*100:+.1f}%)")

    current_codes = {r["code"] for r in current_top10}
    new_codes = {r["code"] for r in new_top10}
    dropped = current_codes - new_codes
    added = new_codes - current_codes
    print(f"\n=== 差分 ===")
    print(f"TOP10から外れる銘柄: {sorted(dropped) if dropped else 'なし'}")
    print(f"TOP10に新規で入る銘柄: {sorted(added) if added else 'なし'}")
    print(f"共通: {len(current_codes & new_codes)}/10銘柄")


if __name__ == "__main__":
    main()
