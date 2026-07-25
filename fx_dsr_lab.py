#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deflated Sharpe Ratio (DSR) 検証ラボ
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

Bailey & Lopez de Prado (2014) "The Deflated Sharpe Ratio"。
ここまでの検証で通貨ペア7つ×パラメータ十数通りと、かなりの数の組み合わせを
試してきた(データスヌーピング/多重検定のリスク)。試行回数が多いほど
「たまたま良く見える」設定が混ざりやすくなるため、観測されたSharpe比を
試行回数で割り引いて評価し直す。

DSR = Φ( (SR_hat - SR0) * sqrt(T-1) / sqrt(1 - γ3*SR_hat + (γ4-1)/4*SR_hat^2) )
  SR_hat: 対象戦略の観測Sharpe比(非年率、日次リターンベース)
  SR0   : N回試行したら「運だけで」出ると期待される最大Sharpe比(次式)
  T     : リターンの観測数(日数)
  γ3,γ4 : リターンの歪度・尖度(非正規性の補正)

E[max SR_N] ≈ σ_SR * [ (1-γ)*Φ^-1(1-1/N) + γ*Φ^-1(1-1/(N・e)) ]
  σ_SR: これまで試した全トライアル(N個)のSharpe比のばらつき
  γ   : オイラー・マスケローニ定数(0.5772...)

★N(試行数)の数え方★
 research_agents.pyの本番パイプラインが実際に評価する組み合わせ数を
 忠実に再現してカウントする: IdeaAgentの4案 + OptimizeAgentの12通り
 (oversold3×exit2×stop2) = 16通り/ペア。これを7ペア分で N=112 とする。
 stoploss_lab等の追加探索を含めるとNはもっと大きくなるため、感度として
 N×4(≈448、ウォークフォワードの内部再最適化を概算で加味)も併記する。

使い方: python fx_dsr_lab.py
"""
from __future__ import annotations
import math
import statistics as pystats

import yfinance as yf

from research_agents import ResearchConfig, StrategyParams, Backtester

NORM = pystats.NormalDist()
EULER_GAMMA = 0.5772156649

PAIRS = ["EURJPY", "USDJPY", "GBPJPY", "AUDJPY", "CHFJPY", "CADJPY", "NZDJPY"]

# research_agents.py IdeaAgent(4案) + OptimizeAgent(oversold3×exit2×stop2=12通り)
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


def main() -> None:
    print("試行プール(N)を構築中: 7通貨ペア × 16パラメータ = 112通りのOOS日次Sharpeを計算 ...")
    trial_sharpes = []
    prices_cache: dict[str, list[float]] = {}
    for pair in PAIRS:
        df = yf.Ticker(f"{pair}=X").history(period="10y")
        prices = [float(x) for x in df["Close"].dropna().tolist()]
        prices_cache[pair] = prices
        cfg = ResearchConfig(symbol=pair)
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

    for n_mult, label in [(1, "N=112(本番パイプライン相当)"), (4, "N=448(WF内部再最適化を概算加味)")]:
        sr0 = expected_max_sharpe(sigma_sr, n_trials * n_mult)
        print(f"  {label}: 運だけで出る期待最大Sharpe SR0={sr0:.3f}")

    print("\n=== 候補戦略のDeflated Sharpe Ratio ===")
    candidates = [
        ("EURJPY", 35, 55, 0.05),
        ("GBPJPY", 30, 55, 0.08),
        ("AUDJPY", 30, 55, 0.08),
        ("NZDJPY", 30, 55, 0.08),
    ]
    for pair, ov, ex, stop in candidates:
        prices = prices_cache[pair]
        cfg = ResearchConfig(symbol=pair)
        bt = Backtester(cfg)
        split = int(len(prices) * cfg.is_ratio)
        oos_prices = prices[split:]
        res = bt.run(oos_prices, sp(ov, ex, stop))
        rets = daily_returns(res.equity_curve)
        sr_hat = sharpe_daily(rets)
        skew, kurt = skew_kurt(rets)
        t = len(rets)

        print(f"\n{pair}(買い<{ov}/利確>{ex}/損切り{stop*100:.0f}%): "
              f"OOS日次Sharpe={sr_hat:.3f} / T={t}本 / 歪度={skew:+.2f} / 尖度={kurt:.2f}")
        for n_mult, label in [(1, "N=112"), (4, "N=448")]:
            sr0 = expected_max_sharpe(sigma_sr, n_trials * n_mult)
            dsr = deflated_sharpe(sr_hat, t, skew, kurt, sr0)
            print(f"  {label}: DSR={dsr*100:5.1f}%  ({'skillの可能性が高い' if dsr > 0.95 else 'ノイズと区別できない' if dsr < 0.5 else '判断つかない領域'})")

    print("\n注意: DSR>95%なら『運では説明しにくい』の目安、50%未満なら『試行回数を考えると")
    print("      ノイズと区別できない』の目安(絶対的な合格基準ではなく参考値)。")


if __name__ == "__main__":
    main()
