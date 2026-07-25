#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1306 資金規模の比較ラボ(50万円 vs 500万円)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

「資金を500万にしたら1306の検証結果は変わるか」という問いの検証。
RSIシグナル自体は価格だけで決まり資金規模に依存しないため、理屈の上では
利益率(%)は同じになるはずだが、trade_unit(10株単位)の端数処理により
資金が少ないほど「使い切れない端数」の割合が相対的に大きくなり、
わずかに利益率が目減りする。この効果の大きさを実測する。

使い方: python capital_scale_lab.py
"""
from research_agents import ResearchConfig, StrategyParams, Backtester, MetricsAgent

prices = [float(l.strip()) for l in open("prices_1306.csv") if l.strip()]
SP = StrategyParams("optimized", "rsi_only", 0, 0, 14, 75, 40, 50, 0.08, 0.0)

print(f"データ: 1306 {len(prices)}本\n")

for capital in (500_000, 5_000_000):
    cfg = ResearchConfig(capital_yen=capital)
    bt = Backtester(cfg)
    met = MetricsAgent(cfg)
    split = int(len(prices) * cfg.is_ratio)

    m_full = met.metrics(bt.run(prices, SP))
    m_is = met.metrics(bt.run(prices[:split], SP))
    m_oos = met.metrics(bt.run(prices[split:], SP))

    print(f"=== 資金{capital:,}円 ===")
    print(f"  全期間: 利益率{m_full['return_pct']:+7.2f}% / 最大DD{m_full['max_dd_pct']:5.1f}% / "
          f"Sharpe{m_full['sharpe']:5.2f} / 取引{m_full['trades']}回")
    print(f"  IS    : 利益率{m_is['return_pct']:+7.2f}% / 最大DD{m_is['max_dd_pct']:5.1f}% / Sharpe{m_is['sharpe']:5.2f}")
    print(f"  OOS   : 利益率{m_oos['return_pct']:+7.2f}% / 最大DD{m_oos['max_dd_pct']:5.1f}% / Sharpe{m_oos['sharpe']:5.2f}")

    # 端数処理で使い切れずに眠っている現金の割合(最終日時点)を見る
    res = bt.run(prices, SP)
    print(f"  最終資産: {res.equity_curve[-1]:,.0f}円(開始{capital:,}円)")
    print()

print("注意: 利益率%はほぼ一致するはずだが、trade_unit(10株)の端数処理により")
print("      資金が少ないほど使い切れない端数の割合が相対的に大きくなり、")
print("      わずかに利益率が目減りする傾向が出る。")
