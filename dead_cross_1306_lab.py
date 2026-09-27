#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1306(RSI逆張り、本番戦略)にデッドクロス・レジームフィルター(120日/350日MA)を
追加適用した場合の効果検証。

背景: regime_shift_agent.py(1321/1571)で確定したデッドクロス方式を1306の
本番RSI逆張り戦略にも流用できるか、というユーザーの質問(2026-09-25)を受けて検証。

方法:
- 1306.T の実データ全期間(yfinanceの分割断崖自動修復つき、regime_shift_agent.py
  のfetch_closesを再利用)を使う。research_agents.py/trading_agents.pyは
  絶対に変更しない(ルール)。ロジックはBacktesterをコピーして拡張。
- ベース戦略: 本番と同じ rsi_only(売られすぎ<40、利確>=50、損切り8%)。
- フィルター版: ノーポジ時の新規買いを「レジーム=bull(短期MA>=長期MA)の時だけ」
  に制限。保有中の手仕舞いロジックは変えない(既存の考え方を維持)。
- IS/OOS分割(前65%/後35%、research_agents.pyのis_ratioと合わせる)。
- 隣接パラメータでの頑健性チェック(120/350から動かしても結果が滑らかか)。
- 年度別・独立エピソード単位でフィルターが「勝ちを削った/負けを防いだ」件数を集計
  (ルール9: プールしたトレード数だけで判定しない)。
