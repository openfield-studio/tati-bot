#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ドローダウン継続日数(高値未更新日数)によるレジーム判定の実証検証
=====================================================================
regime_shift_agent.py(1321/1571デッドクロス戦略、120日/350日MA)は、デッドクロス下落
レジーム中に1日-2.5%以下の急落(ショック)を検知したらインバースETFへ一時切替する設計。
これは2008年リーマンのような「急激で短期集中的な暴落」には強いが、2000-2003年のITバブル
崩壊のような「じわじわ長期間かけて進行する下落」には弱い(ショック前提のため)。

今回のアイデア:
「直近252営業日高値からの経過営業日数(高値未更新日数)」という時間軸の指標を、デッドクロス
下落レジーム中の追加のベア切替トリガーとする(ショックが起きていなくても発火できるようにする)。
下落の「深さ」ではなく「いつまでも高値を更新できていない期間」を見る点がdrawdown_regime_lab.py
(深さ=ドローダウン率)とは異なる。

設計(過剰最適化回避の方針、cusum_regime_lab.pyの枠組みを流用):
- 日経平均(^N225)全期間終値を使用。
- 各日について、直近252営業日高値からの経過営業日数(高値未更新日数、先読みなし)を計算。
- IS期間(前65%)の経験分布(中央値・75パーセンタイル)から閾値を決める(探索しない)。
- デッドクロス下落レジーム中、この経過日数が閾値を超えたら、既存のショック検知に加えて
  追加のベア切替トリガーとする。既存の設計(cooldown15日、最大保有20営業日、
  利確5%/損切り18%)はそのまま維持。
- 閾値を1つに固定して結果を出した後、隣接する2-3個の閾値でも頑健性を確認する。

使い方: python drawdown_duration_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as st
from collections import defaultdict, deque

import yfinance as yf

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
IS_RATIO = 0.65
HIGH_WINDOW = 252

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]

split = int(n * IS_RATIO)
print(f"全期間: {dates[0]} ~ {dates[-1]} ({n}本)")
print(f"IS期間: {dates[0]} ~ {dates[split]} ({split}本)")


def days_since_high(prices: list[float], window: int) -> list[int]:
    """各日について、直近window営業日(その日を含む)の最高値を記録した日からの経過営業日数
    (先読みなし、単調減少dequeでO(n))。当日が高値更新ならduration=0。"""
    dq: deque[tuple[int, float]] = deque()
    out = [0] * len(prices)
    for i, p in enumerate(prices):
        while dq and dq[0][0] <= i - window:
            dq.popleft()
        while dq and dq[-1][1] <= p:
            dq.pop()
        dq.append((i, p))
        out[i] = i - dq[0][0]
    return out


dur = days_since_high(px, HIGH_WINDOW)

# ---------------------------------------------------------------
# 1. 記述統計: IS期間の分布から閾値候補を決める + 主要局面の比較
# ---------------------------------------------------------------
is_dur = dur[1:split]
dur_median = st.median(is_dur)
dur_p75 = st.quantiles(is_dur, n=4)[2]
print(f"\n=== IS期間の高値未更新日数(営業日)の分布 ===")
print(f"中央値={dur_median:.0f}日, 75%tile={dur_p75:.0f}日, 最大={max(is_dur)}日, 平均={st.mean(is_dur):.1f}日")

periods = [
    ("ITバブル崩壊(2000-2003)", dt.date(2000, 1, 1), dt.date(2003, 12, 31)),
    ("リーマンショック(2008-2009)", dt.date(2008, 1, 1), dt.date(2009, 12, 31)),
    ("コロナショック(2020)", dt.date(2020, 1, 1), dt.date(2020, 12, 31)),
]
print("\n=== 主要局面における高値未更新日数の平均・最大値 ===")
for label, d0, d1 in periods:
    idxs = [i for i, d in enumerate(dates) if d0 <= d <= d1]
    if not idxs:
        print(f"  {label}: データなし")
        continue
    vals = [dur[i] for i in idxs]
    print(f"  {label}: 平均{st.mean(vals):.0f}日 最大{max(vals)}日 (n={len(vals)}営業日)")

# ---------------------------------------------------------------
# 2. トレードルール化(cusum_regime_lab.pyの枠組みを流用)
# ---------------------------------------------------------------


