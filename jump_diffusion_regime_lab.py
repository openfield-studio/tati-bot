#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ジャンプ・ディフュージョン分解(バイパワー変分)の実証検証
=====================================================================
調査待ちキュー#23(Barndorff-Nielsen & Shephard 2004/2006、Lee & Mykland 2008)。
日次リターンの実現分散(RV=Σr_t^2)とバイパワー変分(BV≈(π/2)Σ|r_t||r_{t-1}|、
ジャンプにロバスト)の差J=max(RV-BV,0)を「単発ジャンプ成分」、BVを「連続的な
拡散(ドリフト)成分」として分離する。

仮説: イベント型の急落(リーマン・コロナ)はJが大きい(ジャンプ優勢)、構造的・
じわじわ型の下落(ITバブル崩壊)はJが小さい(ジャンプ非優勢)まま負のドリフトが
持続する。「下落中 かつ ジャンプ比率が低い(ジャンプではなく緩やかな下落)」を
検知できれば、既存のショック検知(単発ジャンプ前提)が見逃す構造的下落を
早期警戒できる可能性がある。

設計(過剰最適化回避): 窓幅はIS期間で1つに固定(探索しない、隣接窓での頑健性は
別途確認)。ジャンプ比率の閾値もIS期間の中央値で固定。

使い方: python jump_diffusion_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
import math
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
PI_2 = math.pi / 2

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)
rets = [0.0] + [px[i]/px[i-1]-1 for i in range(1, n)]


def jump_ratio_series(window: int) -> list[float | None]:
    out: list[float | None] = [None] * n
    for i in range(window + 1, n):
        seg = rets[i - window + 1:i + 1]
        rv = sum(r*r for r in seg)
        bv = PI_2 * sum(abs(seg[k]) * abs(seg[k-1]) for k in range(1, len(seg)))
        j = max(rv - bv, 0.0)
        out[i] = j / rv if rv > 0 else 0.0
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

# --- 記述統計: 仮説(イベント型=高ジャンプ比率、構造型=低ジャンプ比率)を確認 ---
WINDOW_DESC = 20
jr_desc = jump_ratio_series(WINDOW_DESC)
periods = {
    "2000-2003 ITバブル崩壊(じわじわ型)": (dt.date(2000, 1, 1), dt.date(2003, 4, 30)),
    "2008-2009 リーマン(急激型)": (dt.date(2008, 9, 1), dt.date(2009, 3, 31)),
    "2020 コロナショック(急激型)": (dt.date(2020, 2, 15), dt.date(2020, 4, 15)),
}
print(f"=== 記述統計: ジャンプ比率J/RV(窓={WINDOW_DESC}日、下落方向のみ) ===")
for label, (start, end) in periods.items():
    vals = [jr_desc[i] for i in range(n) if jr_desc[i] is not None and start <= dates[i] <= end
            and px[i] < px[i-WINDOW_DESC]]
    if vals:
        print(f"  {label}: 平均J/RV={st.mean(vals):.3f} (n={len(vals)})")


def gen_switches(window: int, use_jd: bool):
    jr = jump_ratio_series(window)
    is_vals = [jr[i] for i in range(window+1, split) if jr[i] is not None and px[i] < px[i-window]]
    threshold = st.median(is_vals) if is_vals else 0.3

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
            jd_trigger = False
            if use_jd and jr[i] is not None and i >= window and px[i] < px[i-window]:
                was_yesterday = (jr[i-1] is not None and px[i-1] < px[i-1-window] and jr[i-1] < threshold) if i-1 >= window else False
                jd_trigger = jr[i] < threshold and not was_yesterday
            triggered = is_shock or jd_trigger
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


base = gen_switches(20, False)
print(f"\n{'開始年':<8}{'買い持ち':>14}{'現行':>16}{'JD追加(窓20)':>16}")
jd20 = gen_switches(20, True)
for y in (2000, 2006, 1965):
    eb, bh, nb = evaluate(base, y)
    ej, _, nj = evaluate(jd20, y)
    print(f"{y}年〜 {bh:>12,.0f}円 {eb:>14,.0f}円({nb}回) {ej:>14,.0f}円({nj}回)")

print("\n=== 頑健性チェック: 窓幅10/15/20/25/30日 ===")
for w in (10, 15, 20, 25, 30):
    ver = gen_switches(w, True)
    print(f"\n--- 窓幅{w}日 ---")
    for y in (2000, 2006, 1965):
        eb, bh, nb = evaluate(base, y)
        ej, _, nj = evaluate(ver, y)
        print(f"  {y}年〜: 現行{eb:,.0f}円({nb}回) -> JD追加{ej:,.0f}円({nj}回)  変化{(ej/eb-1)*100:+.1f}%")
