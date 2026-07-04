#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翌営業日約定ズレ 検証ラボ
=====================================================
現行の research_agents.py のバックテストは「その日の終値で判定・同じ終値で即約定」。
だが実運用は「引け後にRSIで判定 → 翌営業日の始値で約定」になるはず。
このズレが成績にどれだけ影響するかを検証する（本体には組み込まない、記録用）。

前提・割り切り:
 - シグナル判定(RSI)は引け後の終値ベースのまま変えない（そこは事実として正しい）。
 - 約定タイミングだけを「当日終値」→「翌営業日始値」にずらす。
 - 損切り判定も終値基準のまま（日中安値データが無いため、現行ロジックと条件を揃える）。
 - 検証対象は research_result.json が採用している現行GO戦略。
 - 同日中に判定→即予約→翌営業日始値で1件だけ約定（現行と同じ単一ポジション制約）。
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import yfinance as yf

from research_agents import (
    ResearchConfig, StrategyParams, Backtester, BacktestResult, MetricsAgent, _rsi,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("execution_lag_lab")

CFG = ResearchConfig()


def fetch_open_close(symbol: str, years: int = 10) -> tuple[list[float], list[float]]:
    """Open/Closeを同じ日次インデックスで取得し、fetch_yf.pyと同じ分割/併合の
    断崖修復を Open/Close 両方に同じ係数で適用する。"""
    ticker = f"{symbol}.T"
    df = yf.Ticker(ticker).history(period=f"{years}y", auto_adjust=True)
    if df is None or df.empty:
        raise RuntimeError(f"データが取れなかった: {ticker}")
    df = df.dropna(subset=["Open", "Close"])
    opens = [float(x) for x in df["Open"].tolist()]
    closes = [float(x) for x in df["Close"].tolist()]

    for i in range(1, len(closes)):
        r = closes[i] / closes[i - 1]
        factor = None
        if r < 0.7:
            f = round(1 / r)
            if f >= 2:
                factor = 1.0 / f
        elif r > 1.4:
            f = round(r)
            if f >= 2:
                factor = float(f)
        if factor is not None:
            for k in range(i):
                closes[k] *= factor
                opens[k] *= factor
    return opens, closes


def load_strategy_from_research_result(path: str = "research_result.json") -> StrategyParams:
    with open(path, encoding="utf-8") as f:
        res = json.load(f)
    sp = res.get("strategy")
    if not sp:
        raise RuntimeError(f"{path} に採用戦略が無い（verdictがGOでない可能性）。先にresearch_agents.pyを実行。")
    sp = {**sp, "name": "current_go"}
    return StrategyParams(**sp)


class NextOpenBacktester:
    """判定は当日終値ベース(RSI)のまま、約定だけ翌営業日の始値にずらすバックテスタ。
    判定した日には発注を『予約』し、翌営業日の始値で約定させてから次の判定に進む。"""

    def __init__(self, cfg: ResearchConfig):
        self.cfg = cfg

    def run(self, opens: list[float], closes: list[float], sp: StrategyParams) -> BacktestResult:
        c = self.cfg
        cash = float(c.capital_yen)
        shares = 0
        entry = 0.0
        equity_curve, trades = [], []
        fee = (c.commission_bps + c.slippage_bps) / 10000.0
        pending: Optional[str] = None  # 翌朝の始値で約定させる予約 "BUY" / "SELL"

        for i in range(len(closes)):
            # ---- 前営業日の判定で予約された注文を、当日の始値で約定 ----
            if pending == "BUY" and shares == 0:
                px = opens[i]
                qty = int(cash // (px * (1 + fee) * c.trade_unit)) * c.trade_unit
                if qty > 0:
                    cash -= qty * px * (1 + fee)
                    shares, entry = qty, px
                    trades.append({"side": "BUY", "px": px, "qty": qty, "i": i, "fill": "next_open"})
            elif pending == "SELL" and shares > 0:
                px = opens[i]
                cash += shares * px * (1 - fee)
                trades.append({"side": "SELL", "px": px, "qty": shares, "i": i, "fill": "next_open"})
                shares, entry = 0, 0.0
            pending = None

            # ---- 当日終値で判定し、成立すれば翌営業日始値の約定を予約 ----
            close_px = closes[i]
            rsi = _rsi(closes, i, sp.rsi_period)
            if shares > 0:
                if close_px <= entry * (1 - sp.stop_loss_pct):
                    pending = "SELL"
                elif rsi is not None and rsi >= sp.rsi_exit:
                    pending = "SELL"
            elif rsi is not None and rsi < sp.rsi_oversold:
                pending = "BUY"

            equity_curve.append(cash + shares * close_px)

        return BacktestResult(equity_curve, trades, equity_curve[-1])


def report(name: str, m: dict) -> None:
    log.info("  [%-14s] 利益率%+7.1f%% / 最大DD%5.1f%% / Sharpe%5.2f / 取引%3d回 / 勝率%4.0f%%",
              name, m["return_pct"], m["max_dd_pct"], m["sharpe"], m["trades"], m["win_rate"] * 100)


def main() -> None:
    sp = load_strategy_from_research_result()
    log.info("検証対象の現行GO戦略: %s (oversold<%.0f exit>%.0f stop%.0f%%)",
              sp.kind, sp.rsi_oversold, sp.rsi_exit, sp.stop_loss_pct * 100)

    opens, closes = fetch_open_close(CFG.symbol, years=10)
    log.info("取得 %d本 (Open/Close) / 最新終値 %.1f円", len(closes), closes[-1])

    split = int(len(closes) * CFG.is_ratio)
    periods = {
        "全期間": (opens, closes),
        "IS(学習)": (opens[:split], closes[:split]),
        "OOS(検証)": (opens[split:], closes[split:]),
    }

    same_bt = Backtester(CFG)
    lag_bt = NextOpenBacktester(CFG)
    met = MetricsAgent(CFG)

    log.info("=== 同日終値で即約定（現行バックテストの前提） ===")
    same_metrics = {}
    for label, (o, c) in periods.items():
        m = met.metrics(same_bt.run(c, sp))
        same_metrics[label] = m
        report(label, m)

    log.info("=== 翌営業日の始値で約定（実運用に近い前提） ===")
    lag_metrics = {}
    for label, (o, c) in periods.items():
        m = met.metrics(lag_bt.run(o, c, sp))
        lag_metrics[label] = m
        report(label, m)

    log.info("=== 差分（翌日始値 − 同日終値） ===")
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
    log.info("※ 損切り判定は終値基準のまま（日中安値データが無いため）。実際は日中に")
    log.info("  ザラ場でストップに掛かることもあり得るので、これでもなお楽観的な近似。")


if __name__ == "__main__":
    main()
