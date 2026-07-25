#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX 損切り幅 再調整ラボ
=====================================================================
※本体(research_agents.py/trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

fx_research_lab.pyのOptimizeAgentは1306から流用したグリッド(損切り5%/8%の
2値のみ)しか試していない。FXはJPYクロスごとにボラティリティの性質が
1306(TOPIX連動ETF)と違う可能性があるため、損切り幅だけをもっと広いグリッド
(3%〜15%)で振り直し、既に採用済みの買い/利確パラメータ(oversold/exit、
research_result_<pair>.jsonに保存済み)は固定したまま再検証する。

★ノブを増やしすぎない工夫★
 買い/利確を同時に振り直すと「たまたま良く見える組み合わせ」を拾うリスクが
 上がる(pro_labの教訓)。今回は損切り幅という1ノブだけを動かし、
 ①IS/OOS ②ウォークフォワード4区間 の両方で確認する。

使い方:
  python fx_stoploss_lab.py EURJPY
  python fx_stoploss_lab.py GBPJPY
"""
from __future__ import annotations
import json
import sys

import yfinance as yf

from research_agents import ResearchConfig, StrategyParams, Backtester, MetricsAgent

STOP_GRID = [0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15]
WF_SPLITS = (0.50, 0.625, 0.75, 0.875)


def load_adopted(pair: str) -> tuple[float, float, float]:
    with open(f"research_result_{pair.lower()}.json", encoding="utf-8") as f:
        res = json.load(f)
    sp = res["strategy"]
    return sp["rsi_oversold"], sp["rsi_exit"], sp["stop_loss_pct"]


def fetch_prices(pair: str, years: int = 10) -> list[float]:
    df = yf.Ticker(f"{pair}=X").history(period=f"{years}y")
    return [float(x) for x in df["Close"].dropna().tolist()]


def sp_for(oversold: float, exit_: float, stop: float) -> StrategyParams:
    return StrategyParams("x", "rsi_only", 0, 0, 14, 75, oversold, exit_, stop, 0.0)


def main() -> None:
    pair = sys.argv[1] if len(sys.argv) > 1 else "EURJPY"
    oversold, exit_, adopted_stop = load_adopted(pair)
    print(f"=== {pair}: 損切り幅の再調整(買い<{oversold:.0f} 利確>{exit_:.0f} は固定、"
          f"現行採用は損切り{adopted_stop*100:.0f}%) ===")

    prices = fetch_prices(pair)
    n = len(prices)
    cfg = ResearchConfig(symbol=pair)
    bt = Backtester(cfg)
    met = MetricsAgent(cfg)
    split = int(n * cfg.is_ratio)

    print(f"\n① 損切り幅グリッド(全期間/IS/OOS利益率%、Calmar)")
    print(f"{'stop%':>6} {'全期間':>8} {'IS':>8} {'IS_Calmar':>9} {'OOS':>8} {'OOS_Calmar':>10} {'OOS取引':>7}")
    results = []
    for stop in STOP_GRID:
        sp = sp_for(oversold, exit_, stop)
        m_full = met.metrics(bt.run(prices, sp))
        m_is = met.metrics(bt.run(prices[:split], sp))
        m_oos = met.metrics(bt.run(prices[split:], sp))
        results.append((stop, m_full, m_is, m_oos))
        print(f"{stop*100:5.0f}% {m_full['return_pct']:+7.1f}% {m_is['return_pct']:+7.1f}% "
              f"{m_is['calmar']:9.2f} {m_oos['return_pct']:+7.1f}% {m_oos['calmar']:10.2f} {m_oos['trades']:7d}")

    print(f"\n② ウォークフォワード(oversold<{oversold:.0f}/exit>{exit_:.0f}固定、損切りだけ4区間で振り直す)")
    bounds = [int(n * r) for r in WF_SPLITS] + [n]
    print(f"{'stop%':>6}", end="")
    for k in range(4):
        print(f"  区間{k+1:>2}", end="")
    print("  プラス数")
    for stop in STOP_GRID:
        sp = sp_for(oversold, exit_, stop)
        rets = []
        for k in range(4):
            seg = prices[bounds[k]:bounds[k + 1]]
            if len(seg) < 30:
                rets.append(None)
                continue
            m = met.metrics(bt.run(seg, sp))
            rets.append(m["return_pct"])
        positive = sum(1 for r in rets if r is not None and r > 0)
        print(f"{stop*100:5.0f}%", end="")
        for r in rets:
            print(f"  {r:+5.1f}" if r is not None else "   n/a", end="")
        print(f"     {positive}/4")

    best_by_oos = max(results, key=lambda r: r[3]["calmar"])
    best_by_is = max(results, key=lambda r: r[2]["calmar"])
    print(f"\n=== 現行採用: 損切り{adopted_stop*100:.0f}% ===")
    print(f"  [参考・後出し] OOSを見てからの最良: 損切り{best_by_oos[0]*100:.0f}% "
          f"(OOS利益率{best_by_oos[3]['return_pct']:+.1f}%/Calmar{best_by_oos[3]['calmar']:.2f})")
    print(f"  [正しい選び方] ISだけで選んだ最良: 損切り{best_by_is[0]*100:.0f}% "
          f"(IS Calmar{best_by_is[2]['calmar']:.2f} → OOS利益率{best_by_is[3]['return_pct']:+.1f}%/"
          f"Calmar{best_by_is[3]['calmar']:.2f}/取引{best_by_is[3]['trades']}回)")
    if best_by_is[0] == adopted_stop:
        print("  → ISだけで選んでも現行採用値と一致。損切り幅の変更は不要。")
    else:
        print(f"  → ISだけで選ぶと現行({adopted_stop*100:.0f}%)から{best_by_is[0]*100:.0f}%への変更が示唆される。")


if __name__ == "__main__":
    main()
