#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EMD(経験的モード分解)による「V字回復/L字回復」判別の実証検証
=====================================================================
調査待ちキュー#26(2026-10-04追加)。Mahata et al. (2020)の個別銘柄向け手法
(EMDでIMFに分解し、回復を担う低周波IMFの特徴的時間スケールτが明確か不定かで
財務健全性を判別)を、市場全体(日経平均)のレジーム判定に転用。

仮説: イベント型の急落(リーマン・コロナ)はショック後に特徴的な時間スケールτを持つ
明確なV字の戻りIMFが現れる(隣接する評価時点間でτが安定)が、構造的・じわじわ型の
下落(ITバブル崩壊)は回復を担う低周波IMFの時間スケールが不定(隣接評価時点間でτが
ばらつく、またはそもそも定義できない)という仮説。

実装の簡略化(正直に記録):
- EEMD(アンサンブル版、モード混合対策)ではなく標準EMDを使用。EEMDは1回の分解に
  標準EMDの数十〜100倍の計算コストがかかり、本検証の規模(61年・複数窓・複数評価点)
  では非現実的。標準EMDは実測で1回あたり約0.03秒(窓250日)と高速で、日次ローリング
  計算が現実的な時間で完走する
- 日次ローリングではなく、計算量削減のため3営業日おき(STEP=3)に評価点を間引いている。
  間引いた間は直近の評価値をフォワードフィルする(未来の情報は一切使わない)
- τの安定性(CV)は「厳密に10日前・20日前」ではなく、逐次計算の過程でキャッシュされた
  直近3回の評価点(間隔は概ね0・3・6営業日前)を使う実装上の簡略化

使い方: python emd_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as st
import time
from collections import defaultdict

import numpy as np
import yfinance as yf
from PyEMD import EMD

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
IS_RATIO = 0.65
STEP = 3  # 計算量削減のための間引き間隔(営業日)
CV_THRESHOLD = 0.15  # tau安定性の変動係数しきい値(IS期間の中央値から別途決定)

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
logpx = np.log(np.array(px))
n = len(px)
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]

emd = EMD()


def compute_tau(window: int, end_idx: int) -> float:
    """end_idxを含むwindow日間のlog価格をEMD分解し、残差を除いた最低周波IMFの
    周期(ゼロクロス法)を返す。定義できない場合はnanを返す。"""
    seg = logpx[end_idx - window + 1:end_idx + 1]
    try:
        imfs = emd(seg)
    except Exception:
        return float("nan")
    if imfs.shape[0] < 2:
        return float("nan")
    imf_low = imfs[-2]  # 最後(残差/トレンド)の1つ手前=最低周波の振動成分
    zc = int(np.sum(np.diff(np.sign(imf_low)) != 0))
    if zc < 2:
        return float("nan")
    return window / (zc / 2)


def tau_confident_series(window: int, step: int = STEP) -> list[float | None]:
    """各営業日についてtau安定性フラグ(1.0=明確/V字、0.0=不定/L字、None=未計算)を返す。
    STEP営業日おきにtauを計算し、直近3回の計算値(概ね0/STEP/2*STEP営業日前)のCVで判定。
    間引いた日は直近のフラグをフォワードフィル(先読みなし)。"""
    confident: list[float | None] = [None] * n
    tau_cache: list[float] = []
    last_flag = None
    for i in range(window - 1, n):
        if (i - (window - 1)) % step == 0:
            tau_i = compute_tau(window, i)
            tau_cache.append(tau_i)
            if len(tau_cache) > 3:
                tau_cache.pop(0)
            if len(tau_cache) == 3 and all(not np.isnan(t) for t in tau_cache):
                m = st.mean(tau_cache)
                sd = st.pstdev(tau_cache)
                cv = sd / m if m > 0 else float("inf")
                last_flag = 1.0 if cv < CV_THRESHOLD else 0.0
            else:
                last_flag = 0.0  # tau未定義が混じる=不安定とみなす(L字側)
        confident[i] = last_flag
    return confident


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

