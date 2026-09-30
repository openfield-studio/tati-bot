#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HMMレジーム判定を使ったregime_shift戦略のバックテスト。デッドクロス方式(現行)と比較。"""
from __future__ import annotations
import datetime as dt
from collections import defaultdict

import numpy as np
import yfinance as yf

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)

p_bear = np.load("hmm_p_bear.npy")
hmm_regime = ["bear" if p_bear[i] >= 0.5 else "bull" for i in range(n)]

def sma(arr, w):
    out = [None]*len(arr); s=0.0
    for i,v in enumerate(arr):
        s+=v
        if i>=w: s-=arr[i-w]
        if i>=w-1: out[i]=s/w
    return out

ma_fast = sma(px, MA_FAST); ma_slow = sma(px, MA_SLOW)
dc_regime = ["bull" if (ma_fast[i] is None or ma_slow[i] is None or ma_fast[i]>=ma_slow[i]) else "bear" for i in range(n)]

def gen_switches(regime):
    events = [(0,'long')]; holding='long'; entry_i=0; last_shock=-10**9
    for i in range(MA_SLOW, n):
        if holding=='bear':
            r = -(px[i]/px[entry_i]-1); held = i-entry_i
            if r>=BEAR_TP or r<=-BEAR_SL or held>=MAX_HOLD:
                events.append((i,'long')); holding='long'; entry_i=i
        else:
            day_ret = px[i]/px[i-1]-1
            is_shock = day_ret<=SHOCK_TH
            cd_ok = (i-last_shock)>=COOLDOWN
            if is_shock and cd_ok and regime[i]=='bear':
                events.append((i,'bear')); holding='bear'; entry_i=i; last_shock=i
            elif is_shock:
                last_shock=i
    return events

def evaluate(events, start_year):
    start_date = dt.date(start_year,1,1)
    start_i = next(i for i,d in enumerate(dates) if d>=start_date)
    leg='long'
    for i,tgt in events:
        if i>start_i: break
        leg=tgt
    ev_in = [(i,tgt) for i,tgt in events if i>start_i]
    equity=PRINCIPAL; last_switch_eq=PRINCIPAL
    yearly=defaultdict(float); prev=px[start_i]
    ev_iter=iter(ev_in); next_ev=next(ev_iter,None)
    for i in range(start_i+1,n):
        ratio = px[i]/prev if leg=='long' else 1+-(px[i]/prev-1)
        equity*=ratio; prev=px[i]
        while next_ev is not None and next_ev[0]==i:
            equity*=(1-COST)
            yearly[dates[i].year]+=equity-last_switch_eq
            last_switch_eq=equity
            leg=next_ev[1]
            next_ev=next(ev_iter,None)
        if i==n-1 or dates[i+1].year!=dates[i].year:
            g=yearly.get(dates[i].year,0.0)
            if g>0:
                tax=g*TAX_RATE; equity-=tax; last_switch_eq=equity
    bh = PRINCIPAL*(px[-1]/px[start_i])
    return equity, bh, len(ev_in)

dc_events = gen_switches(dc_regime)
hmm_events = gen_switches(hmm_regime)

print(f"{'開始年':<8}{'買い持ち':>14}{'現行(デッドクロス)':>18}{'HMM版':>16}")
for y in (2000, 2006, 1965):
    ed, bh, nd = evaluate(dc_events, y)
    eh, _, nh = evaluate(hmm_events, y)
    print(f"{y}年〜 {bh:>12,.0f}円 {ed:>14,.0f}円({nd}回) {eh:>14,.0f}円({nh}回)")

print("\n=== OOS(2005年〜)のみ ===")
for y in (2005,):
    ed, bh, nd = evaluate(dc_events, y)
    eh, _, nh = evaluate(hmm_events, y)
    print(f"{y}年〜 買い持ち{bh:,.0f}円  デッドクロス{ed:,.0f}円({nd}回)  HMM{eh:,.0f}円({nh}回)")

print("\n=== ITバブル崩壊期(2000-2003年)のHMM弱気判定の様子 ===")
prev_month = None
for i in range(n):
    if dt.date(2000,1,1) <= dates[i] <= dt.date(2003,12,31):
        if dates[i].month != prev_month:
            print(f"  {dates[i]}: P(弱気)={p_bear[i]*100:.1f}%  デッドクロス判定={dc_regime[i]}")
            prev_month = dates[i].month
