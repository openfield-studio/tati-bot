#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1306単体のDeflated Sharpe Ratio検証ラボ
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

fx_dsr_lab.py/power_dsr_lab.pyでは複数銘柄をスクリーニングしたこと自体の
多重検定を補正したが、1306は元々単一銘柄として検証しており他銘柄との
比較選定はしていない。ただし1306自身もIdeaAgent4案+OptimizeAgent12通り=
16パターンから最良を選んでいるため、この内部的な試行(N=16)だけを考慮した
DSRを計算し、1306の「GO」がこの検証でも揺らがないかを確認する。

使い方: python dsr_1306_lab.py
"""
from __future__ import annotations
import math
import statistics as pystats

from research_agents import ResearchConfig, StrategyParams, Backtester

NORM = pystats.NormalDist()
EULER_GAMMA = 0.5772156649

IDEA_SEEDS = [(30, 50, 0.05), (30, 55, 0.05), (35, 50, 0.05), (25, 55, 0.06)]
OPT_GRID = [(ov, ex, stop) for ov in (30, 35, 40) for ex in (50, 55) for stop in (0.05, 0.08)]
ALL_CONFIGS = IDEA_SEEDS + OPT_GRID  # 16通り


def daily_returns(eq):
    return [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]


def skew_kurt(rets):
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n
    std = var ** 0.5
    if std == 0:
        return 0.0, 3.0
    skew = (sum((r - mean) ** 3 for r in rets) / n) / std ** 3
    kurt = (sum((r - mean) ** 4 for r in rets) / n) / std ** 4
    return skew, kurt


def sharpe_daily(rets):
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = var ** 0.5
    return mean / std if std > 0 else 0.0


def expected_max_sharpe(sigma_sr, n_trials):
    if n_trials <= 1:
        return 0.0
    z1 = NORM.inv_cdf(1 - 1 / n_trials)
    z2 = NORM.inv_cdf(1 - 1 / (n_trials * math.e))
    return sigma_sr * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(sr_hat, t, skew, kurt, sr0):
    denom = math.sqrt(max(1e-9, 1 - skew * sr_hat + ((kurt - 1) / 4) * sr_hat ** 2))
    z = (sr_hat - sr0) * math.sqrt(t - 1) / denom
    return NORM.cdf(z)


def sp(oversold, exit_, stop):
    return StrategyParams("x", "rsi_only", 0, 0, 14, 75, oversold, exit_, stop, 0.0)


def main() -> None:
    prices = [float(l.strip()) for l in open("prices_1306.csv") if l.strip()]
    cfg = ResearchConfig()
    bt = Backtester(cfg)
    split = int(len(prices) * cfg.is_ratio)
    oos_prices = prices[split:]

    print(f"1306: {len(prices)}本 / OOS {len(oos_prices)}本")
    print(f"試行プール(N=16, 1306単体のIdeaAgent+OptimizeAgentの組み合わせのみ)を計算中 ...")

    trial_sharpes = []
    for ov, ex, stop in ALL_CONFIGS:
        res = bt.run(oos_prices, sp(ov, ex, stop))
        rets = daily_returns(res.equity_curve)
        trial_sharpes.append(sharpe_daily(rets))

    n_trials = len(trial_sharpes)
    sigma_sr = pystats.pstdev(trial_sharpes)
    sr0 = expected_max_sharpe(sigma_sr, n_trials)
    print(f"N={n_trials} / σ_SR={sigma_sr:.3f} / 運だけで出る期待最大Sharpe(日次)={sr0:.3f} "
          f"(年率換算 {sr0*245**0.5:.2f})")

    # 採用戦略: 買い<40 利確>50 損切り8%
    res = bt.run(oos_prices, sp(40, 50, 0.08))
    rets = daily_returns(res.equity_curve)
    sr_hat = sharpe_daily(rets)
    skew, kurt = skew_kurt(rets)
    t = len(rets)
    dsr = deflated_sharpe(sr_hat, t, skew, kurt, sr0)
    annualized = sr_hat * 245 ** 0.5

    print(f"\n採用戦略(買い<40/利確>50/損切り8%): OOS Sharpe(年率換算){annualized:.2f} / T={t} / "
          f"歪度{skew:+.2f} / 尖度{kurt:.2f}")
    print(f"DSR(N=16, 1306単体) = {dsr*100:.1f}%  "
          f"({'skillの可能性が高い' if dsr > 0.95 else 'ノイズと区別できない' if dsr < 0.5 else '判断つかない領域'})")

    print("\n参考: 他銘柄と比較選定した場合のN(FX N=112, 業種ETF N=144)での目安も併記")
    for n_mult, label in [(112 / 16, "N=112相当(FXと同じ数の比較選定をした場合)"),
                          (144 / 16, "N=144相当(業種ETFスクリーニングと同じ場合)")]:
        sr0_alt = expected_max_sharpe(sigma_sr, n_trials * n_mult)
        dsr_alt = deflated_sharpe(sr_hat, t, skew, kurt, sr0_alt)
        print(f"  {label}: DSR={dsr_alt*100:.1f}%")


if __name__ == "__main__":
    main()