"""
from __future__ import annotations

import dataclasses
import math
import sys

sys.path.insert(0, ".")
import regime_shift_agent as rsa  # fetch_closes(分割断崖自動修復)を再利用
from research_agents import ResearchConfig, StrategyParams, _rsi  # noqa: E402


CFG = ResearchConfig()


def _sma_series(px: list[float], n: int) -> list[float | None]:
    out = [None] * len(px)
    s = 0.0
    for i, v in enumerate(px):
        s += v
        if i >= n:
            s -= px[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


@dataclasses.dataclass
class Trade:
    buy_i: int
    buy_px: float
    sell_i: int
    sell_px: float
    why: str


def run_backtest(prices: list[float], sp: StrategyParams,
                  regime: list[bool] | None) -> tuple[list[float], list[Trade]]:
    """regime[i] = True なら bull(通常買ってよい)。Noneならフィルター無し(既存ロジック)。"""
    c = CFG
    cash = float(c.capital_yen)
    shares = 0
    entry = 0.0
    buy_i = -1
    equity_curve: list[float] = []
    trades: list[Trade] = []
    fee = (c.commission_bps + c.slippage_bps) / 10000.0

    for i, px in enumerate(prices):
        rsi = _rsi(prices, i, sp.rsi_period)

        if shares > 0:
            exit_now, why = False, ""
            if sp.stop_loss_pct > 0 and px <= entry * (1 - sp.stop_loss_pct):
                exit_now, why = True, "stop"
            elif rsi is not None and rsi >= sp.rsi_exit:
                exit_now, why = True, "rsi_recover"
            if exit_now:
                cash += shares * px * (1 - fee)
                trades.append(Trade(buy_i, entry, i, px, why))
                shares, entry, buy_i = 0, 0.0, -1
        elif rsi is not None:
            buy_now = rsi < sp.rsi_oversold
            if buy_now and regime is not None and not regime[i]:
                buy_now = False  # bear regimeなら新規買いを見送る
            if buy_now:
                budget = cash
                qty = int(budget // (px * (1 + fee) * c.trade_unit)) * c.trade_unit
                if qty > 0:
                    cash -= qty * px * (1 + fee)
                    shares, entry, buy_i = qty, px, i
        equity_curve.append(cash + shares * px)

    return equity_curve, trades


def metrics(eq: list[float], trades: list[Trade]) -> dict:
    start, end = eq[0], eq[-1]
    ret = (end / start - 1) * 100
    peak, max_dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    wins = sum(1 for t in trades if t.sell_px >= t.buy_px)
    n = len(trades)
    return {"return_pct": ret, "max_dd_pct": max_dd * 100, "trades": n,
            "win_rate": (wins / n * 100) if n else 0.0}


def main() -> None:
    closes = rsa.fetch_closes("1306.T", min_days=100)
    dates = [d for d, _ in closes]
    prices = [p for _, p in closes]
    print(f"データ: {dates[0]}~{dates[-1]} ({len(prices)}本)")

    sp = StrategyParams("rsi_only_prod", "rsi_only", 0, 0, 14, 75, 40, 50, 0.08, 0.0)

    # --- 通し全期間: フィルター無し vs 有り(120/350) ---
    ma_fast = _sma_series(prices, 120)
    ma_slow = _sma_series(prices, 350)
    regime = [(f is not None and s is not None and f >= s) for f, s in zip(ma_fast, ma_slow)]
    # データ不足(初期350日)は安全側=bullとして買い制限しない(regime_shift_agent.pyと同じ思想)
    regime = [True if (ma_slow[i] is None) else regime[i] for i in range(len(prices))]

    eq_base, tr_base = run_backtest(prices, sp, None)
    eq_filt, tr_filt = run_backtest(prices, sp, regime)
    m_base, m_filt = metrics(eq_base, tr_base), metrics(eq_filt, tr_filt)

    print("\n=== 全期間(フルヒストリー) ===")
    print(f"フィルター無し(本番): {m_base}")
    print(f"フィルター有り(120/350): {m_filt}")

    # --- IS/OOS分割 ---
    split = int(len(prices) * CFG.is_ratio)
    for label, sl in (("IS", slice(0, split)), ("OOS", slice(split, None))):
        p_sub = prices[sl]
        r_sub = regime[sl]
        eb, tb = run_backtest(p_sub, sp, None)
        ef, tf = run_backtest(p_sub, sp, r_sub)
        print(f"\n=== {label} ({dates[sl][0]}~{dates[sl][-1]}, {len(p_sub)}本) ===")
        print(f"フィルター無し: {metrics(eb, tb)}")
        print(f"フィルター有り: {metrics(ef, tf)}")

    # --- 隣接パラメータでの頑健性チェック ---
    print("\n=== 隣接パラメータ頑健性(全期間) ===")
    for fast_n in (90, 120, 150):
        for slow_n in (280, 350, 400):
            if fast_n >= slow_n:
                continue
            mf = _sma_series(prices, fast_n)
            ms = _sma_series(prices, slow_n)
            reg = [(f is not None and s is not None and f >= s) or s is None
                   for f, s in zip(mf, ms)]
            eq, tr = run_backtest(prices, sp, reg)
            m = metrics(eq, tr)
            print(f"  fast={fast_n:3d} slow={slow_n:3d}: 利益率{m['return_pct']:+7.1f}% "
                  f"DD{m['max_dd_pct']:5.1f}% 取引{m['trades']:3d} 勝率{m['win_rate']:4.0f}%")

    # --- bear regimeで実際にスキップされた取引の分析(独立エピソード単位) ---
    print("\n=== bear regime中にスキップされたはずの買いシグナルの検証 ===")
    # フィルター無し版の全トレードのうち、エントリー時点でbear regimeだったものを抽出
    skipped_like = [t for t in tr_base if not regime[t.buy_i]]
    print(f"フィルター無し版でbear regime中にエントリーしたトレード数: {len(skipped_like)}/{len(tr_base)}")
    from collections import defaultdict
    by_year: dict[int, list[Trade]] = defaultdict(list)
    for t in skipped_like:
        by_year[dates[t.buy_i].year].append(t)
    for y in sorted(by_year):
        ts = by_year[y]
        rets = [(t.sell_px / t.buy_px - 1) * 100 for t in ts]
        print(f"  {y}年: {len(ts)}件, 個々のリターン={['%+.1f%%' % r for r in rets]}")


if __name__ == "__main__":
    main()
