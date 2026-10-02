#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CUSUM逐次変化点検知(累積和管理図)によるドリフト検知の実証検証
=====================================================================
調査待ちキュー#22(Page 1954の原典、Chu-Stinchcombe-White 1996等)。単発ショック
(1日-2.5%以下)では拾えない「持続的な弱気ドリフト」を、1日ごとの小さな下振れを
累積することで検知する片側CUSUM(下方シフト検知用)を試す。

設計(過剰最適化回避の方針):
- 基準ドリフトμ_0・許容幅kはIS期間の経験分布から算出(探索しない)。
  k = σ_IS / 2(標準的なCUSUMの経験則)。
- 決定閾値hは「結果が良くなるまで探す」のではなく、ARL(average run length、
  誤検知までの平均日数)較正で決める: IS期間のリターンをブートストラップ
  (ドリフト無しを模すためシャッフル再抽出)し、目標ARL(約250営業日=年1回程度の
  誤検知水準)になるhを逆算する。
- 既存の枠組み(dead-cross下落レジーム中、cooldown考慮)にCUSUMアラームを追加
  トリガーとして組み込み、現行(単発ショックのみ)と比較。
- h探索の妥当性確認のため、目標ARL(150/250/500)を振って頑健性も確認(ルール9)。

使い方: python cusum_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
import random
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

split = int(n * IS_RATIO)
is_rets = rets[1:split]
mu0 = st.mean(is_rets)
sigma = st.stdev(is_rets)
k = sigma / 2
print(f"IS期間: {dates[0]} ~ {dates[split]} ({split}本)")
print(f"μ0(基準ドリフト)={mu0*100:+.4f}%/日, σ={sigma*100:.4f}%/日, k(許容幅)={k*100:.4f}%/日")


def run_cusum(returns: list[float], h: float) -> list[int]:
    """下方シフト検知の片側CUSUM。アラーム発生インデックスのリストを返す(アラーム後リセット)。"""
    alarms = []
    s = 0.0
    for i, r in enumerate(returns):
        s = min(0.0, s + (r - mu0 + k))
        if s <= -h:
            alarms.append(i)
            s = 0.0
    return alarms


def calibrate_h(target_arl: float, n_sims: int = 200, sim_len: int = 2000, seed: int = 42) -> float:
    """IS期間のリターンをシャッフル再抽出(ドリフト無しを模す)してARLがtarget_arlになるhを二分探索。"""
    rng = random.Random(seed)

    def mean_arl(h: float) -> float:
        run_lengths = []
        for _ in range(n_sims):
            sim = [rng.choice(is_rets) for _ in range(sim_len)]
            alarms = run_cusum(sim, h)
            if alarms:
                run_lengths.append(alarms[0] + 1)
            else:
                run_lengths.append(sim_len)  # 未検知はsim_len扱い(下限近似)
        return st.mean(run_lengths)

    lo, hi = sigma * 0.5, sigma * 30
    for _ in range(20):
        mid = (lo + hi) / 2
        arl = mean_arl(mid)
        if arl < target_arl:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


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


def gen_switches(use_cusum: bool, h: float | None):
    events = [(0, 'long')]
    holding = 'long'; entry_i = 0; last_shock = -10**9
    s = 0.0  # CUSUM状態(全期間を通して前向きに更新、IS/OOSともに同じh・μ0・kを使う=先読みなし)
    for i in range(1, n):
        r = rets[i]
        if use_cusum:
            s = min(0.0, s + (r - mu0 + k))
        if i < MA_SLOW:
            continue
        if holding == 'bear':
            rr = -(px[i]/px[entry_i]-1); held = i-entry_i
            if rr >= BEAR_TP or rr <= -BEAR_SL or held >= MAX_HOLD:
                events.append((i, 'long')); holding = 'long'; entry_i = i
        else:
            is_shock = r <= SHOCK_TH
            cusum_alarm = False
            if use_cusum and s <= -h:
                cusum_alarm = True
                s = 0.0  # アラーム後リセット
            triggered = is_shock or cusum_alarm
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


base = gen_switches(False, None)

print("\n=== ARL較正(目標ARL=250営業日、ブートストラップ200回) ===")
h250 = calibrate_h(250)
print(f"較正されたh(目標ARL=250): {h250*100:.3f}%")

cusum250 = gen_switches(True, h250)
print(f"\n{'開始年':<8}{'買い持ち':>14}{'現行':>16}{'CUSUM追加(ARL250)':>20}")
for y in (2000, 2006, 1965):
    eb, bh, nb = evaluate(base, y)
    ec, _, nc = evaluate(cusum250, y)
    print(f"{y}年〜 {bh:>12,.0f}円 {eb:>14,.0f}円({nb}回) {ec:>14,.0f}円({nc}回)")

print("\n=== 頑健性チェック: 目標ARLを150/250/500で振る ===")
for target_arl in (150, 250, 500):
    h = calibrate_h(target_arl)
    ver = gen_switches(True, h)
    print(f"\n--- 目標ARL={target_arl}(h={h*100:.3f}%) ---")
    for y in (2000, 2006, 1965):
        eb, bh, nb = evaluate(base, y)
        ec, _, nc = evaluate(ver, y)
        print(f"  {y}年〜: 現行{eb:,.0f}円({nb}回) -> CUSUM追加{ec:,.0f}円({nc}回)  変化{(ec/eb-1)*100:+.1f}%")
