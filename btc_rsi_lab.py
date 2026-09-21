#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ビットコイン(BTC-USD)日足での純RSI逆張り戦略 検証ラボ(バックテストのみ)
=====================================================================
※本体には組み込まない。口座・入金・発注は一切なし。「試したらどうなるか」の記録。

ユーザーの「ビットコインでもできる?→検証だけしてみて」を受けて実施。
1306のGO戦略(RSI<40買い・RSI>=50利確・損切り-8%)を、パラメータを一切いじらず
BTCの日足にそのまま当てて、①買い持ち放置との比較、②IS/OOS、③年別成績、
④取引コスト感度を見る。加えて⑤research_agents.pyのパイプライン(パラメータ探索+
ウォークフォワード)も1571ラボと同じ手順で回す。

注意:
 - fetch_yf.pyの「分割の断崖チェック」(1日±30%超を分割とみなす)はBTCで誤作動する
   (BTCは1日で30%超下がる日がある)ため、使わず直接yfinanceから取得する。
 - BTCは24時間365日取引なので年率換算は365日。日足の「翌日始値」は前日終値とほぼ同じで、
   株のような約定ズレの問題は小さい(代わりに取引コストを感度分析する)。
 - 価格は1/1000(=1mBTC単位)にスケールして整数株数の粗さを避ける。
   RSI・損切り・リターンはスケール不変。

