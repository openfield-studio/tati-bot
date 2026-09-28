#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
メタラベリング(Meta-Labeling)の実証検証
=====================================================================
調査待ちキュー#17(López de Prado 2018 "Advances in Financial Machine Learning")。
既存のショック検知(regime_shift_agent.pyのデッドクロス+ショック)は検知した全シグナルに
一律のルールで反応する設計だが、メタラベリングは一次シグナル(ベアへの一時切替)とは別に、
そのシグナルを実際に採用するかどうかを判定する二次モデルを追加する。

現行設計(項目125で修正済み)では「デフォルトは常に1321保有、下落レジーム中のショックで
1571へ一時切替」が実質的な意思決定ポイントなので、この「切替の採否」をメタラベリングの
対象にする。

方法:
- 日経平均61年データで、現行のSWITCH_TO_BEARイベント全件を再現し、各イベントの発生時点で
  分かる特徴量(ショック幅・レジームの深さ・直近ボラティリティ)と、結果(勝敗)を記録
- IS(前65%)でロジスティック回帰を学習(過学習回避のため特徴量は3つに限定)
- OOS(後35%)で「モデルの勝率予測が閾値を超えた時だけ切替を採用」した場合の成績を、
  「全シグナルを無条件に採用」の現行版と比較
- サンプル数が少ない(過去61年でSWITCH_TO_BEARはn=70〜90程度)ため、過学習リスクを
  ルール9に従い明記する

使い方: python meta_labeling_lab.py
"""
from __future__ import annotations
import datetime as dt
import math
from collections import defaultdict

import numpy as np
import yfinance as yf

MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
VOL_WINDOW = 20

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)
rets = [0.0] + [px[i]/px[i-1]-1 for i in range(1, n)]


def sma(arr, w):
    out = [None]*len(arr); s = 0.0
    for i, v in enumerate(arr):
        s += v
        if i >= w: s -= arr[i-w]
        if i >= w-1: out[i] = s/w
    return out


ma_fast = sma(px, MA_FAST)
ma_slow = sma(px, MA_SLOW)
regime = ["bull" if (ma_fast[i] is None or ma_slow[i] is None or ma_fast[i] >= ma_slow[i]) else "bear" for i in range(n)]

vol20 = [None]*n
for i in range(VOL_WINDOW, n):
    w = rets[i-VOL_WINDOW+1:i+1]
    vol20[i] = (sum((r - sum(w)/len(w))**2 for r in w) / len(w)) ** 0.5

# --- 現行設計をそのまま再現し、SWITCH_TO_BEARイベントを特徴量付きで記録 ---
events = []
holding = "long"; entry_i = 0; last_shock = -10**9
for i in range(MA_SLOW, n):
    if holding == "bear":
        r = -(px[i]/px[entry_i]-1)
        held = i - entry_i
        if r >= BEAR_TP or r <= -BEAR_SL or held >= MAX_HOLD:
            win = 1 if r > 0 else 0
            events[-1]["outcome_ret"] = r
            events[-1]["win"] = win
            holding = "long"; entry_i = i
    else:
        day_ret = rets[i]
        is_shock = day_ret <= SHOCK_TH
        cd_ok = (i - last_shock) >= COOLDOWN
        if is_shock and cd_ok and regime[i] == "bear":
            ma_gap = (ma_slow[i]/ma_fast[i] - 1) if (ma_fast[i] and ma_slow[i]) else 0.0
            feat_vol = vol20[i] if vol20[i] is not None else 0.0
            events.append({"i": i, "date": dates[i], "shock_mag": day_ret,
                            "ma_gap": ma_gap, "vol20": feat_vol})
            holding = "bear"; entry_i = i; last_shock = i
        elif is_shock:
            last_shock = i

# 未決済(最後まで手仕舞いしなかった)イベントを除外
events = [e for e in events if "win" in e]
print(f"SWITCH_TO_BEARイベント総数: {len(events)}")
print(f"全体の勝率: {sum(e['win'] for e in events)/len(events)*100:.1f}%")

# --- IS/OOS分割(時系列65/35) ---
split = int(len(events) * 0.65)
is_events = events[:split]
oos_events = events[split:]
print(f"IS: {len(is_events)}件 ({is_events[0]['date']}~{is_events[-1]['date']})")
print(f"OOS: {len(oos_events)}件 ({oos_events[0]['date']}~{oos_events[-1]['date']})")


def to_xy(evs):
    X = np.array([[e["shock_mag"], e["ma_gap"], e["vol20"]] for e in evs])
    y = np.array([e["win"] for e in evs])
    return X, y


X_is, y_is = to_xy(is_events)
X_oos, y_oos = to_xy(oos_events)

# 標準化(ISの平均・標準偏差で、OOSにも同じものを適用=先読み回避)
mu, sigma = X_is.mean(axis=0), X_is.std(axis=0)
sigma[sigma == 0] = 1.0
X_is_n = (X_is - mu) / sigma
X_oos_n = (X_oos - mu) / sigma


def fit_logistic(X, y, lr=0.1, epochs=2000, l2=0.01):
    n_feat = X.shape[1]
    w = np.zeros(n_feat); b = 0.0
    for _ in range(epochs):
        z = X @ w + b
        p = 1 / (1 + np.exp(-z))
        grad_w = X.T @ (p - y) / len(y) + l2 * w
        grad_b = (p - y).mean()
        w -= lr * grad_w
        b -= lr * grad_b
    return w, b


w, b = fit_logistic(X_is_n, y_is)
print(f"\nロジスティック回帰係数(標準化後): shock_mag={w[0]:+.3f} ma_gap={w[1]:+.3f} vol20={w[2]:+.3f} bias={b:+.3f}")

p_oos = 1 / (1 + np.exp(-(X_oos_n @ w + b)))

# --- OOSで: 全採用 vs メタラベリングでフィルター(閾値0.5) ---
oos_rets = np.array([e["outcome_ret"] for e in oos_events])
oos_rets_cost = oos_rets - 0.002  # 往復コスト概算

all_adopt_mean = oos_rets_cost.mean()
for th in (0.4, 0.5, 0.6):
    mask = p_oos >= th
    n_taken = mask.sum()
    if n_taken == 0:
        print(f"閾値{th}: 採用件数0件(判定不能)")
        continue
    filtered_mean = oos_rets_cost[mask].mean()
    filtered_winrate = (oos_rets[mask] > 0).mean() * 100
    print(f"\n閾値{th}: OOS {n_taken}/{len(oos_events)}件採用、"
          f"平均リターン{filtered_mean*100:+.2f}%(勝率{filtered_winrate:.0f}%) "
          f"vs 全採用{all_adopt_mean*100:+.2f}%(勝率{(oos_rets>0).mean()*100:.0f}%)")

print("\n注意: OOSイベント数が少ない(n={})ため、この結果の統計的信頼性は低い。"
      "ルール9に従い過学習リスクを明記する。".format(len(oos_events)))
