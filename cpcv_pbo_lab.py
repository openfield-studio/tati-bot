#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1306 CPCV / PBO(Combinatorial Purged Cross-Validation / Probability of
Backtest Overfitting)検証ラボ
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

Bailey, Borwein, Lopez de Prado, Zhu (2017) "The Probability of Backtest
Overfitting"。今日実装したDeflated Sharpe Ratio(単一のIS/OOS分割・試行数で
評価)よりさらに厳密に、「学習/検証の分割の仕方を総当たりで変えたとき、
IS側で一番良く見えた設定がOOS側でも一番良いままか」を検証する。

手順(CSCV: Combinatorially Symmetric Cross-Validation):
 1. 全期間をS個の等分ブロックに分割する(S=10)。
 2. ブロックの半分(5個)を選ぶ組み合わせ全パターン(C(10,5)=252通り)について:
    a. 選んだ5ブロック=学習(IS)、残り5ブロック=検証(OOS)とみなす。
    b. N個の候補パラメータ(IdeaAgent4案+OptimizeAgent12通り=16通り)を
       IS側の日次Sharpeでランキングし、一番良い設定(勝者)を選ぶ。
    c. その勝者がOOS側では何位につけるか(順位を0〜1の比率に変換)を見る。
    d. 順位比率をlogit変換し、集める。
 3. PBO = 「IS側の勝者がOOS側で中央値より悪い」割合(logit<0の割合)。
    PBOが高いほど「IS側で一番良く見える設定を選ぶ」という行為自体が
    当てにならない(過剰最適化しやすい)ことを意味する。

使い方: python cpcv_pbo_lab.py
"""
from __future__ import annotations
import itertools
import math

from research_agents import ResearchConfig, StrategyParams, Backtester, MetricsAgent

S_BLOCKS = 10  # ブロック数(C(10,5)=252通り、計算量とのバランス)
IDEA_SEEDS = [(30, 50, 0.05), (30, 55, 0.05), (35, 50, 0.05), (25, 55, 0.06)]
OPT_GRID = [(ov, ex, stop) for ov in (30, 35, 40) for ex in (50, 55) for stop in (0.05, 0.08)]
ALL_CONFIGS = IDEA_SEEDS + OPT_GRID  # 16通り


def daily_returns(eq: list[float]) -> list[float]:
    return [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]


def sharpe_of(rets: list[float]) -> float:
    if len(rets) < 2:
        return -1e9
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = var ** 0.5
    return mean / std if std > 0 else -1e9


def sp(oversold, exit_, stop):
    return StrategyParams("x", "rsi_only", 0, 0, 14, 75, oversold, exit_, stop, 0.0)


def main() -> None:
    prices = [float(l.strip()) for l in open("prices_1306.csv") if l.strip()]
    cfg = ResearchConfig()
    bt = Backtester(cfg)

    print(f"1306: {len(prices)}本 / 候補パラメータ N={len(ALL_CONFIGS)}通り")
    print("各候補の全期間日次リターン系列を計算中 ...")

    # config毎の日次リターン系列(全期間)を用意
    all_rets = []
    for ov, ex, stop in ALL_CONFIGS:
        res = bt.run(prices, sp(ov, ex, stop))
        all_rets.append(daily_returns(res.equity_curve))

    t = len(all_rets[0])
    block_size = t // S_BLOCKS
    blocks = [list(range(i * block_size, (i + 1) * block_size if i < S_BLOCKS - 1 else t))
              for i in range(S_BLOCKS)]
    print(f"リターン日数 T={t} / {S_BLOCKS}ブロック(各約{block_size}日)")

    half = S_BLOCKS // 2
    combos = list(itertools.combinations(range(S_BLOCKS), half))
    print(f"CPCV組み合わせ数: C({S_BLOCKS},{half}) = {len(combos)}通り\n")

    logits = []
    for train_block_idx in combos:
        train_idx = set()
        for b in train_block_idx:
            train_idx.update(blocks[b])
        test_idx = set(range(t)) - train_idx

        train_sharpes = [sharpe_of([r[i] for i in train_idx]) for r in all_rets]
        test_sharpes = [sharpe_of([r[i] for i in test_idx]) for r in all_rets]

        winner = max(range(len(ALL_CONFIGS)), key=lambda k: train_sharpes[k])
        # 勝者がOOS側で何位か(順位比率 0〜1、1に近いほど良い)
        rank = sum(1 for s in test_sharpes if s <= test_sharpes[winner]) / len(ALL_CONFIGS)
        rank = min(max(rank, 1e-6), 1 - 1e-6)  # logitのため端を丸める
        logits.append(math.log(rank / (1 - rank)))

    pbo = sum(1 for lg in logits if lg < 0) / len(logits)
    print(f"=== PBO(過剰最適化の確率) = {pbo*100:.1f}% ===")
    print(f"  (logit中央値: {sorted(logits)[len(logits)//2]:+.2f} / "
          f"logit平均: {sum(logits)/len(logits):+.2f})")
    print("\n目安: PBO<10%なら『選定行為自体が信頼できる』、50%なら『コイン投げと同じ』、")
    print("      50%超なら『ISで一番良く見えたものがOOSでは平均以下になりがち』。")


if __name__ == "__main__":
    main()
