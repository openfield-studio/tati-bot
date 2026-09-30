#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
トレンド効率性(Kaufman Efficiency Ratio)による「なだらかな下落」と「急落」の区別を検証
=====================================================================================
調査待ちキュー#21(Kaufman 1995のER、Peters 1994のHurst指数)。「イベント型の急落は
効率性(直線的な値動き)が高く、構造的型のじわじわ下落は効率性が低い」という仮説を、
まず記述統計で検証してから(仮説が成り立たなければ無理にルール化しない)、成り立てば
regime_shiftへの組み込みを検討する。

Efficiency Ratio(window) = |px[t]-px[t-window]| / Σ|px[i]-px[i-1]| (i=t-window+1..t)
0〜1、1に近いほど直線的(効率的)、0に近いほどジグザグ(非効率的)。

使い方: python efficiency_ratio_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as st

import yfinance as yf

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)


def efficiency_ratio_series(window: int) -> list[float | None]:
    out: list[float | None] = [None] * n
    for i in range(window, n):
        net = abs(px[i] - px[i - window])
        vol_sum = sum(abs(px[k] - px[k - 1]) for k in range(i - window + 1, i + 1))
        out[i] = net / vol_sum if vol_sum > 0 else None
    return out


for window in (20, 60):
    er = efficiency_ratio_series(window)
    print(f"\n{'='*80}\nEfficiency Ratio(窓={window}営業日)\n{'='*80}")

    periods = {
        "2000-2003 ITバブル崩壊(じわじわ型)": (dt.date(2000, 1, 1), dt.date(2003, 4, 30)),
        "2008-2009 リーマン(急激型)": (dt.date(2008, 9, 1), dt.date(2009, 3, 31)),
        "2020 コロナショック(急激型)": (dt.date(2020, 2, 15), dt.date(2020, 4, 15)),
        "全期間(参考、比較対象)": (dates[window], dates[-1]),
    }

    for label, (start, end) in periods.items():
        vals_all = [er[i] for i in range(n) if er[i] is not None and start <= dates[i] <= end]
        # 期間中「下落方向」のERのみに絞る(上昇中の効率性は今回の関心外)
        vals_decline = [er[i] for i in range(1, n) if er[i] is not None and start <= dates[i] <= end
                         and px[i] < px[i - window]]
        if not vals_all:
            continue
        mean_all = st.mean(vals_all)
        mean_decline = st.mean(vals_decline) if vals_decline else float("nan")
        print(f"  {label}: 全体平均ER={mean_all:.3f}  下落方向のみ平均ER={mean_decline:.3f}  "
              f"(n={len(vals_all)}, 下落局面n={len(vals_decline)})")
