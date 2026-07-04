#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sizing_lab.py — 資金規模とポジションサイジング実験室（記録用）
================================================================
※本体には組み込まない。「資金500万円だとどうなるか」の検証記録。

2026-06-22 の検証結果まとめ (資金500万円):
  [A 全額一括(現状)]   10年+72.7% / 最大DD20.6% = 一時-103万円 / リーマン級なら一時-182万円
  [B 分割エントリー]   RSI<35で1/3, <30で+1/3, <25で残り。
                       10年+49.5%とリターンを23pt削る割にDDはほぼ減らず → 不採用。
  [C 半分だけ運用]     10年+36.4% / DD11.6% = 一時-58万円。痛みがきれいに半減。
                       リターンとリスクのダイヤルとして最有力。

結論:
  - 戦略の%成績は資金規模で変わらない(1306の流動性なら500万は無風)。
  - 変わるのは含み損の絶対額=心理。狼狽売り(ルール放棄)が最大の敵。
  - 増額は段階的に: DRY-RUN → 少額実弾 → 信頼できたら増やす。
  - 各段階で「この含み損額でも眠れるか」を自問する。
  - モンテカルロ結果(pro_lab)と併用: マイナス年の確率27%は設計の想定内。

使い方: python sizing_lab.py  (prices_1306.csv と research_agents.py が必要)
"""
from __future__ import annotations
import random
import sys

sys.path.insert(0, ".")
from research_agents import _rsi, BacktestResult, MetricsAgent, ResearchConfig

cfg = ResearchConfig()
met = MetricsAgent(cfg)
FEE = (cfg.commission_bps + cfg.slippage_bps) / 10000.0
CAP = 5_000_000


def load_prices() -> list[float]:
    return [float(l.strip()) for l in open("prices_1306.csv") if l.strip()]


def make_path(last: float, target: float, days: int, vol: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    raw, p = [], last
    for _ in range(days):
        p *= 1 + rng.gauss(0, vol)
        raw.append(p)
    corr = target / raw[-1]
    return [round(raw[i] * corr ** ((i + 1) / days), 2) for i in range(days)]


def bot(series: list[float], mode: str):
    """A=全額一括 / B=分割エントリー(1/3ずつ) / C=半分だけ運用"""
    cash, shares, entry = float(CAP), 0.0, 0.0
    tranche_lv = 0
    eq, trades = [], []
    budget_cap = CAP * (0.5 if mode == "C" else 1.0)
    for i in range(len(series)):
        rsi = _rsi(series, i, 14)
        px = series[i]
        if shares > 0 and rsi is not None:
            if px <= entry * 0.95 or rsi >= 50:
                cash += shares * px * (1 - FEE)
                trades.append({"side": "SELL", "px": px, "qty": shares})
                shares, entry, tranche_lv = 0.0, 0.0, 0
        if rsi is not None:
            if mode in ("A", "C") and shares == 0 and rsi < 35:
                use = min(cash, budget_cap)
                q = use / (px * (1 + FEE))
                cash -= q * px * (1 + FEE)
                shares, entry = q, px
                trades.append({"side": "BUY", "px": px, "qty": q})
            elif mode == "B":
                lv = 3 if rsi < 25 else 2 if rsi < 30 else 1 if rsi < 35 else 0
                if lv > tranche_lv:
                    use = min(cash, (lv - tranche_lv) * (CAP / 3))
                    if use > 0:
                        q = use / (px * (1 + FEE))
                        cash -= q * px * (1 + FEE)
                        entry = (entry * shares + px * q) / (shares + q) if shares else px
                        shares += q
                        tranche_lv = lv
                        trades.append({"side": "BUY", "px": px, "qty": q})
        eq.append(cash + shares * px)
    return met.metrics(BacktestResult(eq, trades, eq[-1]))


def show(name: str, series: list[float]) -> None:
    print(name)
    for mode, label in (("A", "A 全額一括(現状)"), ("B", "B 分割エントリー"),
                        ("C", "C 半分だけ運用  ")):
        m = bot(series, mode)
        print(f"  {label}: {m['return_pct']:+7.1f}% / 最大DD{m['max_dd_pct']:5.1f}% "
              f"(一時 -{CAP * m['max_dd_pct'] / 100:,.0f}円) / 取引{m['trades']:3d}回")


def main() -> None:
    prices = load_prices()
    print(f"資金{CAP:,}円で運用した場合\n")
    print("【10年全期間】")
    show("", prices)
    print()
    last, warm = prices[-1], prices[-260:]
    print("【リーマン級-40%シナリオ】")
    show("", warm + make_path(last, last * 0.60, 245, 0.016, 11))
    print()
    print("【実録: コロナ暴落】")
    show("", prices[200:960])


if __name__ == "__main__":
    main()
