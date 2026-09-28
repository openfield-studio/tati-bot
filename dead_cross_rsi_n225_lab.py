#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「1306と同じRSI<40エントリー」を日経平均61年データ(1965〜2026)に当てて、
デッドクロス+ベア切替が機能するかを検証(2026-09-28)。

ユーザーの「1321のデッドクロスはうまくいくのにこっちは何で?」を受けた切り分け実験。
項目123(1306+1569、2012〜2026年、NO-GO)は、本物の暴落を含まない期間での検証
だった可能性がある。日経平均の61年データ(1965〜2026、石油危機・バブル崩壊・
アジア危機・ITバブル崩壊・リーマンショック等を含む)に、1306と同じRSI<40エントリーを
当てて、デッドクロス+ベア切替(regime_shiftと同じ利確5%/損切り18%/最大保有20日)が
機能するかを確認する。エントリー条件だけを1306式(RSI<40)に変え、他は全てregime_shift
(1321/1571)側の検証と揃える。ベア側は日経平均自身の-1倍(理論値、1571同様の想定)。
"""
from __future__ import annotations
import sys
sys.path.insert(0, ".")
import nikkei_long_term_stoploss_lab as n
from research_agents import ResearchConfig, StrategyParams, _rsi

CFG = ResearchConfig()
BEAR_TP, BEAR_SL, BEAR_MAX_HOLD = 0.05, 0.18, 20


def _sma_series(px, w):
    out = [None]*len(px)
    s = 0.0
    for i, v in enumerate(px):
        s += v
        if i >= w:
            s -= px[i-w]
        if i >= w-1:
            out[i] = s/w
    return out


def run(prices, sp, regime):
    c = CFG
    cash = float(c.capital_yen)
    shares = 0; entry = 0.0; buy_i = -1; target = None
    eq = []; trades = []
    fee = (c.commission_bps + c.slippage_bps)/10000.0
    for i, px in enumerate(prices):
        rsi = _rsi(prices, i, sp.rsi_period)
        if shares > 0:
            if target == "long":
                exit_now = (px <= entry*(1-sp.stop_loss_pct)) or (rsi is not None and rsi >= sp.rsi_exit)
                cur = px
            else:
                r = px/entry - 1
                held = i - buy_i
                exit_now = (r >= BEAR_TP) or (r <= -BEAR_SL) or (held >= BEAR_MAX_HOLD)
                cur = px  # 理論ベア: 日経平均自身の-1倍として判定(rはlong基準、実質は-r相当をここでは別途変換)
            if target == "bear":
                # bear PnLはlong基準pxの変化の符号反転
                r_signed = -(px/entry - 1)
                held = i - buy_i
                exit_now = (r_signed >= BEAR_TP) or (r_signed <= -BEAR_SL) or (held >= BEAR_MAX_HOLD)
                if exit_now:
                    pnl_px = entry*(1+r_signed)  # 決済「価格」相当(現金換算用の仮想値)
                    cash += shares*entry*(1+r_signed)*(1-fee)
                    trades.append((buy_i, i, target, r_signed))
                    shares, entry, buy_i, target = 0, 0.0, -1, None
            else:
                if exit_now:
                    cash += shares*px*(1-fee)
                    trades.append((buy_i, i, target, px/entry-1))
                    shares, entry, buy_i, target = 0, 0.0, -1, None
        elif rsi is not None and rsi < sp.rsi_oversold:
            is_bull = regime[i] if regime is not None else True
            qty = int(cash // (px*(1+fee)*c.trade_unit)) * c.trade_unit
            if qty > 0:
                cash -= qty*px*(1+fee)
                shares, entry, buy_i, target = qty, px, i, ("long" if is_bull else "bear")
        if target == "bear" and shares > 0:
            r_signed = -(px/entry-1)
            eq.append(cash + shares*entry*(1+r_signed))
        else:
            eq.append(cash + shares*px)
    return eq, trades


def metrics(eq, trades):
    start, end = eq[0], eq[-1]
    ret = (end/start-1)*100
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    wins = sum(1 for t in trades if t[3] > 0)
    nb = sum(1 for t in trades if t[2] == "bear")
    return {"return_pct": ret, "max_dd_pct": mdd*100, "trades": len(trades),
            "bear_trades": nb, "win_rate": (wins/len(trades)*100) if trades else 0}


def main():
    closes = n.fetch_closes(n.TICKER)
    dates = sorted(closes)
    prices = [closes[d] for d in dates]
    print(f"日経平均: {dates[0]} ~ {dates[-1]} ({len(prices)}本)")

    sp = StrategyParams("rsi1306style", "rsi_only", 0, 0, 14, 75, 40, 50, 0.08, 0.0)
    ma_f = _sma_series(prices, 120); ma_s = _sma_series(prices, 350)
    regime = [True if ms is None else (mf >= ms) for mf, ms in zip(ma_f, ma_s)]

    eq_a, tr_a = run(prices, sp, None)
    eq_b, tr_b = run(prices, sp, regime)  # skip版は別途(is_bull=False時にbearでなくskipにするパスが無いので、
                                            # ここではbear版のみ評価。skip版はrun()にNoneを渡した基準と比較)
    print(f"\n(a)フィルター無し: {metrics(eq_a, tr_a)}")
    print(f"(c)デッドクロス時1569相当へ切替: {metrics(eq_b, tr_b)}")

    split = int(len(prices)*CFG.is_ratio)
    for label, sl in (("IS(1965-1999頃)", slice(0, split)), ("OOS(2000-2026)", slice(split, None))):
        pa, ra = prices[sl], (regime[sl])
        ea, ta = run(pa, sp, None)
        eb, tb = run(pa, sp, ra)
        print(f"\n{label} ({dates[sl][0]}~{dates[sl][-1]}):")
        print(f"  (a)フィルター無し: {metrics(ea, ta)}")
        print(f"  (c)デッドクロス+切替: {metrics(eb, tb)}")

    print("\nベアトレード内訳(上位/下位含め全件):")
    for bi, si, tgt, r in tr_b:
        if tgt == "bear":
            print(f"  {dates[bi]}買い→{dates[si]}  リターン{r*100:+.2f}%")


if __name__ == "__main__":
    main()
