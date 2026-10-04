#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ワッサースタイン距離(最適輸送理論)による市場レジームのノンパラメトリック・クラスタリング
=====================================================================================
調査待ちキュー#24(2026-10-02追加)の実証検証。

Horvath, Issa & Muguruza (2021) "Clustering Market Regimes Using the Wasserstein Distance"が原典。
既存の#20 HMM(ガウス分布を仮定するパラメトリック手法、試行#89で重大NO-GO=判定不安定・過剰切替)とは
異なり、ローリング窓のリターンの実際の経験分布(平均・分散だけでなく歪度・尖度・裾の形まで)同士を
ワッサースタイン距離で比較し、分布の形そのものでレジームをクラスタリングするノンパラメトリック手法。

実装: 1次元経験分布間のワッサースタイン距離はscipy.stats.wasserstein_distanceで計算。
IS期間のみでWasserstein重心(barycenter)による2クラスタ(強気/弱気)のk-means型クラスタリングを
実施し、セントロイド(各クラスタの代表的な「ソート済みリターン分布の形」)をIS期間だけで固定する。
OOS期間は固定済みセントロイドとの距離だけで毎日の割当を行う(ルックアヘッドなし)。

1次元経験分布(同じサンプルサイズ)のWasserstein重心は、ソート済みサンプルの要素ごとの平均
(quantile関数の平均)に一致することが知られており、これによりk-medoidsのO(n^2)距離計算を
避け、O(n)の重心更新で済むk-means型の実装にしている。

既存のregime_shift_agent.py(デッドクロス regime判定+ショック検知でSWITCH_TO_BEAR)への
追加トリガーとして、「弱気クラスタへの新規突入(前日は違うクラスタだった)」かつ「既存の
デッドクロスregimeもbear」の時にSWITCH_TO_BEARを追加発火させる設計で検証する。

使い方: python wasserstein_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as st
from collections import defaultdict

import numpy as np
import yfinance as yf
from scipy.stats import wasserstein_distance

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
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]
rets_arr = np.array(rets)


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

split = int(n * IS_RATIO)


# --- ワッサースタインk-means(重心=ソート済みサンプルの要素ごと平均)-----------------

def rolling_windows(window: int) -> list[np.ndarray | None]:
    """各日について直近window日分のリターン配列(ソート済み)を返す。無ければNone。"""
    out: list[np.ndarray | None] = [None] * n
    for i in range(window, n):
        out[i] = np.sort(rets_arr[i - window + 1:i + 1])
    return out


def fit_wasserstein_kmeans(windows: list[np.ndarray | None], fit_end: int, window: int, n_iter: int = 15):
    """IS期間([window, fit_end))のみを使い、2クラスタのWasserstein重心を求める。"""
    is_idx = [i for i in range(window, fit_end) if windows[i] is not None]
    is_windows = [windows[i] for i in is_idx]
    is_means = [w.mean() for w in is_windows]

    # 初期シード: IS期間でウィンドウ平均リターンが最小/最大のものをそれぞれ弱気/強気の種にする
    bear_seed_idx = int(np.argmin(is_means))
    bull_seed_idx = int(np.argmax(is_means))
    centroid_bear = is_windows[bear_seed_idx].copy()
    centroid_bull = is_windows[bull_seed_idx].copy()

    for _ in range(n_iter):
        bear_members, bull_members = [], []
        for w in is_windows:
            d_bear = wasserstein_distance(w, centroid_bear)
            d_bull = wasserstein_distance(w, centroid_bull)
            if d_bear <= d_bull:
                bear_members.append(w)
            else:
                bull_members.append(w)
        if bear_members:
            centroid_bear = np.mean(np.stack(bear_members), axis=0)
        if bull_members:
            centroid_bull = np.mean(np.stack(bull_members), axis=0)

    # 平均リターンが低い方を「弱気」centroidとして確定
    if centroid_bear.mean() > centroid_bull.mean():
        centroid_bear, centroid_bull = centroid_bull, centroid_bear
    return centroid_bear, centroid_bull, len(bear_members), len(bull_members)


def classify_series(windows: list[np.ndarray | None], centroid_bear: np.ndarray, centroid_bull: np.ndarray) -> list[str | None]:
    out: list[str | None] = [None] * n
    for i, w in enumerate(windows):
        if w is None:
            continue
        d_bear = wasserstein_distance(w, centroid_bear)
        d_bull = wasserstein_distance(w, centroid_bull)
        out[i] = "bear" if d_bear <= d_bull else "bull"
    return out


