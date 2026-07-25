#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX 最短足(日中データ)検証ラボ
=====================================================================
※本体(research_agents.py/trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

「反応速度を上げる」方向性のうち、ニュース監視の高速化ではなく執行タイミング側の
改善を検証する。現行のFX検証はすべて日足(1日1回、終値で判定)だが、もっと
短い足を使えば反応は速くなる。ただしyfinanceの無料データには足の細かさに応じて
取得できる期間の上限がある(実測):

  1分足  … 直近7日分のみ   → 統計的検証には話にならない
  5分足  … 直近60日分のみ  → まだ足りない
  1時間足 … 直近730日分(約2.8年) → 検証に使える最短の足はこれ

このラボでは1時間足(RSI(14時間)=約半日強で判定)を、fx_research_lab.pyと
同じ本番パイプライン(IdeaAgent〜WalkForwardAgent)にかける。約2.8年分しかない
ため、10年日足の検証よりサンプルは少なく、結論の確からしさはその分弱い。

使い方:
  python fx_intraday_lab.py EURJPY          (デフォルト: 1時間足・730日)
  python fx_intraday_lab.py EURJPY 1h 730d
  python fx_intraday_lab.py EURJPY 1m 7d    (1分足・直近7日、参考程度)
"""
from __future__ import annotations
import sys

import research_agents
from research_agents import ResearchConfig, ResearchMasterAgent


def fetch_fx(pair: str, interval: str, period: str) -> list[float]:
    import yfinance as yf
    ticker = f"{pair}=X"
    print(f"取得中: {ticker} / {interval}足・{period} ...")
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    df = df.dropna(subset=["Close"])
    if df.empty:
        print(f"データが取れなかった: {ticker}")
        sys.exit(1)
    closes = [float(x) for x in df["Close"].tolist()]
    print(f"取得完了: {len(closes)}本({interval}足) ({df.index[0]} 〜 {df.index[-1]})")
    return closes


def main() -> None:
    pair = sys.argv[1] if len(sys.argv) > 1 else "EURJPY"
    interval = sys.argv[2] if len(sys.argv) > 2 else "1h"
    period = sys.argv[3] if len(sys.argv) > 3 else "730d"

    prices = fetch_fx(pair, interval, period)
    research_agents.load_prices = lambda symbol, n=6000: prices

    cfg = ResearchConfig(symbol=pair, result_path=f"research_result_{pair.lower()}_{interval}.json")
    result = ResearchMasterAgent(cfg).run()

    print()
    print(f"=== {pair}({interval}足) 判定: {result['verdict']} ===")
    if result["strategy"]:
        sp = result["strategy"]
        print(f"  採用パラメータ: 買い<{sp['rsi_oversold']:.0f} "
              f"利確>{sp['rsi_exit']:.0f} 損切り{sp['stop_loss_pct']*100:.0f}% "
              f"(RSI期間={sp['rsi_period']}本={interval}足)")
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
    print(f"\n注意: {interval}足はyfinance無料データの上限({period})しか遡れないため、")
    print("      10年日足の検証よりサンプル数が少なく、結論の確からしさはその分弱い。")


if __name__ == "__main__":
    main()
