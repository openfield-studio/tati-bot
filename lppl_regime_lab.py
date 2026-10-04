#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LPPL(対数周期的べき乗則、Log-Periodic Power Law)モデルによる
「反転バブル(anti-bubble)」検出の実証検証(調査待ちキュー#25)
===========================================================
Johansen & Sornette (1999)の原典に基づく。対数価格を
    ln p(t) = A + B*(t-tc)^m * [1 + C*cos(omega*ln(t-tc) - phi)]
にフィットする。t > tc(ピーク後)で使う「反転バブル」形。

実装上の簡略化(安定性優先、Filimonov & Sornette 2013の「slaving」法を採用):
- C*cos(omega*ln(t')-phi) = C1*cos(omega*ln t') + C2*sin(omega*ln t') と三角関数展開すると、
  tc・m・omegaを固定すれば A,B,C1,C2 については線形回帰(最小二乗)になる。
  非線形パラメータはm・omegaのみをグリッドサーチし、A,B,C1,C2は各グリッド点で
  closed-formに解く(scipyのcurve_fit等の局所最適化より格段に安定)。
- tcは「窓内の価格ピーク(直近高値)」に固定(フィット対象外にすることで次元を1つ削減)。

「減速する対数周期性」は関数形自体に内包される(ピーク後(t-tc)^m形を使う時点で、
位相の瞬間角速度 d/dt[omega*ln(t-tc)] = omega/(t-tc) は t が進むほど減少=減速する)。
よってモデルのフィット品質(R²・振動振幅の有意性)自体が「反転バブル的パターンの強さ」を表す。

使い方: python lppl_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as st
import sys
from collections import defaultdict

import numpy as np
import yfinance as yf

sys.stdout.reconfigure(encoding="utf-8")

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
IS_RATIO = 0.65

M_GRID = np.arange(0.1, 0.95, 0.1)       # べき指数候補
OMEGA_GRID = np.arange(3.0, 17.0, 2.0)   # 対数周期角振動数候補(文献の典型範囲5〜15を含む)
MIN_POST_PEAK = 60                        # ピーク後の最小観測点数
R2_QUALIFY = 0.30                         # フィット品質の最低基準
AMP_RATIO_MIN, AMP_RATIO_MAX = 0.02, 2.0  # 振動振幅/トレンド振幅の妥当範囲

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
logpx = np.log(px)
n = len(px)
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]


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


def lppl_slaved_fit(logp_window: np.ndarray, peak_local_idx: int):
    """窓内logp_windowに対し、ピークをtcとして固定しpost-peak部分をLPPL(slaved)フィット。
    戻り値: (best_r2, best_m, best_omega, amp_ratio) または None(データ不足・フィット不可)"""
    post = logp_window[peak_local_idx:]
    k = len(post) - 1  # peak自体(t'=0)を除いた後続点数
    if k < MIN_POST_PEAK:
        return None
    y = post[1:]  # t'=1..k
    tprime = np.arange(1, k + 1, dtype=float)
    ln_tprime = np.log(tprime)

    best_sse = np.inf
    best = None
    sst = np.sum((y - np.mean(y)) ** 2)
    if sst <= 0:
        return None

    for m in M_GRID:
        tp_m = tprime ** m
        for omega in OMEGA_GRID:
            cos_t = tp_m * np.cos(omega * ln_tprime)
            sin_t = tp_m * np.sin(omega * ln_tprime)
            X = np.column_stack([np.ones_like(tprime), tp_m, cos_t, sin_t])
            try:
                coef, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
            except np.linalg.LinAlgError:
                continue
            if rank < 4:
                continue
            resid = y - X @ coef
            sse = float(np.sum(resid ** 2))
            if sse < best_sse:
                best_sse = sse
                A, B, C1, C2 = coef
                amp = float(np.hypot(C1, C2))
                best = (m, omega, A, B, amp)

    if best is None:
        return None
    m, omega, A, B, amp = best
    r2 = 1.0 - best_sse / sst
    amp_ratio = amp / abs(B) if abs(B) > 1e-12 else np.inf
    return r2, m, omega, amp_ratio


def confidence_indicator(end_i: int, window_lengths=(250, 375, 500)) -> tuple[int, int]:
    """end_i時点で複数窓長を使い、何個の窓が『反転バブル的パターン』条件を満たすか。
    戻り値: (qualify_count, total_checked)"""
    qualify = 0
    checked = 0
    for wl in window_lengths:
        start_i = end_i - wl + 1
        if start_i < 0:
            continue
        seg = logpx[start_i:end_i + 1]
        peak_local = int(np.argmax(seg))
        res = lppl_slaved_fit(seg, peak_local)
        checked += 1
        if res is None:
            continue
        r2, m, omega, amp_ratio = res
        if r2 >= R2_QUALIFY and 0.0 < m < 1.0 and AMP_RATIO_MIN <= amp_ratio <= AMP_RATIO_MAX:
            qualify += 1
    return qualify, checked


# ============================================================
# 1. 1990年バブル崩壊後の再現チェック(原著対象期間)
# ============================================================
print("=== 1. 1990年バブル崩壊後(原著対象)の再現チェック ===")
check_dates = [dt.date(y, m, 1) for y in (1991, 1992, 1993, 1994) for m in (1, 7)]
for cd in check_dates:
    idx = next((i for i, d in enumerate(dates) if d >= cd), None)
    if idx is None or idx < 500:
        continue
    q, c = confidence_indicator(idx, (250, 375, 500))
    print(f"  {cd}: confidence={q}/{c}")

# ============================================================
# 2. 記述統計: IT/リーマン/コロナでのConfidence Indicator比較(bear regime日のみ)
# ============================================================
print("\n=== 2. 記述統計: 危機期間でのConfidence Indicator(bear regime日のみ、窓500固定でR²参考値) ===")
periods = {
    "2000-2003 ITバブル崩壊(じわじわ型)": (dt.date(2000, 1, 1), dt.date(2003, 4, 30)),
    "2008-2009 リーマン(急激型)": (dt.date(2008, 9, 1), dt.date(2009, 3, 31)),
    "2020 コロナショック(急激型)": (dt.date(2020, 2, 15), dt.date(2020, 4, 15)),
}
sample_stride = 5  # 計算コスト削減のため5営業日おきにサンプリング
for label, (pstart, pend) in periods.items():
    confs = []
    for i in range(500, n, sample_stride):
        if not (pstart <= dates[i] <= pend):
            continue
        if dc_regime[i] != "bear":
            continue
        q, c = confidence_indicator(i, (250, 375, 500))
        if c > 0:
            confs.append(q / c)
    if confs:
        print(f"  {label}: 平均confidence比率={st.mean(confs):.2f} (n={len(confs)}サンプル, bear regime日のみ)")
    else:
        print(f"  {label}: bear regime日なし、またはサンプルなし")

# ============================================================
# 3. トレードルール化
# ============================================================
print("\n=== 3. トレードルール化: 2000/2006/1965年開始での比較 ===")


def gen_switches(use_lppl: bool, conf_threshold: int = 2, stride: int = 3):
    events = [(0, "long")]
    holding = "long"
    entry_i = 0
    last_shock = -10 ** 9
    last_lppl_conf = 0
    for i in range(MA_SLOW, n):
        if holding == "bear":
            rr = -(px[i] / px[entry_i] - 1)
            held = i - entry_i
            if rr >= BEAR_TP or rr <= -BEAR_SL or held >= MAX_HOLD:
                events.append((i, "long"))
                holding = "long"
                entry_i = i
        else:
            r = rets[i]
            is_shock = r <= SHOCK_TH
            lppl_trigger = False
            if use_lppl and dc_regime[i] == "bear" and (i % stride == 0):
                q, c = confidence_indicator(i, (250, 375, 500))
                conf_now = 1 if (c > 0 and q >= conf_threshold) else 0
                lppl_trigger = conf_now == 1 and last_lppl_conf == 0
                last_lppl_conf = conf_now
            triggered = is_shock or lppl_trigger
            cd_ok = (i - last_shock) >= COOLDOWN
            if triggered and cd_ok and dc_regime[i] == "bear":
                events.append((i, "bear"))
                holding = "bear"
                entry_i = i
                last_shock = i
            elif triggered:
                last_shock = i
    return events


def evaluate(events, start_year):
    start_date = dt.date(start_year, 1, 1)
    start_i = next(i for i, d in enumerate(dates) if d >= start_date)
    leg = "long"
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
        ratio = px[i] / prev if leg == "long" else 1 + -(px[i] / prev - 1)
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


base = gen_switches(False)
lppl_ver = gen_switches(True, conf_threshold=2, stride=3)
print(f"{'開始年':<8}{'買い持ち':>14}{'現行':>16}{'LPPL追加(conf>=2/3)':>20}")
for y in (2000, 2006, 1965):
    eb, bh, nb = evaluate(base, y)
    el, _, nl = evaluate(lppl_ver, y)
    print(f"{y}年〜 {bh:>12,.0f}円 {eb:>14,.0f}円({nb}回) {el:>18,.0f}円({nl}回)")

# ============================================================
# 4. 頑健性チェック: confidence閾値を振る
# ============================================================
print("\n=== 4. 頑健性チェック: confidence閾値1/3・2/3・3/3 ===")
for th in (1, 2, 3):
    ver = gen_switches(True, conf_threshold=th, stride=3)
    print(f"\n--- 閾値 {th}/3 ---")
    for y in (2000, 2006, 1965):
        eb, bh, nb = evaluate(base, y)
        el, _, nl = evaluate(ver, y)
        change = (el / eb - 1) * 100 if eb != 0 else float("nan")
        print(f"  {y}年〜: 現行{eb:,.0f}円({nb}回) -> LPPL追加{el:,.0f}円({nl}回)  変化{change:+.1f}%")

print("\n完了。")