# --- 記述統計: IT/リーマン/コロナでの弱気クラスタ滞在比率 -------------------------------

WINDOW_DESC = 20
windows_desc = rolling_windows(WINDOW_DESC)
centroid_bear_desc, centroid_bull_desc, n_bear_is, n_bull_is = fit_wasserstein_kmeans(windows_desc, split, WINDOW_DESC)
cluster_desc = classify_series(windows_desc, centroid_bear_desc, centroid_bull_desc)

print(f"=== IS期間クラスタリング結果(窓={WINDOW_DESC}日) ===")
print(f"  IS割当: 弱気{n_bear_is}件 / 強気{n_bull_is}件")
print(f"  弱気centroid平均リターン: {centroid_bear_desc.mean()*100:+.4f}%/日, 標準偏差: {centroid_bear_desc.std()*100:.4f}%")
print(f"  強気centroid平均リターン: {centroid_bull_desc.mean()*100:+.4f}%/日, 標準偏差: {centroid_bull_desc.std()*100:.4f}%")

periods = {
    "2000-2003 ITバブル崩壊(じわじわ型)": (dt.date(2000, 1, 1), dt.date(2003, 4, 30)),
    "2008-2009 リーマン(急激型)": (dt.date(2008, 9, 1), dt.date(2009, 3, 31)),
    "2020 コロナショック(急激型)": (dt.date(2020, 2, 15), dt.date(2020, 4, 15)),
}
print(f"\n=== 記述統計: 弱気クラスタ滞在比率・平均ワッサースタイン距離(窓={WINDOW_DESC}日) ===")
for label, (start, end) in periods.items():
    idx = [i for i in range(n) if windows_desc[i] is not None and start <= dates[i] <= end]
    if not idx:
        continue
    bear_ratio = sum(1 for i in idx if cluster_desc[i] == "bear") / len(idx)
    avg_d_bear = np.mean([wasserstein_distance(windows_desc[i], centroid_bear_desc) for i in idx])
    print(f"  {label}: 弱気クラスタ滞在比率={bear_ratio*100:.1f}% (n={len(idx)}), 弱気centroidとの平均距離={avg_d_bear*100:.4f}%")


# --- トレードルール化 ------------------------------------------------------------------

def gen_switches(window: int, use_wasserstein: bool):
    windows = rolling_windows(window)
    centroid_bear, centroid_bull, _, _ = fit_wasserstein_kmeans(windows, split, window)
    cluster = classify_series(windows, centroid_bear, centroid_bull) if use_wasserstein else None

    events = [(0, 'long')]
    holding = 'long'
    entry_i = 0
    last_shock = -10**9
    for i in range(MA_SLOW, n):
        if holding == 'bear':
            rr = -(px[i] / px[entry_i] - 1)
            held = i - entry_i
            if rr >= BEAR_TP or rr <= -BEAR_SL or held >= MAX_HOLD:
                events.append((i, 'long'))
                holding = 'long'
                entry_i = i
        else:
            r = rets[i]
            is_shock = r <= SHOCK_TH
            w_trigger = False
            if use_wasserstein and cluster[i] is not None:
                prev_ok = i - 1 >= window and cluster[i - 1] is not None
                was_bear_yesterday = cluster[i - 1] == "bear" if prev_ok else False
                w_trigger = cluster[i] == "bear" and not was_bear_yesterday
            triggered = is_shock or w_trigger
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


base = gen_switches(WINDOW_DESC, False)
print(f"\n{'開始年':<8}{'買い持ち':>14}{'現行':>16}{'Wasserstein追加(窓20)':>20}")
w20 = gen_switches(WINDOW_DESC, True)
for y in (2000, 2006, 1965):
    eb, bh, nb = evaluate(base, y)
    ew, _, nw = evaluate(w20, y)
    print(f"{y}年〜 {bh:>12,.0f}円 {eb:>14,.0f}円({nb}回) {ew:>18,.0f}円({nw}回)")

print("\n=== 頑健性チェック: 窓幅15/20/25/30日 ===")
for w in (15, 20, 25, 30):
    ver = gen_switches(w, True)
    print(f"\n--- 窓幅{w}日 ---")
    for y in (2000, 2006, 1965):
        eb, bh, nb = evaluate(base, y)
        ew, _, nw = evaluate(ver, y)
        change = (ew / eb - 1) * 100 if eb else float("nan")
        print(f"  {y}年〜: 現行{eb:,.0f}円({nb}回) -> Wasserstein追加{ew:,.0f}円({nw}回)  変化{change:+.1f}%")