def sma(arr, w):
    out = [None] * len(arr)
    s = 0.0
    for i, v in enumerate(arr):
        s += v
        if i >= w:
            s -= arr[i - w]
        if i >= w - 1:
            out[i] = s / w
    return out


ma_fast = sma(px, MA_FAST)
ma_slow = sma(px, MA_SLOW)
dc_regime = ["bull" if (ma_fast[i] is None or ma_slow[i] is None or ma_fast[i] >= ma_slow[i]) else "bear" for i in range(n)]


def gen_switches(use_dur: bool, dur_th: int | None):
    events = [(0, 'long')]
    holding = 'long'
    entry_i = 0
    last_shock = -10**9
    for i in range(1, n):
        r = rets[i]
        if i < MA_SLOW:
            continue
        if holding == 'bear':
            rr = -(px[i] / px[entry_i] - 1)
            held = i - entry_i
            if rr >= BEAR_TP or rr <= -BEAR_SL or held >= MAX_HOLD:
                events.append((i, 'long'))
                holding = 'long'
                entry_i = i
        else:
            is_shock = r <= SHOCK_TH
            dur_alarm = use_dur and dur[i] >= dur_th
            triggered = is_shock or dur_alarm
            cd_ok = (i - last_shock) >= COOLDOWN
            if triggered and cd_ok and dc_regime[i] == 'bear':
                events.append((i, 'bear'))
                holding = 'bear'
                entry_i = i
                last_shock = i
            elif triggered:
                last_shock = i
    return events


def evaluate(events, start_year):
    start_date = dt.date(start_year, 1, 1)
    start_i = next(i for i, d in enumerate(dates) if d >= start_date)
    leg = 'long'
    for i, tgt in events:
        if i > start_i:
            break
        leg = tgt
    ev_in = [(i, tgt) for i, tgt in events if i > start_i]
    equity = PRINCIPAL
    last_switch_eq = PRINCIPAL
    yearly = defaultdict(float)
    prev = px[start_i]
    ev_iter = iter(ev_in)
    next_ev = next(ev_iter, None)
    for i in range(start_i + 1, n):
        ratio = px[i] / prev if leg == 'long' else 1 + -(px[i] / prev - 1)
        equity *= ratio
        prev = px[i]
        while next_ev is not None and next_ev[0] == i:
            equity *= (1 - COST)
            yearly[dates[i].year] += equity - last_switch_eq
            last_switch_eq = equity
            leg = next_ev[1]
            next_ev = next(ev_iter, None)
        if i == n - 1 or dates[i + 1].year != dates[i].year:
            g = yearly.get(dates[i].year, 0.0)
            if g > 0:
                tax = g * TAX_RATE
                equity -= tax
                last_switch_eq = equity
    bh = PRINCIPAL * (px[-1] / px[start_i])
    return equity, bh, len(ev_in)


base = gen_switches(False, None)

print("\n=== トレードルール比較(固定閾値=IS中央値) ===")
dur_th_fixed = int(round(dur_median))
print(f"固定閾値: 高値未更新日数 >= {dur_th_fixed}日")
new_rule = gen_switches(True, dur_th_fixed)
print(f"\n{'開始年':<8}{'買い持ち':>16}{'現行(ショックのみ)':>20}{'新案(ショック+継続日数)':>24}")
for y in (2000, 2006, 1965):
    eb, bh, nb = evaluate(base, y)
    en, _, nn = evaluate(new_rule, y)
    print(f"{y}年〜 {bh:>14,.0f}円 {eb:>16,.0f}円({nb}回) {en:>18,.0f}円({nn}回)")

print("\n=== 頑健性チェック: 閾値を振る(IS中央値・P75近傍) ===")
candidate_ths = sorted(set([
    max(5, dur_th_fixed - 20),
    dur_th_fixed,
    int(round(dur_p75)),
    int(round(dur_p75)) + 20,
]))
for th in candidate_ths:
    ver = gen_switches(True, th)
    print(f"\n--- 閾値={th}日 ---")
    for y in (2000, 2006, 1965):
        eb, bh, nb = evaluate(base, y)
        ev, _, nv = evaluate(ver, y)
        diff = (ev / eb - 1) * 100 if eb else float('nan')
        print(f"  {y}年〜: 現行{eb:,.0f}円({nb}回) -> 新案{ev:,.0f}円({nv}回)  変化{diff:+.1f}%")
