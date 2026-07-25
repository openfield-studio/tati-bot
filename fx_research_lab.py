#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX(USD/JPY) 独立戦略 本番検証ラボ
=====================================================================
※本体(research_agents.py/trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

fx_lab.py で「1306で採用した設定(<35/50/5%>, <40/50/8%>)をそのまま為替に
持ち込むとNO-GO、ただし買いRSI閾値を25〜30まで下げると簡易マップ上はプラスに
転じる」と分かった。inverse_1571_lab.py と同じやり方で、research_agents.py の
IdeaAgent〜WalkForwardAgentのフルパイプライン(過剰最適化対策込み)をFXの実データ
にかけ、為替専用にゼロから最適化した場合にGOになる戦略が見つかるか検証する。

前提:
 - research_agents.load_prices() はJ-Quants(株専用)/合成データ用でFXには使えない
   ため、fx_lab.py と同じ yfinance 取得(通貨ペア=X)に差し替える(モンキーパッチ)。
 - 結果は research_result.json(本番の1306戦略)を上書きしないよう、
   research_result_<pair>.json に分けて出力する。

使い方:
  pip install yfinance          (未インストールなら)
  python fx_research_lab.py               USD/JPYの10年データで検証
  python fx_research_lab.py EURJPY 10      他通貨ペアや年数も指定可能
"""
from __future__ import annotations
import sys

import research_agents
from research_agents import ResearchConfig, ResearchMasterAgent


def fetch_fx(pair: str, years: int) -> list[float]:
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance が未インストール。先に:  pip install yfinance")
        sys.exit(1)

    ticker = f"{pair}=X"
    print(f"取得中: {ticker} / 直近{years}年 ...")
    df = yf.Ticker(ticker).history(period=f"{years}y")
    if df is None or df.empty:
        print(f"データが取れなかった: {ticker}。通貨ペア表記を確認(例: USDJPY, EURJPY)。")
        sys.exit(1)

    closes = [float(x) for x in df["Close"].dropna().tolist()]
    print(f"取得完了: {len(closes)}本 (最古 {closes[0]:.2f} → 最新 {closes[-1]:.2f})")
    return closes


def main() -> None:
    pair = sys.argv[1] if len(sys.argv) > 1 else "USDJPY"
    years = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    prices = fetch_fx(pair, years)

    # load_prices(symbol, n=6000) を、取得済みのFX実データを返すだけの関数に差し替える。
    research_agents.load_prices = lambda symbol, n=6000: prices

    cfg = ResearchConfig(symbol=pair, result_path=f"research_result_{pair.lower()}.json")
    result = ResearchMasterAgent(cfg).run()

    print()
    print(f"=== {pair} 独立戦略 判定: {result['verdict']} ===")
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
