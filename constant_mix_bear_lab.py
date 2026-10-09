#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#29: Constant Mix(固定比率リバランス)によるベア側保有ルールの見直し。

事前登録(2026-10-09、計算前にユーザーへ提示):
  入る判断(デッドクロス中のショック-2.5%でSWITCH_TO_BEAR)は現行のまま。
  ベア保有中は 1571:現金 = w:(1-w) を保ち、1571の比率がwの±20%(相対)を外れたらwに戻す。
  利確+5%/損切り-18%/最大20日は使わず、デッドクロス終了で1321(100%)に戻る。
  w = IS期間(前半65%)のデッドクロス中に現行ルールで1571を保有していた日の割合。
  段階① ITバブル崩壊のデッドクロス期間でリバランス5回以上、かつリバランス上乗せ(戻しあり−戻しなし)>0。
        リーマンのデッドクロス期間はリバランス回数か上乗せがITバブル崩壊より小さい。
  段階② 2000/2006/1965年開始の3シナリオ全てで税引後最終資産が現行を上回る
  段階③ w±0.1で改善の符号が反転しない
  段階④ リバランス回数が61年で50回以上
使い方: python constant_mix_bear_lab.py [--stage2]
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
BAND_REL = 0.20

s = yf.Ticker("^N225").history(period="max", auto_adjust=True)["Close"].dropna()
s.index = pd.to_datetime(s.index.date)
dates = [d.date() for d in s.index]
px = [float(v) for v in s.values]
n = len(px)
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]
ma_f = s.rolling(MA_FAST).mean().values
ma_s = s.rolling(MA_SLOW).mean().values
bear = [(not math.isnan(ma_f[i]) and not math.isnan(ma_s[i]) and ma_f[i] < ma_s[i]) for i in range(n)]
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
                if (i - last_shock) >= COOLDOWN and bear[i]:
                    holding, entry_i = "bear", i
                last_shock = i
        st[i] = holding
    return st


BASE = base_states()
is_bear_days = [i for i in range(MA_SLOW, split) if bear[i]]
W_IS = sum(1 for i in is_bear_days if BASE[i] == "bear") / len(is_bear_days)


def cm_path(w: float) -> tuple[list[tuple[str, float]], list[int]]:
    """日次の(脚, 1571比率)。ベア保有はショック発火からデッドクロス終了まで。
    1571比率は値動きでドリフトし、wの±20%(相対)を外れた日にwへ戻す。"""
    out, rebals = [], []
    in_bear, last_shock, cur = False, -10**9, w
    for i in range(n):
        if i < MA_SLOW:
            out.append(("long", 1.0))
            continue
        if in_bear:
            if not bear[i]:
                in_bear = False
            else:
                r = -rets[i]
                cur = cur * (1 + r) / (cur * (1 + r) + (1 - cur))
                if abs(cur - w) > BAND_REL * w:
                    cur = w
                    rebals.append(i)
        if not in_bear:
            if rets[i] <= SHOCK_TH:
                if (i - last_shock) >= COOLDOWN and bear[i]:
                    in_bear, cur = True, w
                last_shock = i
        out.append(("bear", cur) if in_bear else ("long", 1.0))
    return out, rebals


def evaluate(states: list[tuple[str, float]], start_year: int) -> tuple[float, float]:
    start_i = idx(dt.date(start_year, 1, 1))
    equity = last_eq = PRINCIPAL
    peak, mdd = equity, 0.0
    yearly = defaultdict(float)
    for i in range(start_i + 1, n):
        leg, w = states[i - 1]
        equity *= 1 + (rets[i] * w if leg == "long" else -rets[i] * w)
        if states[i] != states[i - 1]:
            pl, pw = states[i - 1]
            cl, cw = states[i]
            turn = abs(cw - pw) if pl == cl else (pw + cw)
            if pl == cl and leg == "bear":
                turn = abs(cw - (pw * (1 - rets[i]) / (pw * (1 - rets[i]) + 1 - pw)))
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


def episode_stats(states, rebals, a: dt.date, b: dt.date, w: float) -> tuple[int, float, str]:
    """[a,b]内で最初にベア保有に入った日から、そのベア保有が終わるまでの区間。"""
    ia, ib = idx(a), idx(b)
    st = next((i for i in range(ia, ib) if states[i][0] == "bear"), None)
    if st is None:
        return 0, float("nan"), "ベア保有なし"
    en = next((i for i in range(st, n) if states[i][0] != "bear"), n - 1)
    k = sum(1 for r in rebals if st <= r <= en)
    v_cm = v_bh = 1.0
    hold_1571 = w
    for i in range(st + 1, en + 1):
        v_cm *= 1 + (-rets[i]) * states[i - 1][1]
        hold_1571 *= 1 - rets[i]
    v_bh = hold_1571 + (1 - w)
    return k, v_cm - v_bh, f"{dates[st]}〜{dates[en]}({en-st}営業日)"


def stage1() -> bool:
    w = W_IS
    print(f"w(IS期間のデッドクロス中に1571を保有していた日の割合) = {w:.3f}")
    states, rebals = cm_path(w)
    it = episode_stats(states, rebals, dt.date(2000, 8, 1), dt.date(2003, 4, 30), w)
    lb = episode_stats(states, rebals, dt.date(2008, 9, 1), dt.date(2009, 6, 30), w)
    print(f"ITバブル崩壊: {it[2]}  リバランス{it[0]}回  上乗せ(戻しあり−戻しなし) {it[1]*100:+.2f}%")
    print(f"リーマン    : {lb[2]}  リバランス{lb[0]}回  上乗せ {lb[1]*100:+.2f}%")
    ok_it = it[0] >= 5 and it[1] > 0
    ok_lb = (lb[0] < it[0]) or (lb[1] < it[1])
    print(f"判定: ITバブル崩壊(5回以上かつ上乗せ>0) {'OK' if ok_it else 'NG'} / "
          f"リーマンの方が小さい {'OK' if ok_lb else 'NG'}")
    yrs = defaultdict(lambda: [0, 0.0])
    for i in range(n):
        if states[i][0] == "bear":
            yrs[dates[i].year][0] += 1
    print("ベア保有日数(年別):", {y: v[0] for y, v in sorted(yrs.items()) if v[0]})
    print(f"全期間のリバランス回数: {len(rebals)}")
    ok = ok_it and ok_lb
    print(f"段階①判定: {'合格' if ok else 'NO-GO'}")
    return ok


def stage2() -> None:
    years = (2000, 2006, 1965)
    base = [(x, 1.0) for x in BASE]
    b = {y: evaluate(base, y) for y in years}
    print("\n" + " | ".join(f"{y}年〜" for y in years))
    print("現行      " + " | ".join(f"{b[y][0]:>13,.0f}円 DD{b[y][1]*100:.0f}%" for y in years))
    for w in (W_IS - 0.1, W_IS, W_IS + 0.1):
        if w <= 0:
            continue
        st, rb = cm_path(w)
        cells = []
        for y in years:
            eq, dd = evaluate(st, y)
            cells.append(f"{eq:>13,.0f}円 DD{dd*100:.0f}% ({(eq/b[y][0]-1)*100:+.1f}%)")
        print(f"w={w:.2f}  " + " | ".join(cells) + f"  リバランス{len(rb)}回")


if __name__ == "__main__":
    ok = stage1()
    if ok and "--stage2" in sys.argv:
        stage2()
