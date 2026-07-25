#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
電力関連ETF(1627: NEXT FUNDS 電力・ガス(TOPIX-17))単独戦略 検証ラボ
=====================================================================
※本体(research_agents.py/trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

「これから電力需要の増加を見込んで電力関連ETFで検証できないか」という発案を受け、
1571(インバースETF単独検証)と同じやり方で、1306の純RSI逆張りロジックを
1627(電力・ガスセクターETF、関西電力・東京瓦斯・大阪瓦斯等を含む)に
そのまま適用したらどうなるかを、research_agents.pyの検証パイプライン
(IdeaAgent〜WalkForwardAgent)にそのままかけて検証する。

前提:
 - データはyfinance(1627.T)から取得。J-Quants経由ではなくyfinanceに
   統一するため research_agents.load_prices をこのETFの実データで差し替える
   (FXラボと同じ手法)。
 - 1306より出来高が少ない(流動性が低い)点に注意。バックテスト自体は
   終値ベースなので実行できるが、実運用では約定のしやすさが1306と異なる。
 - 結果は research_result.json(本番の1306戦略)を上書きしないよう、
   research_result_1627.json に分けて出力する。

使い方:
  python power_etf_lab.py
"""
from __future__ import annotations
import sys

import research_agents
from research_agents import ResearchConfig, ResearchMasterAgent


def fetch_prices(code: str, years: int = 10) -> list[float]:
    import yfinance as yf
    df = yf.Ticker(f"{code}.T").history(period=f"{years}y")
    closes = [float(x) for x in df["Close"].dropna().tolist()]
    print(f"取得完了: {code}.T {len(closes)}本 (最古 {closes[0]:.0f}円 → 最新 {closes[-1]:.0f}円)")
    return closes


def main() -> None:
    code = sys.argv[1] if len(sys.argv) > 1 else "1627"
    prices = fetch_prices(code)
    research_agents.load_prices = lambda symbol, n=6000: prices

    cfg = ResearchConfig(symbol=code, result_path=f"research_result_{code}.json")
    result = ResearchMasterAgent(cfg).run()

    print()
    print(f"=== {code} 単独戦略 判定: {result['verdict']} ===")
    if result["strategy"]:
        sp = result["strategy"]
        print(f"  採用パラメータ: 買い<{sp['rsi_oversold']:.0f} "
              f"利確>{sp['rsi_exit']:.0f} 損切り{sp['stop_loss_pct']*100:.0f}%")
        oos = result["out_of_sample"]
        print(f"  OOS成績: 利益率{oos['return_pct']:+.1f}% / 最大DD{oos['max_dd_pct']:.1f}% / "
              f"Sharpe{oos['sharpe']:.2f} / 取引{oos['trades']}回")
    for w in result["warnings"]:
        print(f"  [警告] {w}")
    wf = result.get("walk_forward")
    if wf:
        print(f"ウォークフォワード: {wf['positive']}/{wf['total']} 区間プラス "
              f"→ {'合格' if wf['passed'] else '不合格'}")
    print(f"詳細: {cfg.result_path}")


if __name__ == "__main__":
    main()
