#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
銅÷金比率を「状態フィルター」としてregime_shiftに組み込む段階②〜④の検証
(macro_indicator_descriptive_lab.pyで段階①合格、SESSION_LOG項目151)。

設計(事前登録、2026-10-05):
  現行: 常時1321保有、デッドクロス中にショック(-2.5%)が来たら1571へ最大20日。
  変更: デッドクロス中 かつ 銅÷金の12ヶ月変化がマイナス(米国データ1営業日ラグ)の間は、
        1321を持たず現金(参考版: 50%保有)。1571への切替ロジックは現行のまま。
合格基準(事前登録):
  ② 2000年・2006年開始の両方で現行より改善(1965年はデータ無しで対象外)
  ③ 判定期間189/252/315営業日で改善の符号が反転しない
  ④ 現金⇔保有の切替回数を報告(極端に少なければ少数取引依存として不合格)
課税考慮・コストはqar_rebound_lab.pyと同じ。
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

import pandas as pd
import yfinance as yf

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20


def close(t: str) -> pd.Series:
    s = yf.Ticker(t).history(period="max", auto_adjust=True)["Close"].dropna()
    s.index = pd.to_datetime(s.index.date)
    return s


n225 = close("^N225")
dates = [d.date() for d in n225.index]
px = [float(v) for v in n225.values]
n = len(px)
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]
ma_f = n225.rolling(MA_FAST).mean().values
ma_s = n225.rolling(MA_SLOW).mean().values
bear_regime = [(not pd.isna(ma_f[i]) and not pd.isna(ma_s[i]) and ma_f[i] < ma_s[i]) for i in range(n)]

ratio = (close("HG=F") / close("GC=F")).dropna()


def warn_series(lookback: int) -> list[bool]:
    w = (ratio.diff(lookback) < 0).where(ratio.diff(lookback).notna()).shift(1)
    w = w.reindex(n225.index, method="ffill")
    return [bool(v) if not pd.isna(v) else False for v in w.values]


def base_states() -> list[str]:
    """現行regime_shiftの日次ポジション('long'/'bear')。"""
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


def apply_filter(base: list[str], warn: list[bool], weight: float) -> list[tuple[str, float]]:
    out = []
    for i in range(n):
        if base[i] == "long" and bear_regime[i] and warn[i]:
            out.append(("long", weight))
        else:
            out.append((base[i], 1.0))
    return out


def evaluate(states: list[tuple[str, float]], start_year: int) -> tuple[float, int]:
    start_i = next(i for i, d in enumerate(dates) if d >= dt.date(start_year, 1, 1))
    equity = PRINCIPAL
    last_eq = PRINCIPAL
    yearly = defaultdict(float)
    switches = 0
    for i in range(start_i + 1, n):
        leg, w = states[i - 1]
        r = rets[i]
        day = r * w if leg == "long" else -r
        equity *= 1 + day
        if states[i] != states[i - 1]:
            prev_w = states[i - 1][1] if states[i - 1][0] == "long" else 1.0
            cur_w = states[i][1] if states[i][0] == "long" else 1.0
            turnover = abs(cur_w - prev_w) if states[i][0] == states[i - 1][0] else max(prev_w, cur_w)
            equity *= 1 - COST * turnover
            yearly[dates[i].year] += equity - last_eq
            last_eq = equity
            switches += 1
        if i == n - 1 or dates[i + 1].year != dates[i].year:
            g = yearly.get(dates[i].year, 0.0)
            if g > 0:
                equity -= g * TAX_RATE
                last_eq = equity
    return equity, switches


def main() -> None:
    base = base_states()
    base_t = [(s, 1.0) for s in base]
    print("判定期間 | 版 | 2000年〜 | 2006年〜")
    rows = {}
    for y in (2000, 2006):
        rows[("base", y)] = evaluate(base_t, y)
    print(f"現行      | {rows[('base', 2000)][0]:>14,.0f}円({rows[('base', 2000)][1]}回) | "
          f"{rows[('base', 2006)][0]:>14,.0f}円({rows[('base', 2006)][1]}回)")
    for lb in (189, 252, 315):
        warn = warn_series(lb)
        for label, wgt in (("現金", 0.0), ("50%", 0.5)):
            st = apply_filter(base, warn, wgt)
            res = [evaluate(st, y) for y in (2000, 2006)]
            chg = [(res[k][0] / rows[("base", y)][0] - 1) * 100 for k, y in enumerate((2000, 2006))]
            print(f"{lb}日 {label:<4} | {res[0][0]:>14,.0f}円({res[0][1]}回) {chg[0]:+6.1f}% | "
                  f"{res[1][0]:>14,.0f}円({res[1][1]}回) {chg[1]:+6.1f}%")
    warn = warn_series(252)
    on = sum(1 for i in range(n) if base[i] == "long" and bear_regime[i] and warn[i])
    print(f"\n(252日)フィルターで現金化された日数: {on}日")
    yrs = defaultdict(int)
    for i in range(n):
        if base[i] == "long" and bear_regime[i] and warn[i]:
            yrs[dates[i].year] += 1
    print("年別:", dict(sorted(yrs.items())))


if __name__ == "__main__":
    main()
