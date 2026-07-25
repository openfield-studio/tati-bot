#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1306 ATRベース損切り 検証ラボ
=====================================================================
※本体(research_agents.py/trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

プロの手法調査で分かった通り、固定%の損切りではなくATR(Average True Range、
値幅のボラティリティ)に連動した損切り幅を使うのが標準的なプラクティス
(Robert Carverの"Systematic Trading"等)。固定8%損切りをATR基準の損切りに
置き換えたら1306の成績が変わるか検証する。

★モデル化の割り切り★
 - エントリー・利確(RSI)ロジックは現行のまま変えない。損切りだけを置き換える。
 - stop_level = entry_price - atr_mult × ATR(entry時点、14日) で固定
   (現行の固定%損切りと同じく、エントリー時点で決めた水準に固定。
   値幅に応じて毎日追随させる「トレーリング」方式ではない)。
 - ATRはOpen/High/Low/Closeが必要なため、research_agents.pyのBacktester
   (Closeのみ)は使わず専用のバックテスタを実装する。
 - パラメータ選びは stop_loss_lab.py の教訓を踏まえ、IS期間だけで選ぶ
   (OOSを見てから選ぶ後出しジャンケンをしない)。

使い方: python atr_stoploss_lab.py
"""
from __future__ import annotations

import yfinance as yf

from research_agents import ResearchConfig, StrategyParams, MetricsAgent, BacktestResult, _rsi

ATR_PERIOD = 14
ATR_MULT_GRID = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
CFG = ResearchConfig()
SP = StrategyParams("atr", "rsi_only", 0, 0, 14, 75, 40, 50, 0.0, 0.0)  # stop_loss_pctは使わない


def fetch_ohlc(code: str = "1306", years: int = 10):
    """fetch_yf.pyと同じ分割断崖の自動修復をOpen/High/Low/Closeの4系列に適用する。
    (1306は2026-03-30〜31の2日間だけ株価が1/10になって翌日戻る、という生データの
    不具合が実際に発生済み。closesベースで検出した補正係数を4系列すべてに適用。)"""
    df = yf.Ticker(f"{code}.T").history(period=f"{years}y", auto_adjust=True)
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    opens = df["Open"].tolist()
    highs = df["High"].tolist()
    lows = df["Low"].tolist()
    closes = df["Close"].tolist()

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
                opens[k] *= factor
                highs[k] *= factor
                lows[k] *= factor
                closes[k] *= factor
    return opens, highs, lows, closes


def compute_atr(highs, lows, closes, period=ATR_PERIOD):
    """真の値幅(True Range)のperiod日平均。"""
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = [None] * len(tr)
    for i in range(period - 1, len(tr)):
        atr[i] = sum(tr[i - period + 1:i + 1]) / period
    return atr


class ATRStopBacktester:
    """RSI逆張りロジックは同じ、損切りだけをATR基準の固定水準に置き換える。"""

    def __init__(self, cfg: ResearchConfig, atr: list, atr_mult: float):
        self.cfg = cfg
        self.atr = atr
        self.atr_mult = atr_mult

    def run(self, closes: list, sp: StrategyParams) -> BacktestResult:
        c = self.cfg
        cash = float(c.capital_yen)
        shares = 0
        stop_level = 0.0
        equity_curve, trades = [], []
        fee = (c.commission_bps + c.slippage_bps) / 10000.0

        for i, px in enumerate(closes):
            rsi = _rsi(closes, i, sp.rsi_period)
            if shares > 0:
                if px <= stop_level:
                    cash += shares * px * (1 - fee)
                    trades.append({"side": "SELL", "px": px, "qty": shares, "i": i})
                    shares = 0
                elif rsi is not None and rsi >= sp.rsi_exit:
                    cash += shares * px * (1 - fee)
                    trades.append({"side": "SELL", "px": px, "qty": shares, "i": i})
                    shares = 0
            elif rsi is not None and rsi < sp.rsi_oversold and self.atr[i] is not None:
                qty = int(cash // (px * (1 + fee) * c.trade_unit)) * c.trade_unit
                if qty > 0:
                    cash -= qty * px * (1 + fee)
                    shares = qty
                    stop_level = px - self.atr_mult * self.atr[i]
                    trades.append({"side": "BUY", "px": px, "qty": qty, "i": i})

            equity_curve.append(cash + shares * px)

        return BacktestResult(equity_curve, trades, equity_curve[-1])


def main() -> None:
    opens, highs, lows, closes = fetch_ohlc()
    atr = compute_atr(highs, lows, closes)
    n = len(closes)
    split = int(n * CFG.is_ratio)
    met = MetricsAgent(CFG)

    print(f"1306: {n}本(OHLC) / IS {split}本 + OOS {n-split}本\n")
    print("=== ATR損切り幅グリッド(全期間/IS/OOS利益率%、IS Calmar) ===")
    print(f"{'ATR倍率':>8} {'全期間':>8} {'IS':>8} {'IS_Calmar':>9} {'OOS':>8} {'OOS_Calmar':>10} {'OOS取引':>7}")
    results = []
    for mult in ATR_MULT_GRID:
        bt = ATRStopBacktester(CFG, atr, mult)
        m_full = met.metrics(bt.run(closes, SP))
        m_is = met.metrics(bt.run(closes[:split], SP))
        m_oos = met.metrics(bt.run(closes[split:], SP))
        results.append((mult, m_full, m_is, m_oos))
        print(f"{mult:7.1f}x {m_full['return_pct']:+7.1f}% {m_is['return_pct']:+7.1f}% "
              f"{m_is['calmar']:9.2f} {m_oos['return_pct']:+7.1f}% {m_oos['calmar']:10.2f} {m_oos['trades']:7d}")

    # 現行(固定8%損切り)の参考値
    from research_agents import Backtester
    sp_fixed = StrategyParams("fixed", "rsi_only", 0, 0, 14, 75, 40, 50, 0.08, 0.0)
    fixed_bt = Backtester(CFG)
    m_full_fixed = met.metrics(fixed_bt.run(closes, sp_fixed))
    m_is_fixed = met.metrics(fixed_bt.run(closes[:split], sp_fixed))
    m_oos_fixed = met.metrics(fixed_bt.run(closes[split:], sp_fixed))
    print(f"\n[参考] 現行 固定8%損切り: 全期間{m_full_fixed['return_pct']:+.1f}% / "
          f"IS{m_is_fixed['return_pct']:+.1f}%(Calmar{m_is_fixed['calmar']:.2f}) / "
          f"OOS{m_oos_fixed['return_pct']:+.1f}%(Calmar{m_oos_fixed['calmar']:.2f})")

    best_by_is = max(results, key=lambda r: r[2]["calmar"])
    print(f"\n=== ISだけで選んだ最良のATR倍率: {best_by_is[0]}x ===")
    print(f"  IS Calmar{best_by_is[2]['calmar']:.2f} → OOS利益率{best_by_is[3]['return_pct']:+.1f}% / "
          f"Calmar{best_by_is[3]['calmar']:.2f} / 取引{best_by_is[3]['trades']}回 / "
          f"最大DD{best_by_is[3]['max_dd_pct']:.1f}%")
    print(f"  [参考]固定8%損切りのOOS: 最大DD{m_oos_fixed['max_dd_pct']:.1f}%")


if __name__ == "__main__":
    main()
