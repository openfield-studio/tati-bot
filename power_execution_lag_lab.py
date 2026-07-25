#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1627(電力・ガスETF) 翌営業日約定ズレ 検証ラボ
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

1306本体で行ったexecution_lag_lab.pyと同じ検証を、power_etf_lab.pyでGO判定
された1627戦略(買い<35/利確>50/損切り5%)にもかける。現行のバックテストは
「当日終値で判定・同じ終値で即約定」の前提だが、実運用は「引け後に判定→
翌営業日の始値で約定」になるはず。このズレが成績にどれだけ影響するかを確認する。

使い方:
  python power_execution_lag_lab.py
"""
from __future__ import annotations

import json

import yfinance as yf

from research_agents import ResearchConfig, StrategyParams, Backtester, MetricsAgent
from execution_lag_lab import NextOpenBacktester

CFG = ResearchConfig(symbol="1627")


def fetch_open_close(code: str, years: int = 10) -> tuple[list[float], list[float]]:
    ticker = f"{code}.T"
    df = yf.Ticker(ticker).history(period=f"{years}y", auto_adjust=True)
    df = df.dropna(subset=["Open", "Close"])
    opens = [float(x) for x in df["Open"].tolist()]
    closes = [float(x) for x in df["Close"].tolist()]

    # 1306のfetch_yf.pyと同じ分割断崖の自動修復(1627はETFで分割は稀だが念のため)
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


def load_strategy(path: str = "research_result_1627.json") -> StrategyParams:
    with open(path, encoding="utf-8") as f:
        res = json.load(f)
    sp = res["strategy"]
    return StrategyParams(**{**sp, "name": "power_go"})


def report(name: str, m: dict) -> None:
    print(f"  [{name:<10}] 利益率{m['return_pct']:+7.1f}% / 最大DD{m['max_dd_pct']:5.1f}% / "
          f"Sharpe{m['sharpe']:5.2f} / 取引{m['trades']:3d}回 / 勝率{m['win_rate']*100:4.0f}%")


def main() -> None:
    sp = load_strategy()
    print(f"検証対象: 1627 {sp.kind} (oversold<{sp.rsi_oversold:.0f} "
          f"exit>{sp.rsi_exit:.0f} stop{sp.stop_loss_pct*100:.0f}%)")

    opens, closes = fetch_open_close("1627", years=10)
    print(f"取得 {len(closes)}本(Open/Close) / 最新終値 {closes[-1]:.0f}円")

    split = int(len(closes) * CFG.is_ratio)
    periods = {
        "全期間": (opens, closes),
        "IS(学習)": (opens[:split], closes[:split]),
        "OOS(検証)": (opens[split:], closes[split:]),
    }

    same_bt = Backtester(CFG)
    lag_bt = NextOpenBacktester(CFG)
    met = MetricsAgent(CFG)

    print("\n=== 同日終値で即約定(現行バックテストの前提) ===")
    same_metrics = {}
    for label, (o, c) in periods.items():
        m = met.metrics(same_bt.run(c, sp))
        same_metrics[label] = m
        report(label, m)

    print("\n=== 翌営業日の始値で約定(実運用に近い前提) ===")
    lag_metrics = {}
    for label, (o, c) in periods.items():
        m = met.metrics(lag_bt.run(o, c, sp))
        lag_metrics[label] = m
        report(label, m)

    print("\n=== 差分(翌日始値 − 同日終値) ===")
    for label in periods:
        d_ret = lag_metrics[label]["return_pct"] - same_metrics[label]["return_pct"]
        d_dd = lag_metrics[label]["max_dd_pct"] - same_metrics[label]["max_dd_pct"]
        print(f"  [{label:<10}] 利益率差分{d_ret:+6.1f}pt / 最大DD差分{d_dd:+5.1f}pt")

    oos_lag = lag_metrics["OOS(検証)"]
    verdict = "GO" if oos_lag["return_pct"] > 0 and oos_lag["sharpe"] > 0 else "要再検討"
    print(f"\n=== 結論 ===")
    print(f"OOSで翌日約定にしても利益率{oos_lag['return_pct']:+.1f}% / "
          f"Sharpe{oos_lag['sharpe']:.2f} → 約定ズレを織り込んでも {verdict}")


if __name__ == "__main__":
    main()
