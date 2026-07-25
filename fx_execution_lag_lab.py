#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX(EUR/JPY) 翌営業日約定ズレ 検証ラボ
=====================================================
fx_research_lab.py で EUR/JPY 単独戦略(買い<35/利確>55/損切り5%)がGOと判定された。
1306本体で行った execution_lag_lab.py と同じ検証を、このEUR/JPY戦略にもかける。
現行の研究チームのバックテストは「当日終値で判定・同じ終値で即約定」の前提だが、
実運用は「引け後にRSIで判定→翌営業日の始値で約定」になるはず。このズレが
成績にどれだけ影響するかを確認する（本体には組み込まない、記録用）。

前提・割り切り:
 - シグナル判定(RSI)は終値ベースのまま変えない。
 - 約定タイミングだけ「当日終値」→「翌営業日始値」にずらす。
 - 損切り判定も終値基準のまま(日中安値データなしのため、現行ロジックと条件を揃える)。
 - FXには株のような分割がないため、execution_lag_lab.pyの断崖修復ロジックは不要。
 - 検証対象は research_result_eurjpy.json が採用している戦略。

使い方:
  python fx_execution_lag_lab.py     (先に fx_research_lab.py EURJPY 10 の実行が必要)
"""

from __future__ import annotations

import json
import logging

import yfinance as yf

from research_agents import ResearchConfig, StrategyParams, BacktestResult, MetricsAgent, _rsi
from execution_lag_lab import NextOpenBacktester
from research_agents import Backtester

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("fx_execution_lag_lab")

CFG = ResearchConfig(symbol="EURJPY")


def fetch_open_close(pair: str, years: int = 10) -> tuple[list[float], list[float]]:
    ticker = f"{pair}=X"
    df = yf.Ticker(ticker).history(period=f"{years}y")
    if df is None or df.empty:
        raise RuntimeError(f"データが取れなかった: {ticker}")
    df = df.dropna(subset=["Open", "Close"])
    opens = [float(x) for x in df["Open"].tolist()]
    closes = [float(x) for x in df["Close"].tolist()]
    return opens, closes


def load_strategy(path: str = "research_result_eurjpy.json") -> StrategyParams:
    with open(path, encoding="utf-8") as f:
        res = json.load(f)
    sp = res.get("strategy")
    if not sp:
        raise RuntimeError(f"{path} に採用戦略が無い(verdictがGOでない可能性)。先にfx_research_lab.pyを実行。")
    sp = {**sp, "name": "eurjpy_go"}
    return StrategyParams(**sp)


def report(name: str, m: dict) -> None:
    log.info("  [%-14s] 利益率%+7.1f%% / 最大DD%5.1f%% / Sharpe%5.2f / 取引%3d回 / 勝率%4.0f%%",
              name, m["return_pct"], m["max_dd_pct"], m["sharpe"], m["trades"], m["win_rate"] * 100)


def main() -> None:
    sp = load_strategy()
    log.info("検証対象: EUR/JPY %s (oversold<%.0f exit>%.0f stop%.0f%%)",
              sp.kind, sp.rsi_oversold, sp.rsi_exit, sp.stop_loss_pct * 100)

    opens, closes = fetch_open_close("EURJPY", years=10)
    log.info("取得 %d本 (Open/Close) / 最新終値 %.2f円", len(closes), closes[-1])

    split = int(len(closes) * CFG.is_ratio)
    periods = {
        "全期間": (opens, closes),
        "IS(学習)": (opens[:split], closes[:split]),
        "OOS(検証)": (opens[split:], closes[split:]),
    }

    same_bt = Backtester(CFG)
    lag_bt = NextOpenBacktester(CFG)
    met = MetricsAgent(CFG)

    log.info("=== 同日終値で即約定(現行バックテストの前提) ===")
    same_metrics = {}
    for label, (o, c) in periods.items():
        m = met.metrics(same_bt.run(c, sp))
        same_metrics[label] = m
        report(label, m)

    log.info("=== 翌営業日の始値で約定(実運用に近い前提) ===")
    lag_metrics = {}
    for label, (o, c) in periods.items():
        m = met.metrics(lag_bt.run(o, c, sp))
        lag_metrics[label] = m
        report(label, m)

    log.info("=== 差分(翌日始値 − 同日終値) ===")
    for label in periods:
        d_ret = lag_metrics[label]["return_pct"] - same_metrics[label]["return_pct"]
        d_dd = lag_metrics[label]["max_dd_pct"] - same_metrics[label]["max_dd_pct"]
        log.info("  [%-14s] 利益率差分%+6.1fpt / 最大DD差分%+5.1fpt", label, d_ret, d_dd)

    oos_same = same_metrics["OOS(検証)"]
    oos_lag = lag_metrics["OOS(検証)"]
    verdict = "GO" if oos_lag["return_pct"] > 0 and oos_lag["sharpe"] > 0 else "要再検討"
    log.info("=== 結論 ===")
    log.info("OOSで翌日約定にしても利益率%+.1f%% / Sharpe%.2f → 約定ズレを織り込んでも %s",
              oos_lag["return_pct"], oos_lag["sharpe"], verdict)
    log.info("※ 損切り判定は終値基準のまま。スワップポイント(金利差コスト/収益)は")
    log.info("  引き続き未考慮(このラボの対象外、別途検討が必要)。")


if __name__ == "__main__":
    main()
