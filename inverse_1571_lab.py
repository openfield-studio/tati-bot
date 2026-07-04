#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1571(日経平均インバース・インデックス連動型ETF) 単独戦略 検証ラボ
=====================================================================
※本体(research_agents.py/trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

bear_lab.py では 1306 の値動きから合成した疑似インバース系列で
「下げ相場のヘッジとして常時組み込む」案を検証し、不採用と判明済み(項目3参照)。
ここでは実際の 1571 価格データを使い、1306と同じ純RSI逆張りロジックを
1571単体の独立した戦略として検証パイプライン(research_agents.py)にそのままかける。

前提:
 - 実データは prices_1571.csv (fetch_yf.py 1571 10 で取得済み)を使う。
 - research_result.json(本番の1306戦略)を上書きしないよう、
   結果は research_result_1571.json に分けて出力する。

使い方:
  python fetch_yf.py 1571 10     … 実データ取得(初回・更新時)
  python inverse_1571_lab.py     … 検証実行
"""

from __future__ import annotations

from research_agents import ResearchConfig, ResearchMasterAgent


def main() -> None:
    cfg = ResearchConfig(symbol="1571", result_path="research_result_1571.json")
    result = ResearchMasterAgent(cfg).run()

    print()
    print(f"=== 1571単独戦略 判定: {result['verdict']} ===")
    for w in result["warnings"]:
        print(f"  ⚠ {w}")
    wf = result.get("walk_forward")
    if wf:
        print(f"ウォークフォワード: {wf['positive']}/{wf['total']} 区間プラス "
              f"→ {'合格' if wf['passed'] else '不合格'}")
    print(f"詳細: {cfg.result_path}")


if __name__ == "__main__":
    main()
