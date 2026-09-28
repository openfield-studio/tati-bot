#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市場ブレッド(値上がり銘柄比率、200日MA基準)の下抜けを、regime_shiftの追加エントリー
トリガーとして検証。同一市場(東証)・同一取引時間帯のデータのみを使うため、
VIX検証のような時差起因の先読みバイアスの心配がない。

トリガー: デッドクロス下落レジーム中、ブレッドが30%を新たに下抜けたら
(既に下抜けている間の連続発火を避けるため「新規下抜け」のみ)、ショックを待たずに
1571へ一時切替。既存の設計(20日最大保有、利確5%/損切り18%)はそのまま維持。

使い方: python market_breadth_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
import json
from collections import defaultdict

import yfinance as yf

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
BREADTH_TH = 0.30

with open("market_breadth_series.json", encoding="utf-8") as f:
    breadth_raw = json.load(f)
breadth_map = {dt.date.fromisoformat(k): v for k, v in breadth_raw.items()}

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)

breadth_series = []
last_b = None
for d in dates:
    if d in breadth_map:
        last_b = breadth_map[d]
    breadth_series.append(last_b)

def sma(arr, w):
    out = [None]*len(arr); s = 0.0
    for i, v in enumerate(arr):
        s += v
        if i >= w: s -= arr[i-w]
        if i >= w-1: out[i] = s/w
    return out

ma_fast = sma(px, MA_FAST); ma_slow = sma(px, MA_SLOW)
regime = ["bull" if (ma_fast[i] is None or ma_slow[i] is None or ma_fast[i] >= ma_slow[i]) else "bear" for i in range(n)]

def gen_switches(use_breadth: bool):
    events = [(0, "long")]
    holding = "long"; entry_i = 0; last_shock = -10**9
    for i in range(MA_SLOW, n):
        if holding == "bear":
            r = -(px[i]/px[entry_i]-1)
            held = i - entry_i
            if r >= BEAR_TP or r <= -BEAR_SL or held >= MAX_HOLD:
                events.append((i, "long")); holding = "long"; entry_i = i
        else:
            day_ret = px[i]/px[i-1]-1
            is_shock = day_ret <= SHOCK_TH
            breadth_trigger = False
            if use_breadth and breadth_series[i] is not None and breadth_series[i-1] is not None:
                breadth_trigger = breadth_series[i] < BREADTH_TH and breadth_series[i-1] >= BREADTH_TH
            triggered = is_shock or breadth_trigger
            cd_ok = (i - last_shock) >= COOLDOWN
            if triggered and cd_ok and regime[i] == "bear":
                events.append((i, "bear")); holding = "bear"; entry_i = i; last_shock = i
            elif triggered:
                last_shock = i
    return events

def evaluate(events, start_year):
    start_date = dt.date(start_year, 1, 1)
    start_i = next(i for i, d in enumerate(dates) if d >= start_date)
    leg = "long"
    for i, tgt in events:
        if i > start_i: break
        leg = tgt
    ev_in = [(i, tgt) for i, tgt in events if i > start_i]
    equity = PRINCIPAL; last_switch_eq = PRINCIPAL
    yearly = defaultdict(float); prev = px[start_i]
    ev_iter = iter(ev_in); next_ev = next(ev_iter, None)
    for i in range(start_i+1, n):
        ratio = px[i]/prev if leg == "long" else 1 + -(px[i]/prev-1)
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

base = gen_switches(False)
bw = gen_switches(True)

print(f"{'開始年':<8}{'買い持ち':>14}{'現行':>16}{'ブレッド追加':>16}")
for y in (2000, 2006, 2001):
    eb, bh, nb = evaluate(base, y)
    ew, _, nw = evaluate(bw, y)
    print(f"{y}年〜 {bh:>12,.0f}円 {eb:>14,.0f}円({nb}回) {ew:>14,.0f}円({nw}回)")

print("\n=== ブレッド追加で新規発生した2001-2003年の切替イベント ===")
base_i = set(i for i, _ in base)
bw_i = set(i for i, _ in bw)
new_ev = sorted(bw_i - base_i)
for i in new_ev:
    if dt.date(2001,1,1) <= dates[i] <= dt.date(2003,12,31):
        print(f"  {dates[i]}  breadth={breadth_series[i]*100:.1f}%")
print(f"\n新規発生総数(全期間): {len(new_ev)}件")
