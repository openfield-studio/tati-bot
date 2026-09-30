#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Efficiency Ratioを追加トリガーとしてregime_shiftに組み込み検証。
ISの中央値を閾値として固定(探索しない、過剰最適化回避)。"""
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
ER_WINDOW = 60
IS_RATIO = 0.65

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)

er = [None]*n
for i in range(ER_WINDOW, n):
    net = abs(px[i]-px[i-ER_WINDOW])
    vol_sum = sum(abs(px[k]-px[k-1]) for k in range(i-ER_WINDOW+1, i+1))
    er[i] = net/vol_sum if vol_sum>0 else None

split = int(n*IS_RATIO)
is_er_decline = [er[i] for i in range(ER_WINDOW, split) if er[i] is not None and px[i]<px[i-ER_WINDOW]]
er_threshold = st.median(is_er_decline)
print(f"IS期間の下落方向ER中央値(閾値として使用、探索なし): {er_threshold:.3f}")

def sma(arr, w):
    out=[None]*len(arr); s=0.0
    for i,v in enumerate(arr):
        s+=v
        if i>=w: s-=arr[i-w]
        if i>=w-1: out[i]=s/w
    return out

ma_fast = sma(px, MA_FAST); ma_slow = sma(px, MA_SLOW)
dc_regime = ["bull" if (ma_fast[i] is None or ma_slow[i] is None or ma_fast[i]>=ma_slow[i]) else "bear" for i in range(n)]

def gen_switches(use_er: bool):
    events=[(0,'long')]; holding='long'; entry_i=0; last_shock=-10**9
    for i in range(MA_SLOW, n):
        if holding=='bear':
            r = -(px[i]/px[entry_i]-1); held=i-entry_i
            if r>=BEAR_TP or r<=-BEAR_SL or held>=MAX_HOLD:
                events.append((i,'long')); holding='long'; entry_i=i
        else:
            day_ret = px[i]/px[i-1]-1
            is_shock = day_ret<=SHOCK_TH
            er_trigger = False
            if use_er and er[i] is not None and i>=ER_WINDOW and px[i]<px[i-ER_WINDOW]:
                # 「非効率(ジグザグ)な下落が続いている」ことの新規検知(前日は非該当だった場合のみ)
                was_trigger_yesterday = (er[i-1] is not None and px[i-1]<px[i-1-ER_WINDOW] and er[i-1]<er_threshold) if i-1>=ER_WINDOW else False
                er_trigger = er[i]<er_threshold and not was_trigger_yesterday
            triggered = is_shock or er_trigger
            cd_ok = (i-last_shock)>=COOLDOWN
            if triggered and cd_ok and dc_regime[i]=='bear':
                events.append((i,'bear')); holding='bear'; entry_i=i; last_shock=i
            elif triggered:
                last_shock=i
    return events

def evaluate(events, start_year):
    start_date = dt.date(start_year,1,1)
    start_i = next(i for i,d in enumerate(dates) if d>=start_date)
    leg='long'
    for i,tgt in events:
        if i>start_i: break
        leg=tgt
    ev_in=[(i,tgt) for i,tgt in events if i>start_i]
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

base = gen_switches(False)
er_ver = gen_switches(True)

print(f"\n{'開始年':<8}{'買い持ち':>14}{'現行':>16}{'ER追加':>16}")
for y in (2000, 2006, 1965):
    eb, bh, nb = evaluate(base, y)
    ee, _, ne = evaluate(er_ver, y)
    print(f"{y}年〜 {bh:>12,.0f}円 {eb:>14,.0f}円({nb}回) {ee:>14,.0f}円({ne}回)")
