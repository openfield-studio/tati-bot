#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOPIX-17業種別ETF Deflated Sharpe Ratio 検証ラボ
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

power_etf_lab.pyで複数のTOPIX-17業種別ETFをスクリーニングしたところ、
9本中6本がGO判定という高い的中率になった(1571含む)。これはfx_dsr_lab.pyで
FXの7ペアをスクリーニングしたときと同じ、多重検定(データスヌーピング)の
懸念がある。同じ手法(Bailey & Lopez de Prado の Deflated Sharpe Ratio)で
検証し直す。

Nの数え方: research_agents.pyの本番パイプラインが実際に評価する組み合わせ
(IdeaAgent4案+OptimizeAgent12通り=16通り)× スクリーニング対象の銘柄数、で
試行プールを構築する(fx_dsr_lab.pyと同じ考え方)。

使い方: python power_dsr_lab.py
"""
from __future__ import annotations
import math
import statistics as pystats

import yfinance as yf

from research_agents import ResearchConfig, StrategyParams, Backtester

NORM = pystats.NormalDist()
EULER_GAMMA = 0.5772156649

# スクリーニング対象(1571=インバース単独検証、1627=電力・ガス、他はTOPIX-17業種別)
CODES = ["1571", "1617", "1621", "1623", "1625", "1626", "1627", "1631", "1633"]

IDEA_SEEDS = [(30, 50, 0.05), (30, 55, 0.05), (35, 50, 0.05), (25, 55, 0.06)]
OPT_GRID = [(ov, ex, stop) for ov in (30, 35, 40) for ex in (50, 55) for stop in (0.05, 0.08)]
ALL_CONFIGS = IDEA_SEEDS + OPT_GRID


def daily_returns(eq: list[float]) -> list[float]:
    return [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]


def skew_kurt(rets: list[float]) -> tuple[float, float]:
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n
    std = var ** 0.5
    if std == 0:
        return 0.0, 3.0
    skew = (sum((r - mean) ** 3 for r in rets) / n) / std ** 3
    kurt = (sum((r - mean) ** 4 for r in rets) / n) / std ** 4
    return skew, kurt


def sharpe_daily(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = var ** 0.5
    return mean / std if std > 0 else 0.0


def expected_max_sharpe(sigma_sr: float, n_trials: float) -> float:
    if n_trials <= 1:
        return 0.0
    z1 = NORM.inv_cdf(1 - 1 / n_trials)
    z2 = NORM.inv_cdf(1 - 1 / (n_trials * math.e))
    return sigma_sr * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(sr_hat: float, t: int, skew: float, kurt: float, sr0: float) -> float:
    denom = math.sqrt(max(1e-9, 1 - skew * sr_hat + ((kurt - 1) / 4) * sr_hat ** 2))
    z = (sr_hat - sr0) * math.sqrt(t - 1) / denom
    return NORM.cdf(z)


def sp(oversold, exit_, stop):
    return StrategyParams("x", "rsi_only", 0, 0, 14, 75, oversold, exit_, stop, 0.0)


def main() -> None:
    print(f"試行プール(N)を構築中: {len(CODES)}銘柄 × 16パラメータ = {len(CODES)*16}通りのOOS日次Sharpeを計算 ...")
    trial_sharpes = []
    prices_cache: dict[str, list[float]] = {}
    for code in CODES:
        df = yf.Ticker(f"{code}.T").history(period="10y")
        prices = [float(x) for x in df["Close"].dropna().tolist()]
        prices_cache[code] = prices
        cfg = ResearchConfig(symbol=code)
        bt = Backtester(cfg)
        split = int(len(prices) * cfg.is_ratio)
        oos_prices = prices[split:]
        for ov, ex, stop in ALL_CONFIGS:
            res = bt.run(oos_prices, sp(ov, ex, stop))
            rets = daily_returns(res.equity_curve)
            trial_sharpes.append(sharpe_daily(rets))

    n_trials = len(trial_sharpes)
    sigma_sr = pystats.pstdev(trial_sharpes)
    print(f"試行数 N={n_trials} / 試行Sharpeの標準偏差 σ_SR={sigma_sr:.3f} "
          f"(平均{pystats.mean(trial_sharpes):+.3f})")
    sr0 = expected_max_sharpe(sigma_sr, n_trials)
    print(f"運だけで出る期待最大Sharpe SR0={sr0:.3f}(日次)")

    print("\n=== GO判定候補のDeflated Sharpe Ratio ===")
    candidates = [
        ("1617", 35, 55, 0.05),
        ("1621", 30, 55, 0.08),
        ("1623", 40, 50, 0.05),
        ("1625", 40, 55, 0.05),
        ("1627", 35, 50, 0.05),
        ("1633", 40, 55, 0.05),
    ]
    for code, ov, ex, stop in candidates:
        prices = prices_cache[code]
        cfg = ResearchConfig(symbol=code)
        bt = Backtester(cfg)
        split = int(len(prices) * cfg.is_ratio)
        oos_prices = prices[split:]
        res = bt.run(oos_prices, sp(ov, ex, stop))
        rets = daily_returns(res.equity_curve)
        sr_hat = sharpe_daily(rets)
        skew, kurt = skew_kurt(rets)
        t = len(rets)
        dsr = deflated_sharpe(sr_hat, t, skew, kurt, sr0)
        annualized = sr_hat * (245 ** 0.5)
        print(f"  {code}(<{ov}/>{ex}/stop{stop*100:.0f}%): OOS Sharpe(年率換算){annualized:.2f} / "
              f"T={t} / DSR={dsr*100:5.1f}%  "
              f"({'skillの可能性が高い' if dsr > 0.95 else 'ノイズと区別できない' if dsr < 0.5 else '判断つかない領域'})")

    print("\n注意: DSR>95%なら『運では説明しにくい』の目安、50%未満なら『試行回数を考えると")
    print("      ノイズと区別できない』の目安(絶対的な合格基準ではなく参考値)。")


if __name__ == "__main__":
    main()
