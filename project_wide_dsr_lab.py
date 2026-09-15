#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
プロジェクト全体を横断したDeflated Sharpe Ratio(DSR)棚卸しラボ
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

fx_dsr_lab.py(FX 7ペア、N=112)、power_dsr_lab.py(TOPIX-17業種別ETF等9銘柄、N=144)、
dsr_1306_lab.py(1306単体、N=16)は、それぞれ**カテゴリ内だけ**で多重検定を補正してきた。
しかし実際の意思決定の流れは「FXも試した→業種ETFも試した→どちらも多重検定で
ノイズと区別できないと分かった→1306一本化を確定した」というものであり、
1306が生き残ったのはこの一連の探索全体の中でのことである。
つまり本当の試行数(N)は、カテゴリ別のN=16ではなく、
**これまでプロジェクトで実際にバックテストした全組み合わせの合計**とみなすべき、
という指摘(SESSION_LOG項目23-2)を検証する。

対象: FX 7ペア + TOPIX-17業種別ETF等9銘柄 + 1306単体 = 17銘柄 × 16パラメータ = N=272
      (fx_dsr_lab.py/power_dsr_lab.py/dsr_1306_lab.pyの3つのIDEA_SEEDS+OPT_GRIDは同一の
       16パターンなので、単純に3プールを合算できる)

使い方: python project_wide_dsr_lab.py
"""
from __future__ import annotations
import math
import statistics as pystats

import yfinance as yf

from research_agents import ResearchConfig, StrategyParams, Backtester

NORM = pystats.NormalDist()
EULER_GAMMA = 0.5772156649

FX_PAIRS = ["EURJPY", "USDJPY", "GBPJPY", "AUDJPY", "CHFJPY", "CADJPY", "NZDJPY"]
ETF_CODES = ["1571", "1617", "1621", "1623", "1625", "1626", "1627", "1631", "1633"]

IDEA_SEEDS = [(30, 50, 0.05), (30, 55, 0.05), (35, 50, 0.05), (25, 55, 0.06)]
OPT_GRID = [(ov, ex, stop) for ov in (30, 35, 40) for ex in (50, 55) for stop in (0.05, 0.08)]
ALL_CONFIGS = IDEA_SEEDS + OPT_GRID  # 16通り


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


def oos_prices_of(prices: list[float]) -> list[float]:
    cfg = ResearchConfig()
    split = int(len(prices) * cfg.is_ratio)
    return prices[split:]


def trial_sharpes_for(prices: list[float]) -> list[float]:
    cfg = ResearchConfig()
    bt = Backtester(cfg)
    oos = oos_prices_of(prices)
    out = []
    for ov, ex, stop in ALL_CONFIGS:
        res = bt.run(oos, sp(ov, ex, stop))
        rets = daily_returns(res.equity_curve)
        out.append(sharpe_daily(rets))
    return out


def verdict_label(dsr: float) -> str:
    if dsr > 0.95:
        return "skillの可能性が高い"
    if dsr < 0.5:
        return "ノイズと区別できない"
    return "判断つかない領域"


def main() -> None:
    print("=== プロジェクト全体の試行プールを構築中 ===")
    trial_sharpes: list[float] = []
    prices_cache: dict[str, list[float]] = {}

    print(f"[1/3] FX {len(FX_PAIRS)}ペア × 16パラメータ ...")
    for pair in FX_PAIRS:
        df = yf.Ticker(f"{pair}=X").history(period="10y")
        prices = [float(x) for x in df["Close"].dropna().tolist()]
        prices_cache[f"fx_{pair}"] = prices
        trial_sharpes += trial_sharpes_for(prices)

    print(f"[2/3] 業種別ETF等 {len(ETF_CODES)}銘柄 × 16パラメータ ...")
    for code in ETF_CODES:
        df = yf.Ticker(f"{code}.T").history(period="10y")
        prices = [float(x) for x in df["Close"].dropna().tolist()]
        prices_cache[f"etf_{code}"] = prices
        trial_sharpes += trial_sharpes_for(prices)

    print("[3/3] 1306単体 × 16パラメータ ...")
    prices_1306 = [float(l.strip()) for l in open("prices_1306.csv") if l.strip()]
    prices_cache["1306"] = prices_1306
    trial_sharpes += trial_sharpes_for(prices_1306)

    n_trials = len(trial_sharpes)
    sigma_sr = pystats.pstdev(trial_sharpes)
    print(f"\n合計試行数 N={n_trials}(FX{len(FX_PAIRS)*16} + ETF{len(ETF_CODES)*16} + 1306単体16)")
    print(f"試行Sharpeの標準偏差 σ_SR={sigma_sr:.3f}(平均{pystats.mean(trial_sharpes):+.3f})")

    print("\n=== 通しのDeflated Sharpe Ratio(N=272ベース) ===")
    for n_mult, label in [(1, f"N={n_trials}(プロジェクト全体の実試行数)"),
                          (4, f"N={n_trials*4}(WF内部再最適化を概算加味)")]:
        sr0 = expected_max_sharpe(sigma_sr, n_trials * n_mult)
        print(f"  {label}: 運だけで出る期待最大Sharpe(日次) SR0={sr0:.3f}"
              f"(年率換算 {sr0*245**0.5:.2f})")

    print("\n--- 各カテゴリの代表候補を、この通しの基準で評価し直す ---")
    candidates = [
        ("1306(採用戦略・現行)", prices_1306, 40, 50, 0.08),
        ("EURJPY(FX代表)", prices_cache["fx_EURJPY"], 35, 55, 0.05),
        ("GBPJPY(FX最有力)", prices_cache["fx_GBPJPY"], 30, 55, 0.08),
        ("1627(業種ETF最有力)", prices_cache["etf_1627"], 35, 50, 0.05),
    ]
    cfg = ResearchConfig()
    bt = Backtester(cfg)
    for name, prices, ov, ex, stop in candidates:
        oos = oos_prices_of(prices)
        res = bt.run(oos, sp(ov, ex, stop))
        rets = daily_returns(res.equity_curve)
        sr_hat = sharpe_daily(rets)
        skew, kurt = skew_kurt(rets)
        t = len(rets)
        annualized = sr_hat * (245 ** 0.5)
        print(f"\n{name}(<{ov}/>{ex}/stop{stop*100:.0f}%): OOS Sharpe(年率換算){annualized:.2f} / T={t}")
        for n_mult, label in [(1, f"N={n_trials}"), (4, f"N={n_trials*4}")]:
            sr0 = expected_max_sharpe(sigma_sr, n_trials * n_mult)
            dsr = deflated_sharpe(sr_hat, t, skew, kurt, sr0)
            print(f"  {label}: DSR={dsr*100:5.1f}%  ({verdict_label(dsr)})")

    print("\n注意: DSR>95%なら『運では説明しにくい』の目安、50%未満なら『試行回数を考えると")
    print("      ノイズと区別できない』の目安(絶対的な合格基準ではなく参考値)。")
    print("参考: カテゴリ別DSR(fx_dsr_lab.py N=112, power_dsr_lab.py N=144, dsr_1306_lab.py N=16)")
    print("      との比較で、通しのN=272にした分だけ基準がどれだけ厳しくなるかを確認すること。")


if __name__ == "__main__":
    main()
