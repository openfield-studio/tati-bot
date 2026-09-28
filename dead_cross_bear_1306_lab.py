#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1306に「デッドクロス時は1569(TOPIXベア)へ切り替え」を追加適用した場合の検証
=====================================================================================
ユーザーの「1306にベア適用してデッドクロスも検証したんだっけ？」「うん(試して)」
(2026-09-28)を受けて新規作成。

今日(項目120、dead_cross_1306_lab.py)は「デッドクロス時は新規買いを見送るだけ」を
検証してNO-GOだった。今回はregime_shift_agent.py(1321/1571)と同じ設計思想
(通常時はロング、デッドクロス確定時はベア銘柄に切り替え)を1306/1569に適用する版を
新規に検証する。

設計(既存の各戦略のロジックをそのまま踏襲、過剰最適化を避けるため新規のパラメータ探索は
しない):
- エントリートリガー: 1306の本番と同じRSI<40(売られすぎ)。regime_shift_agent.pyの
  ショック検知〈1日-2.5%〉ではなく、1306本来のロジックを維持する。
- 通常相場(デッドクロス無し): 1306を買う。利確はRSI>=50回復、損切り8%(本番と同じ)。
- 下落相場(デッドクロス: 120日MA<350日MA): 1569を買う。利確・損切りは
  regime_shift_agent.pyのベア設定(利確5%/損切り18%/最大保有20営業日)をそのまま流用
  (新規探索するとこの1回の検証のためだけにパラメータを選ぶことになり過剰最適化になるため)。
- 対象期間: 1569の実データが取れる2012-04-03〜(1306は2009年からあるが、実データ優先の
  方針(項目109)に従い両方が揃う期間のみで検証)。

比較対象: (a)今日のNO-GO版(見送りのみ)、(b)本番(フィルター無し)、(c)今回のベア切替版。

