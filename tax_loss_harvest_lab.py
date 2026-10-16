#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#32: 損出し(Tax-Loss Harvesting)の検証。売買判断(regime_shift)は一切変えず、
税の扱いだけを変える。

税エンジン(本ファイルで実装):
  - 取得単価(basis)を保有ごとに追跡し、切替時の確定損益 = 売却額 − basis
  - 年内の確定損益を通算し、年末にプラス分へ20.315%課税
  - [繰越] 年間でマイナスになった分を翌年から3年間、確定益と相殺(古い順)
  - [損出し] 年末最終営業日に含み損(評価額<basis)なら売却→同日買い戻し(片道0.2%×2)で損失を確定
  - 税の支払いは保有の一部売却で賄う扱い(basisを支払比率だけ比例縮小)
  - [最終清算] 期末に全保有を売却して含み益にも課税(損出しは取得単価を下げて税を繰り延べるだけ
    なので、清算しない比較は損出しを過大評価する。主判定は清算あり)

事前登録(2026-10-16):
  段階①(キュー登録済み) (a)損失確定イベントが年平均1回以上 (b)損失確定のある年の半数以上で
        同年内に相殺対象の確定益がある(value_screenerは表示専用で売買シミュレーションがないため、
        regime_shift自身の確定益で判定)
  段階② 2000/2006/1965年開始の3シナリオ全てで税引後最終資産(清算あり)が現行を上回る
  段階③ 繰越あり・なしの両方で損出しの改善の符号が反転しない(損出しのみ・繰越のみの寄与も報告)
  段階④ 損出し実行回数を記録
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

s = yf.Ticker("^N225").history(period="max", auto_adjust=True)["Close"].dropna()
s.index = pd.to_datetime(s.index.date)
dates = [d.date() for d in s.index]
px = [float(v) for v in s.values]
n = len(px)
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]
ma_f = s.rolling(MA_FAST).mean().values
ma_s = s.rolling(MA_SLOW).mean().values
bear_regime = [(not pd.isna(ma_f[i]) and not pd.isna(ma_s[i]) and ma_f[i] < ma_s[i]) for i in range(n)]


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


STATES = base_states()


def start_idx(y: int) -> int:
    return next(i for i, d in enumerate(dates) if d >= dt.date(y, 1, 1))


def evaluate_original(start_year: int) -> float:
    """copper_gold_filter_lab.pyのevaluate()をそのまま再現(比較用)。"""
    si = start_idx(start_year)
    equity = last_eq = PRINCIPAL
    yearly = defaultdict(float)
    for i in range(si + 1, n):
        leg = STATES[i - 1]
        equity *= 1 + (rets[i] if leg == "long" else -rets[i])
        if STATES[i] != STATES[i - 1]:
            equity *= 1 - COST
            yearly[dates[i].year] += equity - last_eq
            last_eq = equity
        if i == n - 1 or dates[i + 1].year != dates[i].year:
            g = yearly.get(dates[i].year, 0.0)
            if g > 0:
                equity -= g * TAX_RATE
                last_eq = equity
    return equity


def evaluate(start_year: int, carry: bool, harvest: bool, liquidate: bool = True) -> dict:
    si = start_idx(start_year)
    equity = basis = PRINCIPAL
    realized = defaultdict(float)
    carry_list: list[list] = []  # [年, 残り損失額(正)]
    harvests = 0
    loss_events = defaultdict(int)
    gain_events = defaultdict(int)
    taxes = 0.0
    for i in range(si + 1, n):
        y = dates[i].year
        leg = STATES[i - 1]
        equity *= 1 + (rets[i] if leg == "long" else -rets[i])
        if STATES[i] != STATES[i - 1]:
            equity *= 1 - COST          # 売却側コスト(買付側は簡略化して同じ0.2%に含む既存方式)
            pl = equity - basis
            realized[y] += pl
            (loss_events if pl < 0 else gain_events)[y] += 1
            basis = equity
        last_day = i == n - 1 or dates[i + 1].year != y
        if last_day:
            if liquidate and i == n - 1:
                equity *= 1 - COST
                realized[y] += equity - basis
                basis = equity
            elif harvest and equity < basis:
                equity *= 1 - COST
                realized[y] += equity - basis
                equity *= 1 - COST
                basis = equity
                harvests += 1
            net = realized.get(y, 0.0)
            if carry:
                carry_list = [c for c in carry_list if y - c[0] <= 3 and c[1] > 0]
                for c in carry_list:
                    if net <= 0:
                        break
                    use = min(c[1], net)
                    c[1] -= use
                    net -= use
                if net < 0:
                    carry_list.append([y, -net])
            tax = TAX_RATE * max(0.0, net)
            if tax > 0:
                f = tax / equity
                equity -= tax
                basis *= 1 - f
                taxes += tax
    return {"equity": equity, "harvests": harvests, "taxes": taxes,
            "loss_events": loss_events, "gain_events": gain_events}


