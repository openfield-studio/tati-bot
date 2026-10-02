#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日次リターンの自己相関(AR(1)係数)によるレジームの質判定の実証検証
=====================================================================
regime_shift_agent.py(dead-cross下落レジーム判定+ショック〈1日-2.5%以下〉検知で
インバースETFに一時切替)は、リーマン・コロナ型の「急激で短期集中的な暴落」には
強いが、2000-2003年ITバブル崩壊のような「じわじわ長期間かけて進行する下落」には
弱い(単発ショックが前提のため緩やかな下落では発火しにくい)。

仮説: 急激なイベント型暴落(リーマン・コロナ)では日々の値動きはノイズに近い
(自己相関が弱い/負)。じわじわ型の構造的下落(ITバブル崩壊)では下落が持続する
モメンタム的性質を持ち、日次リターンに正の自己相関(今日下がったら明日も下がり
やすい)が観測されやすい可能性がある。

実装(過剰最適化回避の方針):
- 直近window日のローリングAR(1)係数(今日のリターンと前日のリターンの相関係数)
  を全期間で計算。
- IS期間(前65%)のAR(1)係数の中央値を閾値として固定(探索しない)。
- dead-cross下落レジーム中、ショックが起きていなくてもAR(1)係数が閾値を上回れば
  (正の自己相関=持続的下落の兆候)追加のベア切替トリガーとする。
- 既存設計(cooldown15日、最大保有20営業日、利確5%/損切り18%)はそのまま維持。
- window幅は1つの値(20日)に固定して結果を出した後、15日・25日でも頑健性を確認。

使い方: python ar1_regime_lab.py
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
AR1_WINDOW = 20  # 基準窓幅(固定、探索せず)。頑健性チェックで15/25も確認する。

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]

split = int(n * IS_RATIO)
print(f"全期間: {dates[0]} ~ {dates[-1]} ({n}本)")
print(f"IS期間: {dates[0]} ~ {dates[split]} ({split}本) / OOS期間: {dates[split]} ~ {dates[-1]}")


def rolling_ar1(returns: list[float], w: int) -> list[float | None]:
    """直近w日のリターンから日次自己相関(AR(1))係数(今日riと前日r(i-1)の相関係数)を計算。
    window内で定義できない(分散0等)場合はNone。先読みなし(i時点までのデータのみ使用)。"""
    out: list[float | None] = [None] * len(returns)
    for i in range(w, len(returns)):
        window = returns[i - w + 1:i + 1]
        x = window[:-1]
        y = window[1:]
        if len(x) < 2:
            continue
        mx, my = st.mean(x), st.mean(y)
        sx = st.pstdev(x)
        sy = st.pstdev(y)
        if sx == 0 or sy == 0:
            continue
        cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / len(x)
        out[i] = cov / (sx * sy)
    return out


def ar1_series_and_threshold(w: int):
    series = rolling_ar1(rets, w)
    is_vals = [v for v in series[1:split] if v is not None]
    threshold = st.median(is_vals)
    return series, threshold, is_vals


ar1_main, ar1_threshold_main, is_vals_main = ar1_series_and_threshold(AR1_WINDOW)
print(f"\n=== IS期間AR(1)係数の分布(window={AR1_WINDOW}日) ===")
print(f"中央値(閾値として採用)={ar1_threshold_main:+.4f}, 平均={st.mean(is_vals_main):+.4f}, "
      f"標準偏差={st.stdev(is_vals_main):.4f} (n={len(is_vals_main)})")


def period_ar1_stats(series, start: dt.date, end: dt.date):
    vals = [series[i] for i in range(n) if series[i] is not None and start <= dates[i] <= end]
    if not vals:
        return None
    return st.mean(vals), st.median(vals), len(vals)


print(f"\n=== 記述統計: 期間別AR(1)係数(window={AR1_WINDOW}日) ===")
print("仮説: じわじわ型(ITバブル崩壊)の方が、イベント型(リーマン・コロナ)より正の自己相関が強い")
periods = {
    "ITバブル崩壊(2000-2003、じわじわ型)": (dt.date(2000, 1, 1), dt.date(2003, 12, 31)),
    "リーマンショック(2008-2009、イベント型)": (dt.date(2008, 1, 1), dt.date(2009, 12, 31)),
    "コロナショック(2020、イベント型)": (dt.date(2020, 1, 1), dt.date(2020, 12, 31)),
}
period_means = {}
for label, (s, e) in periods.items():
    r = period_ar1_stats(ar1_main, s, e)
    if r:
        mean_v, med_v, cnt = r
        period_means[label] = mean_v
        print(f"{label}: 平均={mean_v:+.4f} 中央値={med_v:+.4f} (n={cnt}, IS期間閾値との比較: "
              f"{'閾値超え' if mean_v > ar1_threshold_main else '閾値以下'})")

dotcom_key = "ITバブル崩壊(2000-2003、じわじわ型)"
event_keys = ["リーマンショック(2008-2009、イベント型)", "コロナショック(2020、イベント型)"]
if dotcom_key in period_means and all(k in period_means for k in event_keys):
    dotcom_mean = period_means[dotcom_key]
    event_mean_avg = st.mean([period_means[k] for k in event_keys])
    supports = dotcom_mean > event_mean_avg
    print(f"\n仮説支持判定: ITバブル崩壊平均={dotcom_mean:+.4f} vs イベント型平均={event_mean_avg:+.4f} "
          f"-> {'仮説を支持' if supports else '仮説を支持しない'}")


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
dc_regime = ["bull" if (ma_fast[i] is None or ma_slow[i] is None or ma_fast[i] >= ma_slow[i]) else "bear"
             for i in range(n)]


def gen_switches(use_ar1: bool, ar1_series: list[float | None] | None, threshold: float | None):
    events = [(0, 'long')]
    holding = 'long'
    entry_i = 0
    last_shock = -10 ** 9
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
            ar1_alarm = False
            if use_ar1 and ar1_series[i] is not None and ar1_series[i] >= threshold:
                ar1_alarm = True
            triggered = is_shock or ar1_alarm
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


base = gen_switches(False, None, None)
ar1_rule_main = gen_switches(True, ar1_main, ar1_threshold_main)

print(f"\n=== トレードルール比較(window={AR1_WINDOW}日, 閾値={ar1_threshold_main:+.4f}) ===")
print(f"{'開始年':<8}{'買い持ち':>16}{'現行(ショックのみ)':>20}{'新案(AR1追加)':>18}")
for y in (2000, 2006, 1965):
    eb, bh, nb = evaluate(base, y)
    ea, _, na = evaluate(ar1_rule_main, y)
    print(f"{y}年〜 {bh:>14,.0f}円 {eb:>16,.0f}円({nb}回) {ea:>14,.0f}円({na}回) "
          f"変化{(ea / eb - 1) * 100:+.1f}%")

print("\n=== 頑健性チェック: window幅を15/20/25日で振る ===")
for w in (15, 20, 25):
    series, thr, is_vals = ar1_series_and_threshold(w)
    ver = gen_switches(True, series, thr)
    print(f"\n--- window={w}日(IS中央値閾値={thr:+.4f}) ---")
    for y in (2000, 2006, 1965):
        eb, bh, nb = evaluate(base, y)
        ea, _, na = evaluate(ver, y)
        print(f"  {y}年〜: 現行{eb:,.0f}円({nb}回) -> AR1追加{ea:,.0f}円({na}回)  変化{(ea / eb - 1) * 100:+.1f}%")
