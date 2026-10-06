#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#27(ボラティリティ・ターゲティング)・#28(CPPI)の検証。
regime_shiftの「1321保有中」の保有比率だけを0〜100%で調整し、残りは現金(レバレッジなし)。
1571への切替ロジックは現行のまま。目標比率から20pt以上ずれたときだけ調整する。

事前登録(2026-10-07、計算前にユーザーへ提示):
 #27 保有比率 = 目標ボラ / 直近20日実現ボラ(上限1)、目標ボラ=IS(前半65%)の平均20日ボラ
 #28 保有比率 = m*(V-F)/V(0〜1)、F = 0.8*Vの過去最高値、m = 1/IS期間の1日最大下落率
 段階① キューの登録基準どおり
   #27: ITバブル崩壊期(2000-04〜2003-03)の20日ボラ月次平均 >= 1998-01〜1999-12の1.5倍、
        かつ上昇開始(20日ボラが平時平均の1.5倍を初めて超えた日)がデッドクロス確定より20営業日以上前
   #28: ITバブル崩壊でCPPI保有比率が平時平均の50%以下になるのがデッドクロス確定より20営業日以上前、
        かつリーマンで最初のショック(-2.5%)から20営業日以内に同水準まで低下
 段階② 2000/2006/1965年開始の3シナリオ全てで税引後最終資産が現行を上回る
 段階③ #27窓15/20/30日、#28フロア0.75/0.80/0.85で改善の符号が反転しない
 段階④ 保有比率の調整回数が61年で50回以上
