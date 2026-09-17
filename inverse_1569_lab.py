#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1569(TOPIXベア上場投信、-1倍) 単独戦略 検証ラボ
=====================================================================
※本体(research_agents.py/trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

1306はTOPIX連動(+1倍)なので、その逆側にあたるTOPIXベア(-1倍、1569)を
1306と同じ純RSI逆張りロジックで単独戦略として検証する。inverse_1571_lab.py
(日経平均インバース、NO-GO)とは対象指数が異なる(TOPIX vs 日経平均)ため、
別の1試行として扱う。

前提:
 - 実データは prices_1569.csv (fetch_yf.py 1569 10 で取得済み)を使う。
 - research_result.json(本番の1306戦略)を上書きしないよう、
   結果は research_result_1569.json に分けて出力する。

使い方:
  python fetch_yf.py 1569 10     … 実データ取得(初回・更新時)
  python inverse_1569_lab.py     … 検証実行
"""

from __future__ import annotations

from research_agents import ResearchConfig, ResearchMasterAgent


def main() -> None:
    cfg = ResearchConfig(symbol="1569", result_path="research_result_1569.json")
    result = ResearchMasterAgent(cfg).run()

    print()
    print(f"=== 1569単独戦略 判定: {result['verdict']} ===")
    for w in result["warnings"]:
        print(f"  ⚠ {w}")
    wf = result.get("walk_forward")
    if wf:
        print(f"ウォークフォワード: {wf['positive']}/{wf['total']} 区間プラス "
              f"→ {'合格' if wf['passed'] else '不合格'}")
    print(f"詳細: {cfg.result_path}")


if __name__ == "__main__":
    main()
