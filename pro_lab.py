#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pro_lab.py — プロの検証4点セット（記録用・本体には組み込まない）
==================================================================
2026-06-22 実行結果の要約:
  ①感度マップ  : <35/50は「高原」の上。隣接パラメータも全部プラス=まぐれの一点ではない。
                 ※<40がもっと良く見えるが、全期間を見た後の乗り換えは後出しジャンケン。
                   採用するなら IS/OOS+ウォークフォワードを最初からやり直すこと。
  ②モンテカルロ: ありえた1年の中央値+6.7% / 最悪5%で-11%。マイナス年の確率27%。
                 → 1年やって負けても設計の想定内。パニックでやめないための基準値。
  ③運テスト    : デタラメな日に買う1000回の99%に勝つ。RSIシグナルに情報がある証拠。
  ④コスト感度  : 手数料5倍でも+41%で生存。コスト構造に対して頑健。

使い方: python pro_lab.py  (prices_1306.csv と research_agents.py が必要)
"""
import sys, random, statistics
sys.path.insert(0, '.')
from research_agents import Backtester, MetricsAgent, StrategyParams, ResearchConfig

cfg = ResearchConfig(); bt = Backtester(cfg); met = MetricsAgent(cfg)
prices = [float(l.strip()) for l in open('prices_1306.csv') if l.strip()]
FEE = (cfg.commission_bps + cfg.slippage_bps) / 10000.0

def sp(oversold, exit_, stop=0.05):
    return StrategyParams("x", "rsi_only", 0, 0, 14, 75, oversold, exit_, stop, 0.0)

print("① パラメータ感度マップ（10年利益率%）")
exits = [45, 50, 55, 60]
print("        exit:" + "".join(f"{e:>7}" for e in exits))
for ov in (25, 28, 30, 32, 35, 38, 40):
    row = [met.metrics(bt.run(prices, sp(ov, e)))['return_pct'] for e in exits]
    print(f"  買い<{ov:2d}    " + "".join(f"{r:+7.0f}" for r in row))

res = bt.run(prices, sp(35, 50))
trade_rets, durations, buy = [], [], None
for t in res.trades:
    if t["side"] == "BUY": buy = t
    elif buy:
        trade_rets.append(t["px"]*(1-FEE)/(buy["px"]*(1+FEE)) - 1)
        durations.append(max(1, t["i"] - buy["i"])); buy = None
per_year = len(trade_rets) / 10
print(f"\n(採用<35/50: 全{len(trade_rets)}取引 / {per_year:.1f}回/年 / 平均保有{statistics.mean(durations):.0f}日)")

rng = random.Random(0); outcomes = []
for _ in range(10000):
    k = max(1, round(rng.gauss(per_year, per_year**0.5))); eq = 1.0
    for _ in range(k): eq *= 1 + rng.choice(trade_rets)
    outcomes.append((eq-1)*100)
outcomes.sort(); P = lambda p: outcomes[int(len(outcomes)*p/100)]
print(f"\n② モンテカルロ1万回『ありえた1年』")
print(f"   最悪5% {P(5):+.1f}% / 中央値 {P(50):+.1f}% / 上位5% {P(95):+.1f}%")
print(f"   マイナス年の確率 {sum(1 for o in outcomes if o<0)/100:.0f}% / -10%超 {sum(1 for o in outcomes if o<-10)/100:.0f}%")

actual = met.metrics(res)['return_pct']
rng = random.Random(1); rand_results = []
for _ in range(1000):
    eq = 1.0
    for _ in range(len(trade_rets)):
        i = rng.randrange(14, len(prices)-70)
        j = min(i + rng.choice(durations), len(prices)-1)
        eq *= (prices[j]*(1-FEE)) / (prices[i]*(1+FEE))
    rand_results.append((eq-1)*100)
rand_results.sort()
beat = sum(1 for r in rand_results if actual > r)/10
print(f"\n③ 運テスト: デタラメ買い中央値 {rand_results[500]:+.0f}% vs GO戦略 {actual:+.0f}% → {beat:.0f}%に勝利")

print(f"\n④ コスト感度")
for mult in (1, 2, 3, 5):
    c2 = ResearchConfig(commission_bps=cfg.commission_bps*mult, slippage_bps=cfg.slippage_bps*mult)
    m = met.metrics(Backtester(c2).run(prices, sp(35, 50)))
    print(f"   コスト{mult}倍: {m['return_pct']:+7.1f}% / DD{m['max_dd_pct']:.1f}%")