使い方: python dead_cross_bear_1306_lab.py
"""
from __future__ import annotations
import dataclasses
import sys

sys.path.insert(0, ".")
import regime_shift_agent as rsa
from research_agents import ResearchConfig, StrategyParams, _rsi

CFG = ResearchConfig()

# regime_shift_agent.pyのベア設定をそのまま流用(新規探索しない)
BEAR_TP = 0.05
BEAR_SL = 0.18
BEAR_MAX_HOLD = 20


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
    target: str
    why: str


def run_backtest(prices_long: list[float], prices_bear: list[float] | None,
                  sp: StrategyParams, regime: list[bool] | None) -> tuple[list[float], list[Trade]]:
    """regime[i]=True なら bull。Noneならフィルター無し(本番そのまま)。
    prices_bearがNoneならベア切替なし(=今日のNO-GO版=見送りのみ)。"""
    c = CFG
    cash = float(c.capital_yen)
    shares = 0
    entry = 0.0
    buy_i = -1
    holding_target = None  # "long" or "bear"
    equity_curve: list[float] = []
    trades: list[Trade] = []
    fee = (c.commission_bps + c.slippage_bps) / 10000.0

    for i, px in enumerate(prices_long):
        px_bear = prices_bear[i] if prices_bear is not None else None
        rsi = _rsi(prices_long, i, sp.rsi_period)

        if shares > 0:
            cur_px = px if holding_target == "long" else px_bear
            exit_now, why = False, ""
            if holding_target == "long":
                if sp.stop_loss_pct > 0 and cur_px <= entry * (1 - sp.stop_loss_pct):
                    exit_now, why = True, "stop"
                elif rsi is not None and rsi >= sp.rsi_exit:
                    exit_now, why = True, "rsi_recover"
            else:  # bear
                r = cur_px / entry - 1
                held = i - buy_i
                if r >= BEAR_TP:
                    exit_now, why = True, "bear_tp"
                elif r <= -BEAR_SL:
                    exit_now, why = True, "bear_sl"
                elif held >= BEAR_MAX_HOLD:
                    exit_now, why = True, "bear_maxhold"
            if exit_now:
                cash += shares * cur_px * (1 - fee)
                trades.append(Trade(buy_i, entry, i, cur_px, holding_target, why))
                shares, entry, buy_i, holding_target = 0, 0.0, -1, None
        elif rsi is not None:
            buy_now = rsi < sp.rsi_oversold
            if buy_now:
                is_bull = regime[i] if regime is not None else True
                if is_bull:
                    target, price = "long", px
                elif prices_bear is not None and px_bear is not None:
                    target, price = "bear", px_bear
                else:
                    target, price = None, None  # 今日のNO-GO版=見送り
                if target is not None:
                    qty = int(cash // (price * (1 + fee) * c.trade_unit)) * c.trade_unit
                    if qty > 0:
                        cash -= qty * price * (1 + fee)
                        shares, entry, buy_i, holding_target = qty, price, i, target
        equity_curve.append(cash + shares * (px if holding_target != "bear" else (px_bear or px)))

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
    n_bear = sum(1 for t in trades if t.target == "bear")
    return {"return_pct": ret, "max_dd_pct": max_dd * 100, "trades": n,
            "bear_trades": n_bear, "win_rate": (wins / n * 100) if n else 0.0}


def main() -> None:
    closes_long = rsa.fetch_closes("1306.T", min_days=100)
    closes_bear = rsa.fetch_closes("1569.T", min_days=100)

    common_start = max(closes_long[0][0], closes_bear[0][0])
    dates_long = [d for d, _ in closes_long if d >= common_start]
    prices_long = [p for d, p in closes_long if d >= common_start]

    px_bear_map = dict(closes_bear)
    prices_bear = [px_bear_map.get(d) for d in dates_long]
    # 1569に欠測がある日は直前値で埋める(まれな非取引日ズレ対策)
    last = None
    for i, v in enumerate(prices_bear):
        if v is None:
            prices_bear[i] = last
        else:
            last = v
    if prices_bear[0] is None:
        raise SystemExit("1569の先頭データが欠測、common_startを見直すこと")

    print(f"検証期間: {dates_long[0]} ~ {dates_long[-1]} ({len(prices_long)}本、1569実データが揃う範囲)")

    sp = StrategyParams("rsi_only_prod", "rsi_only", 0, 0, 14, 75, 40, 50, 0.08, 0.0)

    ma_fast = _sma_series(prices_long, 120)
    ma_slow = _sma_series(prices_long, 350)
    regime = [True if ms is None else (mf >= ms) for mf, ms in zip(ma_fast, ma_slow)]

    eq_base, tr_base = run_backtest(prices_long, None, sp, None)
    eq_skip, tr_skip = run_backtest(prices_long, None, sp, regime)
    eq_bear, tr_bear = run_backtest(prices_long, prices_bear, sp, regime)

    print("\n=== 全期間比較 ===")
    print(f"(a)本番(フィルター無し)      : {metrics(eq_base, tr_base)}")
    print(f"(b)デッドクロス時は見送りのみ  : {metrics(eq_skip, tr_skip)}")
    print(f"(c)デッドクロス時は1569へ切替 : {metrics(eq_bear, tr_bear)}")

    split = int(len(prices_long) * CFG.is_ratio)
    for label, sl in (("IS", slice(0, split)), ("OOS", slice(split, None))):
        pl, pb, rg = prices_long[sl], prices_bear[sl], regime[sl]
        eb, tb = run_backtest(pl, None, sp, None)
        es, ts = run_backtest(pl, None, sp, rg)
        ec, tc = run_backtest(pl, pb, sp, rg)
        print(f"\n=== {label} ({dates_long[sl][0]}~{dates_long[sl][-1]}, {len(pl)}本) ===")
        print(f"(a)本番        : {metrics(eb, tb)}")
        print(f"(b)見送りのみ   : {metrics(es, ts)}")
        print(f"(c)1569へ切替  : {metrics(ec, tc)}")

    print("\n=== 1569へのトレード内訳 ===")
    bear_trades = [t for t in tr_bear if t.target == "bear"]
    for t in bear_trades:
        r = t.sell_px / t.buy_px - 1
        print(f"  {dates_long[t.buy_i]}買い→{dates_long[t.sell_i]}({t.why}) リターン{r*100:+.2f}%")


if __name__ == "__main__":
    main()