使い方: python position_sizing_overlay_lab.py [--stage2]
"""
from __future__ import annotations

import datetime as dt
import math
import sys
from collections import defaultdict

import pandas as pd
import yfinance as yf

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
IS_RATIO = 0.65
BAND = 0.20

s = yf.Ticker("^N225").history(period="max", auto_adjust=True)["Close"].dropna()
s.index = pd.to_datetime(s.index.date)
dates = [d.date() for d in s.index]
px = [float(v) for v in s.values]
n = len(px)
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]
ma_f = s.rolling(MA_FAST).mean().values
ma_s = s.rolling(MA_SLOW).mean().values
bear_regime = [(not math.isnan(ma_f[i]) and not math.isnan(ma_s[i]) and ma_f[i] < ma_s[i]) for i in range(n)]
split = int(n * IS_RATIO)


def idx(d: dt.date) -> int:
    return next(i for i, x in enumerate(dates) if x >= d)


def base_states() -> list[str]:
    st = ["long"] * n
    holding, entry_i, last_shock = "long", 0, -10**9
    for i in range(MA_SLOW, n):
        if holding == "bear":
            rr = -(px[i] / px[entry_i] - 1)
            if rr >= BEAR_TP or rr <= -BEAR_SL or i - entry_i >= MAX_HOLD:
                holding, entry_i = "long", i
        else:
            if rets[i] <= SHOCK_TH:
                if (i - last_shock) >= COOLDOWN and bear_regime[i]:
                    holding, entry_i = "bear", i
                last_shock = i
        st[i] = holding
    return st


def realized_vol(window: int) -> list[float]:
    out = [float("nan")] * n
    for i in range(window, n):
        seg = rets[i - window + 1:i + 1]
        m = sum(seg) / window
        out[i] = math.sqrt(sum((x - m) ** 2 for x in seg) / (window - 1)) * math.sqrt(245)
    return out


def vt_target(window: int) -> list[float]:
    vol = realized_vol(window)
    is_vals = [v for v in vol[:split] if not math.isnan(v)]
    tgt = sum(is_vals) / len(is_vals)
    return [1.0 if math.isnan(v) or v <= 0 else min(1.0, tgt / v) for v in vol], vol, tgt


M_CPPI = 1 / abs(min(rets[1:split]))


def cppi_exposure_path(floor_ratio: float) -> list[float]:
    """1321保有を前提にした理論上のCPPI比率(バンドなし)。資産Vは自分自身の運用結果。"""
    v, peak, out = 1.0, 1.0, []
    w = 1.0
    for i in range(n):
        if i > 0:
            v *= 1 + w * rets[i]
        peak = max(peak, v)
        floor = floor_ratio * peak
        w = max(0.0, min(1.0, M_CPPI * (v - floor) / v))
        out.append(w)
    return out


def apply_band(target: list[float], base: list[str]) -> tuple[list[tuple[str, float]], int]:
    cur, out, adj = 1.0, [], 0
    for i in range(n):
        if base[i] == "long":
            if abs(target[i] - cur) >= BAND or (target[i] >= 0.999 and cur < 1.0 and abs(target[i] - cur) > 0.05):
                cur = target[i]
                adj += 1
            out.append(("long", cur))
        else:
            out.append(("bear", 1.0))
    return out, adj


def cppi_states(floor_ratio: float, base: list[str]) -> tuple[list[tuple[str, float]], int]:
    """CPPIは自分の資産推移に依存するため、バンド適用を同時に回す。"""
    v, peak, cur, adj, out = 1.0, 1.0, 1.0, 0, []
    for i in range(n):
        if i > 0:
            leg, w = out[-1]
            v *= 1 + (w * rets[i] if leg == "long" else -rets[i])
        peak = max(peak, v)
        if base[i] == "long":
            tgt = max(0.0, min(1.0, M_CPPI * (v - floor_ratio * peak) / v))
            if abs(tgt - cur) >= BAND or (tgt >= 0.999 and cur < 1.0 and abs(tgt - cur) > 0.05):
                cur = tgt
                adj += 1
            out.append(("long", cur))
        else:
            out.append(("bear", 1.0))
    return out, adj


def evaluate(states: list[tuple[str, float]], start_year: int) -> tuple[float, float]:
    start_i = idx(dt.date(start_year, 1, 1))
    equity = last_eq = PRINCIPAL
    peak, mdd = equity, 0.0
    yearly = defaultdict(float)
    for i in range(start_i + 1, n):
        leg, w = states[i - 1]
        equity *= 1 + (rets[i] * w if leg == "long" else -rets[i])
        if states[i] != states[i - 1]:
            pw = states[i - 1][1] if states[i - 1][0] == "long" else 1.0
            cw = states[i][1] if states[i][0] == "long" else 1.0
            turn = abs(cw - pw) if states[i][0] == states[i - 1][0] else max(pw, cw)
            equity *= 1 - COST * turn
            yearly[dates[i].year] += equity - last_eq
            last_eq = equity
        if i == n - 1 or dates[i + 1].year != dates[i].year:
            g = yearly.get(dates[i].year, 0.0)
            if g > 0:
                equity -= g * TAX_RATE
                last_eq = equity
        peak = max(peak, equity)
        mdd = max(mdd, 1 - equity / peak)
    return equity, mdd


def stage1() -> dict[str, bool]:
    res = {}
    # デッドクロス確定: ITバブル期にbear_regimeがFalse→Trueになった最初の日(2000年以降)
    i0 = idx(dt.date(2000, 1, 1))
    dc = next(i for i in range(i0, n) if bear_regime[i] and not bear_regime[i - 1])
    print(f"デッドクロス確定(2000年以降の初回): {dates[dc]}")
    calm = (idx(dt.date(1998, 1, 1)), idx(dt.date(2000, 1, 1)))
    tgt0, tgt1 = idx(dt.date(2000, 4, 1)), idx(dt.date(2003, 4, 1))

    _, vol, tgt = vt_target(20)
    v = pd.Series(vol, index=s.index)
    calm_m = v.iloc[calm[0]:calm[1]].resample("ME").mean().mean()
    tgt_m = v.iloc[tgt0:tgt1].resample("ME").mean().mean()
    first = next((i for i in range(i0, tgt1) if not math.isnan(vol[i]) and vol[i] >= 1.5 * calm_m), None)
    lead = (dc - first) if first is not None else None
    ok1 = tgt_m >= 1.5 * calm_m
    ok2 = lead is not None and lead >= 20
    print(f"\n#27 ボラ: 平時(1998-99)月次平均 {calm_m*100:.1f}% / ITバブル崩壊期 {tgt_m*100:.1f}% "
          f"(倍率 {tgt_m/calm_m:.2f}、基準1.5倍以上 → {'OK' if ok1 else 'NG'})")
    print(f"    平時の1.5倍を初めて超えた日: {dates[first] if first is not None else 'なし'} "
          f"→ デッドクロス確定の{lead}営業日前(基準20以上 → {'OK' if ok2 else 'NG'})")
    print(f"    (参考)IS平均20日ボラ=目標値 {tgt*100:.1f}%")
    res["#27"] = ok1 and ok2

    expo = cppi_exposure_path(0.80)
    e = pd.Series(expo, index=s.index)
    calm_e = e.iloc[calm[0]:calm[1]].mean()
    thr = 0.5 * calm_e
    first_c = next((i for i in range(i0, tgt1) if expo[i] <= thr), None)
    lead_c = (dc - first_c) if first_c is not None else None
    lehman_shock = next(i for i in range(idx(dt.date(2008, 9, 1)), n) if rets[i] <= SHOCK_TH)
    hit_l = next((i for i in range(lehman_shock, min(n, lehman_shock + 60)) if expo[i] <= thr), None)
    lag_l = (hit_l - lehman_shock) if hit_l is not None else None
    ok3 = lead_c is not None and lead_c >= 20
    ok4 = lag_l is not None and lag_l <= 20
    print(f"\n#28 CPPI(m={M_CPPI:.2f}、フロア80%): 平時平均の保有比率 {calm_e*100:.0f}% → 基準 {thr*100:.0f}%以下")
    print(f"    ITバブル崩壊で基準以下になった日: {dates[first_c] if first_c is not None else 'なし'} "
          f"→ デッドクロス確定の{lead_c}営業日前(基準20以上 → {'OK' if ok3 else 'NG'})")
    print(f"    リーマン最初のショック{dates[lehman_shock]}から基準以下まで: {lag_l}営業日(基準20以内 → {'OK' if ok4 else 'NG'})")
    res["#28"] = ok3 and ok4
    print(f"\n段階①判定: #27 {'合格' if res['#27'] else 'NO-GO'} / #28 {'合格' if res['#28'] else 'NO-GO'}")
    return res


def stage2(which: list[str]) -> None:
    base = base_states()
    base_t = [(x, 1.0) for x in base]
    years = (2000, 2006, 1965)
    b = {y: evaluate(base_t, y) for y in years}
    print("\n段階②〜④  " + " | ".join(f"{y}年〜" for y in years))
    print("現行      " + " | ".join(f"{b[y][0]:>13,.0f}円 DD{b[y][1]*100:.0f}%" for y in years))
    variants = []
    if "#27" in which:
        for w in (15, 20, 30):
            tg, _, _ = vt_target(w)
            variants.append((f"#27 窓{w}日", *apply_band(tg, base)))
    if "#28" in which:
        for f in (0.75, 0.80, 0.85):
            variants.append((f"#28 フロア{int(f*100)}%", *cppi_states(f, base)))
    for label, st, adj in variants:
        cells = []
        for y in years:
            eq, dd = evaluate(st, y)
            cells.append(f"{eq:>13,.0f}円 DD{dd*100:.0f}% ({(eq/b[y][0]-1)*100:+.1f}%)")
        print(f"{label:<10}" + " | ".join(cells) + f"  調整{adj}回")


if __name__ == "__main__":
    r = stage1()
    passed = [k for k, v in r.items() if v]
    if "--stage2" in sys.argv and passed:
        stage2(passed)
