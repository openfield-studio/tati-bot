#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
クオンタイル自己回帰(QAR)的発想による「リバウンド消失」検知の実証検証
=====================================================================
Geminiへの相談で得た提案(2026-10-02)。「じわじわ下落は急落ではなく、上位分位点
(自律反発力)の低下として定義できる」という仮説。完全なQAR(分位点自己回帰、
pinball損失最小化が必要で実装が重い)の代わりに、簡略版として直近window日の
リターン分布の90パーセンタイル(Q90、短期的な「反発の大きさ」の代理指標)を追跡し、
IS期間の基準水準から大きく低下した状態を「反発力の消失」として検知する。

仮説: 健全な相場(上昇・通常の下落とも)では、下落後に相応の戻り(高いQ90)が
観測されるが、構造的・じわじわ型の下落(ITバブル崩壊)では戻りが乏しく(低いQ90)
下落が持続する。イベント型の急落(リーマン・コロナ)は反発自体も激しい(高いQ90を
維持)という対比を想定。

設計(過剰最適化回避): 窓幅はIS期間で1つに固定、閾値もIS中央値で固定。
隣接窓での頑健性は別途確認。

使い方: python qar_rebound_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as st
from collections import defaultdict

import yfinance as yf

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
IS_RATIO = 0.65

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)
rets = [0.0] + [px[i]/px[i-1]-1 for i in range(1, n)]


def q90_series(window: int) -> list[float | None]:
    out: list[float | None] = [None] * n
    for i in range(window, n):
        seg = sorted(rets[i-window+1:i+1])
        idx = int(len(seg) * 0.9)
        out[i] = seg[min(idx, len(seg)-1)]
    return out


def sma(arr, w):
    out = [None]*len(arr); s = 0.0
    for i, v in enumerate(arr):
        s += v
        if i >= w: s -= arr[i-w]
        if i >= w-1: out[i] = s/w
    return out


ma_fast = sma(px, MA_FAST)
ma_slow = sma(px, MA_SLOW)
dc_regime = ["bull" if (ma_fast[i] is None or ma_slow[i] is None or ma_fast[i] >= ma_slow[i]) else "bear" for i in range(n)]

split = int(n * IS_RATIO)

WINDOW_DESC = 60
q90_desc = q90_series(WINDOW_DESC)
periods = {
    "2000-2003 ITバブル崩壊(じわじわ型)": (dt.date(2000, 1, 1), dt.date(2003, 4, 30)),
    "2008-2009 リーマン(急激型)": (dt.date(2008, 9, 1), dt.date(2009, 3, 31)),
    "2020 コロナショック(急激型)": (dt.date(2020, 2, 15), dt.date(2020, 4, 15)),
    "IS全体(参考・平時込み)": (dates[WINDOW_DESC], dates[split]),
}
print(f"=== 記述統計: Q90(上位10%分位点、窓={WINDOW_DESC}日の日次リターン) ===")
for label, (start, end) in periods.items():
    vals = [q90_desc[i] for i in range(n) if q90_desc[i] is not None and start <= dates[i] <= end]
    if vals:
        print(f"  {label}: 平均Q90={st.mean(vals)*100:+.3f}%/日 (n={len(vals)})")


def gen_switches(window: int, use_qar: bool):
    q90 = q90_series(window)
    is_vals = [q90[i] for i in range(window, split) if q90[i] is not None]
    threshold = st.median(is_vals) if is_vals else 0.01

    events = [(0, 'long')]
    holding = 'long'; entry_i = 0; last_shock = -10**9
    for i in range(MA_SLOW, n):
        if holding == 'bear':
            rr = -(px[i]/px[entry_i]-1); held = i-entry_i
            if rr >= BEAR_TP or rr <= -BEAR_SL or held >= MAX_HOLD:
                events.append((i, 'long')); holding = 'long'; entry_i = i
        else:
            r = rets[i]
            is_shock = r <= SHOCK_TH
            qar_trigger = False
            if use_qar and q90[i] is not None:
                was_yesterday = (q90[i-1] is not None and q90[i-1] < threshold) if i-1 >= window else False
                qar_trigger = q90[i] < threshold and not was_yesterday
            triggered = is_shock or qar_trigger
            cd_ok = (i - last_shock) >= COOLDOWN
            if triggered and cd_ok and dc_regime[i] == 'bear':
                events.append((i, 'bear')); holding = 'bear'; entry_i = i; last_shock = i
            elif triggered:
                last_shock = i
    return events


def evaluate(events, start_year):
    start_date = dt.date(start_year, 1, 1)
    start_i = next(i for i, d in enumerate(dates) if d >= start_date)
    leg = 'long'
    for i, tgt in events:
        if i > start_i: break
        leg = tgt
    ev_in = [(i, tgt) for i, tgt in events if i > start_i]
    equity = PRINCIPAL; last_switch_eq = PRINCIPAL
    yearly = defaultdict(float); prev = px[start_i]
    ev_iter = iter(ev_in); next_ev = next(ev_iter, None)
    for i in range(start_i+1, n):
        ratio = px[i]/prev if leg == 'long' else 1 + -(px[i]/prev-1)
        equity *= ratio; prev = px[i]
        while next_ev is not None and next_ev[0] == i:
            equity *= (1-COST)
            yearly[dates[i].year] += equity - last_switch_eq
            last_switch_eq = equity
            leg = next_ev[1]
            next_ev = next(ev_iter, None)
        if i == n-1 or dates[i+1].year != dates[i].year:
            g = yearly.get(dates[i].year, 0.0)
            if g > 0:
                tax = g*TAX_RATE; equity -= tax; last_switch_eq = equity
    bh = PRINCIPAL * (px[-1]/px[start_i])
    return equity, bh, len(ev_in)


base = gen_switches(60, False)
print(f"\n{'開始年':<8}{'買い持ち':>14}{'現行':>16}{'QAR追加(窓60)':>16}")
qar60 = gen_switches(60, True)
for y in (2000, 2006, 1965):
    eb, bh, nb = evaluate(base, y)
    eq_, _, nq = evaluate(qar60, y)
    print(f"{y}年〜 {bh:>12,.0f}円 {eb:>14,.0f}円({nb}回) {eq_:>14,.0f}円({nq}回)")

print("\n=== 頑健性チェック: 窓幅30/45/60/75/90日 ===")
for w in (30, 45, 60, 75, 90):
    ver = gen_switches(w, True)
    print(f"\n--- 窓幅{w}日 ---")
    for y in (2000, 2006, 1965):
        eb, bh, nb = evaluate(base, y)
        eq_, _, nq = evaluate(ver, y)
        print(f"  {y}年〜: 現行{eb:,.0f}円({nb}回) -> QAR追加{eq_:,.0f}円({nq}回)  変化{(eq_/eb-1)*100:+.1f}%")