def stage1() -> bool:
    r = evaluate(1965, carry=False, harvest=False)
    years = range(dates[start_idx(1965)].year, dates[-1].year + 1)
    ny = len(years)
    tot_loss = sum(r["loss_events"].values())
    loss_years = [y for y in years if r["loss_events"].get(y, 0) > 0]
    with_gain = [y for y in loss_years if r["gain_events"].get(y, 0) > 0]
    a = tot_loss / ny
    b = len(with_gain) / len(loss_years) if loss_years else 0.0
    print(f"段階① 損失確定イベント: {tot_loss}回 / {ny}年 = 年平均{a:.2f}回 (基準1回以上 → {'OK' if a >= 1 else 'NG'})")
    print(f"      損失確定のある年 {len(loss_years)}年のうち同年内に確定益もある年 {len(with_gain)}年 = {b*100:.0f}% "
          f"(基準50%以上 → {'OK' if b >= 0.5 else 'NG'})")
    h = evaluate(1965, carry=False, harvest=True)
    print(f"      (参考)年末に含み損があり損出しを実行できた回数: {h['harvests']}回 / {ny}年")
    return a >= 1 and b >= 0.5


def main() -> None:
    print("税計算エンジンの確認(1965/2000/2006年開始、損出し・繰越なし)")
    for y in (1965, 2000, 2006):
        o = evaluate_original(y)
        f_nl = evaluate(y, False, False, liquidate=False)["equity"]
        f_l = evaluate(y, False, False, liquidate=True)["equity"]
        print(f"  {y}年〜 既存evaluate: {o:,.0f}円 / 取得単価追跡・清算なし: {f_nl:,.0f}円 / 同・最終清算あり: {f_l:,.0f}円")
    ok1 = stage1()
    print(f"段階①判定: {'合格' if ok1 else 'NO-GO'}")
    if not ok1:
        return
    print("\n段階②〜④(税引後最終資産、最終清算あり / 括弧内は清算なし)")
    combos = [("現行(繰越なし・損出しなし)", False, False), ("繰越のみ", True, False),
              ("損出しのみ", False, True), ("繰越+損出し", True, True)]
    res = {}
    for label, c, h in combos:
        for y in (2000, 2006, 1965):
            res[(label, y)] = (evaluate(y, c, h, True), evaluate(y, c, h, False))
    for label, c, h in combos:
        cells = []
        for y in (2000, 2006, 1965):
            eq, eq_nl = res[(label, y)][0]["equity"], res[(label, y)][1]["equity"]
            b, b_nl = res[(combos[0][0], y)][0]["equity"], res[(combos[0][0], y)][1]["equity"]
            cells.append(f"{y}〜 {eq:,.0f}円({(eq/b-1)*100:+.2f}%) [清算なし{(eq_nl/b_nl-1)*100:+.2f}%]")
        hv = res[(label, 1965)][0]["harvests"]
        print(f"  {label:<14} " + " | ".join(cells) + f"  損出し{hv}回")
    print("\n段階③ 損出しの寄与(繰越あり・なしそれぞれで、損出しを足した効果)")
    for base_label, with_label in (("現行(繰越なし・損出しなし)", "損出しのみ"), ("繰越のみ", "繰越+損出し")):
        diffs = [(res[(with_label, y)][0]["equity"] / res[(base_label, y)][0]["equity"] - 1) * 100 for y in (2000, 2006, 1965)]
        print(f"  {base_label}→{with_label}: " + ", ".join(f"{y}〜 {d:+.2f}%" for y, d in zip((2000, 2006, 1965), diffs)))


if __name__ == "__main__":
    main()
