#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日経平均(1965〜)の長期データで「本物の回復しない下落」を含めて損切りを再検証 検証ラボ
=====================================================================
※本体には組み込まない。systematic_decline_short_lab.pyの項目92で判明した限界
(1306はyfinanceで2009年以降しか取れず、2009〜2026年は結局右肩上がりの相場のため
『回復しない本物の下落』が1件もサンプルに含まれていなかった)を受けた再検証。

日経平均指数(^N225)はyfinanceで1965年から取得できる(1306と違い個別ETFの分割調整も
不要、指数そのもの)。バブル崩壊後の「失われた10年」(1990年代)、ITバブル崩壊
(2000〜2003年)、リーマンショック(2008〜2009年)等、本物の長期下落局面を含めて
ロングの損切りルールを再検証する。

★注意★ ^N225はTOPIX(1306が追跡する指数)とは別物(日経平均は225銘柄の価格平均型、
TOPIXは東証全体の時価総額加重型)だが、日本株市場全体の長期的な値動きパターンを見る
目的では妥当な代替。1306自体の長期データが取れない制約への対処。

使い方: python nikkei_long_term_stoploss_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats
from collections import defaultdict

import yfinance as yf

import systematic_decline_short_lab as s

TICKER = "^N225"
THRESHOLD = -0.025
COOLDOWN = 15
COST_ROUNDTRIP = 0.002


def fetch_closes(ticker: str) -> dict[dt.date, float]:
    df = yf.Ticker(ticker).history(period="max", auto_adjust=True).dropna(subset=["Close"])
    return {idx.date(): float(c) for idx, c in zip(df.index, df["Close"])}


def main():
    closes = fetch_closes(TICKER)
    shocks = s.find_shock_days(closes, THRESHOLD, COOLDOWN)
    print(f"日経平均データ範囲: {min(closes)}〜{max(closes)}")
    print(f"検出したショック日(1日{THRESHOLD*100:.1f}%以下、cooldown{COOLDOWN}営業日): {len(shocks)}件\n")

    by_year = defaultdict(int)
    for d in shocks:
        by_year[d.year] += 1
    print("年度別件数:")
    print("  " + "  ".join(f"{y}:{n}" for y, n in sorted(by_year.items())))
    print()

    # ---- 保有中の最悪ドローダウン分布(長期下落局面を含めて) ----
    worst_list = []
    for d0 in shocks:
        path = s.path_profile_side(closes, d0, "long", max_days=20)
        if len(path) < 20:
            continue
        worst = min(r for _, r in path)
        final = path[-1][1]
        worst_list.append((d0, worst, final))
    worst_list.sort(key=lambda x: x[1])

    print("=" * 100)
    print("保有中の最悪ドローダウン(深い順、上位15件)")
    print("=" * 100)
    for d0, worst, final in worst_list[:15]:
        print(f"  {d0}  最悪{worst*100:+.2f}%  →20日目{final*100:+.2f}%")

    print("\n最悪ドローダウンの分布:")
    for th in [-0.05, -0.08, -0.10, -0.15, -0.20, -0.25, -0.30]:
        n = sum(1 for _, w, _ in worst_list if w <= th)
        print(f"  {th*100:.0f}%以下まで落ちた: {n}件")

    # ---- 損切り閾値の掃引(長期データで再検証) ----
    print("\n" + "=" * 100)
    print(f"損切り閾値の掃引(固定20営業日、n={len(shocks)}、1965年以降を含む)")
    print("=" * 100)
    for sl in [None, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25]:
        pnls, triggered = [], 0
        for d0 in shocks:
            r = s.stoploss_exit_side(closes, d0, sl, "long")
            if r is None:
                continue
            pnls.append(r - COST_ROUNDTRIP)
            if sl is not None and r <= -sl + 1e-9:
                triggered += 1
        if not pnls:
            continue
        wins = sum(1 for p in pnls if p > 0)
        lbl = "なし" if sl is None else f"{sl*100:.0f}%"
        print(f"  損切り{lbl}: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
              f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 最悪{min(pnls)*100:+.2f}% "
              f"/ 合計{sum(pnls)*100:+.1f}% / 発動{triggered}件")

    # ---- バブル崩壊〜失われた10年(1990年代)だけを抜き出す ----
    print("\n" + "=" * 100)
    print("参考: 1990〜1995年(バブル崩壊直後)だけの結果")
    print("=" * 100)
    bubble_shocks = [d0 for d0 in shocks if 1990 <= d0.year <= 1995]
    print(f"該当イベント: {len(bubble_shocks)}件 " + ", ".join(str(d) for d in bubble_shocks))
    for sl in [None, 0.10, 0.15, 0.20]:
        pnls = []
        for d0 in bubble_shocks:
            r = s.stoploss_exit_side(closes, d0, sl, "long")
            if r is not None:
                pnls.append(r - COST_ROUNDTRIP)
        if not pnls:
            continue
        wins = sum(1 for p in pnls if p > 0)
        lbl = "なし" if sl is None else f"{sl*100:.0f}%"
        print(f"  損切り{lbl}: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
              f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 合計{sum(pnls)*100:+.1f}%")

    print("\n注意: ^N225はTOPIX(1306)とは別指数。日本株市場全体の長期傾向を見る代替として使用。")
    print("コストは往復20bps仮定。1965〜2026年の61年間、実際の市場サイクル数は限られる点に注意。")


if __name__ == "__main__":
    main()