使い方: python btc_rsi_lab.py
"""
from __future__ import annotations
import json
import logging
import statistics as pystats
from collections import defaultdict

import yfinance as yf

import research_agents as ra
from research_agents import (Backtester, BacktestResult, MetricsAgent, ResearchConfig,
                             ResearchMasterAgent, StrategyParams)

logging.basicConfig(level=logging.WARNING)

RULE_1306 = StrategyParams("rsi_only_1306", "rsi_only", 0, 0, 14, 75, 40, 50, 0.08, 0.0)


def fetch_btc():
    df = yf.Ticker("BTC-USD").history(period="max", auto_adjust=True)
    df = df.dropna(subset=["Close"])
    dates = [d.date() for d in df.index]
    closes = [float(x) / 1000.0 for x in df["Close"].tolist()]
    return dates, closes


def make_cfg(commission_bps=10.0, slippage_bps=5.0, result_path="research_result_btc.json"):
    return ResearchConfig(capital_yen=500_000, trade_unit=1, symbol="BTC",
                          commission_bps=commission_bps, slippage_bps=slippage_bps,
                          trading_days_per_year=365, result_path=result_path)


def buy_hold(prices, cfg):
    cap = float(cfg.capital_yen)
    eq = [cap * p / prices[0] for p in prices]
    return BacktestResult(eq, [], eq[-1])


def fmt(m):
    pf = m["profit_factor"]
    pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
    return (f"利益率{m['return_pct']:+8.1f}% / 最大DD{m['max_dd_pct']:5.1f}% / Sharpe{m['sharpe']:5.2f} / "
            f"取引{m['trades']:3d}回 / 勝率{m['win_rate']*100:4.0f}% / PF{pf_s}")


def exposure(res, n):
    """買い持ち期間の割合(日数ベース)。"""
    inpos, buy_i = 0, None
    for t in res.trades:
        if t["side"] == "BUY":
            buy_i = t["i"]
        elif t["side"] == "SELL" and buy_i is not None:
            inpos += t["i"] - buy_i
            buy_i = None
    if buy_i is not None:
        inpos += n - buy_i
    return inpos / n if n else 0.0


def segment_report(label, prices, cfg, met):
    bt = Backtester(cfg)
    res = bt.run(prices, RULE_1306)
    m = met.metrics(res)
    bh = met.metrics(buy_hold(prices, cfg))
    print(f"[{label}](n={len(prices)}本)")
    print(f"  1306ルール : {fmt(m)} / 保有率{exposure(res, len(prices))*100:.0f}%")
    print(f"  買い持ち   : {fmt(bh)}")
    return m, bh, res


def yearly(dates, prices, cfg):
    """暦年ごとに独立にバックテスト(年初に現金スタート)して買い持ちと比較する。"""
    bt = Backtester(cfg)
    met = MetricsAgent(cfg)
    by_year = defaultdict(list)
    for d, p in zip(dates, prices):
        by_year[d.year].append(p)
    print(f"{'年':>5s} {'1306ルール':>10s} {'買い持ち':>9s} {'取引':>4s}")
    wins = 0
    rows = []
    for y in sorted(by_year):
        ps = by_year[y]
        if len(ps) < 120:
            continue
        m = met.metrics(bt.run(ps, RULE_1306))
        b = met.metrics(buy_hold(ps, cfg))
        rows.append((y, m["return_pct"], b["return_pct"], m["trades"]))
        if m["return_pct"] > b["return_pct"]:
            wins += 1
        print(f"{y:>5d} {m['return_pct']:>+9.1f}% {b['return_pct']:>+8.1f}% {m['trades']:>4d}")
    pos = sum(1 for r in rows if r[1] > 0)
    print(f"→ ルールがプラスの年 {pos}/{len(rows)}、買い持ちに勝った年 {wins}/{len(rows)}")
    return rows


def main():
    dates, prices = fetch_btc()
    n = len(prices)
    print(f"BTC-USD日足: {dates[0]}〜{dates[-1]} / {n}本 / 最終{prices[-1]*1000:,.0f}USD")
    rets = [prices[i] / prices[i - 1] - 1 for i in range(1, n)]
    print(f"日次リターン: 最悪{min(rets)*100:.1f}% 最良{max(rets)*100:+.1f}% (分割補正はしていない)\n")

    cfg = make_cfg()
    met = MetricsAgent(cfg)
    split = int(n * cfg.is_ratio)

    print("=" * 78)
    print(f"A. 1306ルール(RSI<40買い/>=50利確/損切り8%)をBTCにそのまま適用"
          f" (片道コスト{cfg.commission_bps + cfg.slippage_bps:.0f}bps仮定)")
    print("=" * 78)
    segment_report("全期間", prices, cfg, met)
    print(f"  (IS/OOS分割日: {dates[split]})")
    segment_report("IS(前65%)", prices[:split], cfg, met)
    segment_report("OOS(後35%)", prices[split:], cfg, met)

    print("\n" + "=" * 78)
    print("B. 暦年別(年初に現金スタートで独立実行) vs 買い持ち")
    print("=" * 78)
    yearly(dates, prices, cfg)

    print("\n" + "=" * 78)
    print("C. 取引コスト感度(全期間、片道bps)")
    print("=" * 78)
    for total in (5, 15, 30, 60, 100):
        c2 = make_cfg(commission_bps=total * 2 / 3, slippage_bps=total / 3)
        m = MetricsAgent(c2).metrics(Backtester(c2).run(prices, RULE_1306))
        print(f"  片道{total:>3d}bps: {fmt(m)}")

    print("\n" + "=" * 78)
    print("D. パイプライン(パラメータ探索+ウォークフォワード、1571ラボと同手順)")
    print("=" * 78)
    ra.load_prices = lambda symbol, n_=6000: prices
    result = ResearchMasterAgent(make_cfg()).run()
    print(f"判定: {result['verdict']}")
    for w in result["warnings"]:
        print(f"  ⚠ {w}")
    st = result["strategy"]
    if st:
        print(f"採用パラメータ: RSI<{st['rsi_oversold']:.0f}買い/>={st['rsi_exit']:.0f}利確/損切り{st['stop_loss_pct']*100:.0f}%")
    print(f"IS : {fmt(result['in_sample'])}" if result["in_sample"] else "IS: なし")
    print(f"OOS: {fmt(result['out_of_sample'])}" if result["out_of_sample"] else "OOS: なし")
    wf = result.get("walk_forward")
    if wf:
        print(f"ウォークフォワード: {wf['positive']}/{wf['total']}区間プラス "
              f"[{', '.join(f'{f['oos_return_pct']:+.0f}%' for f in wf['folds'])}]")


if __name__ == "__main__":
    main()