print("=== 記述統計: tau(低周波IMFの周期)の明確さ(窓=250日、STEP=3) ===")
t0 = time.time()
conf_desc = tau_confident_series(250)
print(f"(計算時間: {time.time()-t0:.1f}秒)")

periods = {
    "2000-2003 ITバブル崩壊(じわじわ型)": (dt.date(2000, 1, 1), dt.date(2003, 4, 30)),
    "2008-2009 リーマン(急激型)": (dt.date(2008, 9, 1), dt.date(2009, 3, 31)),
    "2020 コロナショック(急激型)": (dt.date(2020, 2, 15), dt.date(2020, 4, 15)),
}
for label, (start, end) in periods.items():
    vals = [conf_desc[i] for i in range(n) if conf_desc[i] is not None and start <= dates[i] <= end and dc_regime[i] == "bear"]
    if vals:
        print(f"  {label}: bear regime日のtau明確(V字)比率={st.mean(vals)*100:.1f}% (n={len(vals)})")
    else:
        print(f"  {label}: bear regime該当日なし(サンプルなし)")


def gen_switches(window: int, use_emd: bool, cv_threshold: float = CV_THRESHOLD, step: int = STEP):
    global CV_THRESHOLD
    orig_th = CV_THRESHOLD
    CV_THRESHOLD = cv_threshold
    conf = tau_confident_series(window, step) if use_emd else None
    CV_THRESHOLD = orig_th

    events = [(0, "long")]
    holding = "long"
    entry_i = 0
    last_shock = -10**9
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
            emd_trigger = False
            if use_emd and conf[i] is not None:
                was_yesterday_lshape = conf[i - 1] == 0.0 if i - 1 >= window else False
                emd_trigger = conf[i] == 0.0 and not was_yesterday_lshape
            triggered = is_shock or emd_trigger
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


print("\n=== トレードルール比較(窓250日、CV閾値0.15) ===")
t0 = time.time()
base = gen_switches(250, False)
emd250 = gen_switches(250, True)
print(f"(計算時間: {time.time()-t0:.1f}秒)")
print(f"{'開始年':<8}{'買い持ち':>14}{'現行':>16}{'EMD追加(窓250)':>18}")
for y in (2000, 2006, 1965):
    eb, bh, nb = evaluate(base, y)
    ee, _, ne = evaluate(emd250, y)
    chg = (ee / eb - 1) * 100
    print(f"{y}年〜 {bh:>12,.0f}円 {eb:>14,.0f}円({nb}回) {ee:>14,.0f}円({ne}回) 変化{chg:+.1f}%")

print("\n=== 頑健性チェック1: 窓幅 200/250/300/350日(CV閾値0.15固定、STEP=5で簡略化) ===")
for w in (200, 250, 300, 350):
    t0 = time.time()
    ver = gen_switches(w, True, cv_threshold=0.15, step=5)
    dt_calc = time.time() - t0
    print(f"\n--- 窓幅{w}日 (計算時間{dt_calc:.1f}秒) ---")
    for y in (2000, 2006, 1965):
        eb, bh, nb = evaluate(base, y)
        ee, _, ne = evaluate(ver, y)
        print(f"  {y}年〜: 現行{eb:,.0f}円({nb}回) -> EMD追加{ee:,.0f}円({ne}回) 変化{(ee/eb-1)*100:+.1f}%")

print("\n=== 頑健性チェック2: CV閾値 0.10/0.15/0.20/0.25(窓250日、STEP=5で簡略化) ===")
for th in (0.10, 0.15, 0.20, 0.25):
    t0 = time.time()
    ver = gen_switches(250, True, cv_threshold=th, step=5)
    dt_calc = time.time() - t0
    print(f"\n--- CV閾値{th} (計算時間{dt_calc:.1f}秒) ---")
    for y in (2000, 2006, 1965):
        eb, bh, nb = evaluate(base, y)
        ee, _, ne = evaluate(ver, y)
        print(f"  {y}年〜: 現行{eb:,.0f}円({nb}回) -> EMD追加{ee:,.0f}円({ne}回) 変化{(ee/eb-1)*100:+.1f}%")
