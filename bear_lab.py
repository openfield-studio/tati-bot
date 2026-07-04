#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bear_lab.py — 下げ相場・インバース・レジームトリガー実験室（記録用）
=====================================================================
※本体(trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

2026-06-22 の検証結果まとめ:
  [インバース常時組込み]  10年で +88.9% → +66.9% に劣化。常設は不採用。
  [インバースガチホ]      10年で -80%（複利逓減）。論外。
  [200日線トリガー(V2/V3)] 長いダラ下げ相場では有効(リーマン級 -28%→+6%)。
                           ただしV字急落に弱く(2024/8: +9%→-8%)、
                           10年トータルでは +89%→+31% と大敗 → 不採用。
  結論: 現物のみのGO戦略(V1)を維持。下げへの備えは「資金を全部入れない」で行う。

使い方:  python bear_lab.py   (prices_1306.csv と research_agents.py が同じフォルダに必要)
"""
from __future__ import annotations
import random
import sys

sys.path.insert(0, ".")
from research_agents import (_rsi, _sma, BacktestResult, MetricsAgent,
                             ResearchConfig)

cfg = ResearchConfig()
met = MetricsAgent(cfg)
FEE = (cfg.commission_bps + cfg.slippage_bps) / 10000.0
DAILY_COST = 0.008 / 245        # インバース信託報酬(年0.8%)


def load_prices() -> list[float]:
    return [float(l.strip()) for l in open("prices_1306.csv") if l.strip()]


def make_inverse(series: list[float]) -> list[float]:
    """合成インバース: 日次リターンが逆(コスト込み)。逓減が自然に再現される。"""
    inv = [100.0]
    for i in range(1, len(series)):
        r = series[i] / series[i - 1] - 1
        inv.append(max(inv[-1] * (1 - r - DAILY_COST), 0.01))
    return inv


def make_path(last: float, target: float, days: int, vol: float, seed: int) -> list[float]:
    """終着点を必ず target に合わせた仮想相場を作る。"""
    rng = random.Random(seed)
    raw, p = [], last
    for _ in range(days):
        p *= 1 + rng.gauss(0, vol)
        raw.append(p)
    corr = target / raw[-1]
    return [round(raw[i] * corr ** ((i + 1) / days), 2) for i in range(days)]


def bot(series: list[float], mode: str, ob: float = 60.0):
    """mode: V1=現物のみ / V2=200日線割れで買い禁止 / V3=V2+インバース起動"""
    inv = make_inverse(series)
    cash, pos, qty, entry = 500_000.0, None, 0.0, 0.0
    eq, trades = [], []
    for i in range(len(series)):
        rsi = _rsi(series, i, 14)
        ma200 = _sma(series, i, 200)
        bear = (ma200 is not None and series[i] < ma200) if mode != "V1" else False
        px_l, px_i = series[i], inv[i]

        if pos == "L":
            if (mode != "V1" and bear) or px_l <= entry * 0.95 or (rsi is not None and rsi >= 50):
                cash += qty * px_l * (1 - FEE)
                trades.append({"side": "SELL", "px": px_l, "qty": qty})
                pos = None
        elif pos == "I":
            if not bear or px_i <= entry * 0.95 or (rsi is not None and rsi <= 45):
                cash += qty * px_i * (1 - FEE)
                trades.append({"side": "SELL", "px": px_i, "qty": qty})
                pos = None

        if pos is None and rsi is not None:
            if not bear and rsi < 35:
                qty = cash / (px_l * (1 + FEE)); cash = 0; entry = px_l; pos = "L"
                trades.append({"side": "BUY", "px": px_l, "qty": qty})
            elif mode == "V3" and bear and rsi > ob:
                qty = cash / (px_i * (1 + FEE)); cash = 0; entry = px_i; pos = "I"
                trades.append({"side": "BUY", "px": px_i, "qty": qty})
        eq.append(cash + (qty * (px_l if pos == "L" else px_i) if pos else 0))
    return met.metrics(BacktestResult(eq, trades, eq[-1]))


def show(name: str, series: list[float]) -> None:
    a, b, c = bot(series, "V1"), bot(series, "V2"), bot(series, "V3")
    print(name)
    for label, m in (("V1 現状(現物のみ)   ", a),
                     ("V2 +下げ中買い禁止  ", b),
                     ("V3 +下げ中インバース", c)):
        print(f"  {label}: {m['return_pct']:+7.1f}% / DD{m['max_dd_pct']:5.1f}% "
              f"/ 取引{m['trades']:3d}回")


def main() -> None:
    prices = load_prices()
    inv10 = make_inverse(prices)
    print("【複利逓減】1306ガチホ %+d%% / インバースガチホ %+d%%" % (
        (prices[-1] / prices[0] - 1) * 100, (inv10[-1] / inv10[0] - 1) * 100))
    print()
    print("【10年全期間】"); show("", prices); print()

    last, warm = prices[-1], prices[-260:]
    print("【仮想シナリオ】")
    show("A: 1年ジワジワ-20%", warm + make_path(last, last * 0.80, 245, 0.010, 7))
    show("D: リーマン級-40%", warm + make_path(last, last * 0.60, 245, 0.016, 11))
    print("【実録】")
    show("2018天井→コロナ底", prices[200:960])
    show("2024年8月ショック", prices[1800:2100])


if __name__ == "__main__":
    main()
