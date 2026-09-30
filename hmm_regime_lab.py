#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
マルコフ・レジームスイッチングモデル(隠れマルコフモデル、HMM)によるレジーム判定の実証検証
=====================================================================================
調査待ちキュー#20(Hamilton 1989基礎文献、日経平均への直接応用例あり)。既存のデッドクロス
方式(120日/350日MA、固定閾値のルールベース)を、2状態ガウスHMM(強気/弱気)に置き換えた
場合に、regime_shift戦略の成績(特にIT バブル崩壊のような「じわじわ型下落」)が改善するか
検証する。

hmmlearnはビルド環境の制約(Visual C++ Build Tools不足)でインストールできなかったため、
numpyで2状態ガウスHMM(Baum-Welch EM)を自前実装。

先読み防止: パラメータ(遷移確率・各状態の平均/分散)はIS期間(前65%)のみで学習して固定し、
OOS期間ではその固定パラメータのまま前向き(過去→現在の情報のみを使う「フィルタリング」、
未来を使う「スムージング」ではない)にレジームを推定する。

使い方: python hmm_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
from collections import defaultdict

import numpy as np
import yfinance as yf

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
IS_RATIO = 0.65


def fit_gaussian_hmm_2state(returns: np.ndarray, n_iter: int = 100, seed: int = 42):
    """2状態ガウスHMMをBaum-Welch EMで学習。状態0=強気(平均>0想定)、状態1=弱気。"""
    rng = np.random.default_rng(seed)
    T = len(returns)
    # 初期値: 状態0=平均+リターン・低ボラ、状態1=平均-リターン・高ボラ
    mu = np.array([returns.mean() + returns.std()*0.3, returns.mean() - returns.std()*0.5])
    var = np.array([returns.var()*0.5, returns.var()*2.0])
    A = np.array([[0.98, 0.02], [0.05, 0.95]])   # 遷移行列(持続性を仮定した初期値)
    pi = np.array([0.7, 0.3])

    for it in range(n_iter):
        # --- E-step: forward-backward(スケーリング付き) ---
        B = np.zeros((T, 2))
        for s in range(2):
            B[:, s] = np.exp(-0.5*(returns-mu[s])**2/var[s]) / np.sqrt(2*np.pi*var[s])
        B = np.clip(B, 1e-300, None)

        alpha = np.zeros((T, 2))
        c = np.zeros(T)
        alpha[0] = pi * B[0]
        c[0] = alpha[0].sum()
        alpha[0] /= c[0]
        for t in range(1, T):
            alpha[t] = (alpha[t-1] @ A) * B[t]
            c[t] = alpha[t].sum()
            if c[t] <= 0:
                c[t] = 1e-300
            alpha[t] /= c[t]

        beta = np.zeros((T, 2))
        beta[-1] = 1.0
        for t in range(T-2, -1, -1):
            beta[t] = (A @ (B[t+1] * beta[t+1])) / c[t+1]

        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True)

        xi_sum = np.zeros((2, 2))
        for t in range(T-1):
            denom = c[t+1]
            xi_t = (alpha[t][:, None] * A * B[t+1][None, :] * beta[t+1][None, :]) / denom
            xi_sum += xi_t

        # --- M-step ---
        pi = gamma[0].copy()
        A_new = xi_sum / xi_sum.sum(axis=1, keepdims=True)
        mu_new = (gamma * returns[:, None]).sum(axis=0) / gamma.sum(axis=0)
        var_new = (gamma * (returns[:, None]-mu_new[None, :])**2).sum(axis=0) / gamma.sum(axis=0)
        var_new = np.clip(var_new, 1e-8, None)

        A, mu, var = A_new, mu_new, var_new

    # 状態ラベル: 平均リターンが低い方を「弱気(bear)」とする
    bear_state = int(np.argmin(mu))
    return {"mu": mu, "var": var, "A": A, "pi": pi, "bear_state": bear_state}


def filter_states(returns: np.ndarray, params: dict) -> np.ndarray:
    """固定パラメータで前向きフィルタリング(過去→現在のみ、未来を見ない)し、
    各時点でのP(弱気状態)を返す。"""
    mu, var, A, pi = params["mu"], params["var"], params["A"], params["pi"]
    T = len(returns)
    B = np.zeros((T, 2))
    for s in range(2):
        B[:, s] = np.exp(-0.5*(returns-mu[s])**2/var[s]) / np.sqrt(2*np.pi*var[s])
    B = np.clip(B, 1e-300, None)

    alpha = np.zeros((T, 2))
    alpha[0] = pi * B[0]
    alpha[0] /= alpha[0].sum()
    for t in range(1, T):
        alpha[t] = (alpha[t-1] @ A) * B[t]
        s = alpha[t].sum()
        alpha[t] /= s if s > 0 else 1e-300
    return alpha[:, params["bear_state"]]


print("=== データ取得 ===")
df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
dates = [d for d, _ in closes]
px = [p for _, p in closes]
n = len(px)
rets = np.array([0.0] + [px[i]/px[i-1]-1 for i in range(1, n)])

split = int(n * IS_RATIO)
print(f"IS: {dates[0]} ~ {dates[split]} ({split}本)")
print(f"OOS: {dates[split]} ~ {dates[-1]} ({n-split}本)")

print("\n=== IS期間でHMMパラメータを学習中(EM、100回反復) ===")
params = fit_gaussian_hmm_2state(rets[1:split])  # rets[0]=0.0(先頭ダミー)は除外
print(f"状態0: 平均{params['mu'][0]*100:+.3f}%/日, 標準偏差{params['var'][0]**0.5*100:.3f}%")
print(f"状態1: 平均{params['mu'][1]*100:+.3f}%/日, 標準偏差{params['var'][1]**0.5*100:.3f}%")
print(f"弱気状態と判定: 状態{params['bear_state']}")
print(f"遷移行列:\n{params['A']}")

print("\n=== 全期間(IS+OOS)を固定パラメータで前向きフィルタリング ===")
p_bear = filter_states(rets[1:], params)
p_bear = np.concatenate([[0.0], p_bear])  # 先頭のダミー分を揃える

# レジーム判定: P(弱気)>=0.5を「下落相場」とする(単純な閾値、探索はしない)
hmm_regime = ["bear" if p_bear[i] >= 0.5 else "bull" for i in range(n)]

bear_days = sum(1 for r in hmm_regime if r == "bear")
print(f"弱気判定日数: {bear_days}/{n} ({bear_days/n*100:.1f}%)")

np.save("hmm_p_bear.npy", p_bear)
print("hmm_p_bear.npyに保存(次のバックテストスクリプトで再利用)")
