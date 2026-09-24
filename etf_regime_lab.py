#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1321(日経225 ETF)・1571(日経平均インバースETF)の実データで
ドローダウン基準レジームフィルター戦略を再検証 検証ラボ
=====================================================================
※本体には組み込まない。event_driven_regime_test_prompt.mdの手順に従うイベント駆動戦略・
深掘りルーティンの続き(2026-09-24)。項目105〜107で日経平均(^N225)の理論値を使って
設計した戦略を、実際に取引可能な1321(ロング)・1571(単純-1倍インバース、空売り不要)の
実データで再検証する。

設計(項目100・101・107で確定した最終版と同じロジック、対象銘柄だけ差し替え):
- レジーム判定: 1321自身の直近252営業日高値からのドローダウンが20%以上→「下落相場」
- ショック検知: 1321自身の1日-2.5%以下の下落、cooldown15営業日
- 通常相場のショック→1321を買う、損切り30%、利確なし
- 下落相場のショック→1571を買う(空売り不要、単純-1倍インバースなので買うだけでベア相当)、
  利確5%・損切り18%(1571自身の価格変動で判定、符号反転は不要)

使い方: python etf_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats

import yfinance as yf

import market_event_bear_lab as m
import systematic_decline_short_lab as s
import drawdown_regime_lab as d

COST_ROUNDTRIP = 0.002


def fetch_etf(ticker: str) -> dict[dt.date, float]:
    """1321/1571は個別ETFなので、1306と同じ分割断崖チェックを適用(念のため)。"""
    df = yf.Ticker(ticker).history(period="max", auto_adjust=True).dropna(subset=["Close"])
    dates = [idx.date() for idx in df.index]
    px_list = [float(x) for x in df["Close"].tolist()]
    for i in range(1, len(px_list)):
        r = px_list[i] / px_list[i - 1]
        if r < 0.7:
            factor = round(1 / r)
            if factor >= 2:
                for k in range(i):
                    px_list[k] /= factor
        elif r > 1.4:
            factor = round(r)
            if factor >= 2:
                for k in range(i):
                    px_list[k] *= factor
    return dict(zip(dates, px_list))


def main():
    closes_1321 = fetch_etf("1321.T")
    closes_1571 = fetch_etf("1571.T")

    common_start = max(min(closes_1321), min(closes_1571))
    print(f"1321データ: {min(closes_1321)}〜{max(closes_1321)}")
    print(f"1571データ: {min(closes_1571)}〜{max(closes_1571)}")
    print(f"両方使える期間: {common_start}〜{max(closes_1321)}\n")

    # レジーム判定・ショック検知は1321自身の値動きで行う
    high_1321 = d.trailing_high(closes_1321, 252)
    shocks = s.find_shock_days(closes_1321, s.THRESHOLD, s.COOLDOWN)
    shocks = [d0 for d0 in shocks if d0 >= common_start]
    dd_th = 0.20

    keys_1321 = sorted(closes_1321)
    idx_1321 = {k: i for i, k in enumerate(keys_1321)}

    def window_for(d0, ticker_closes, tp_pct, sl_pct, max_days=20):
        entry_idx = idx_1321[d0] + 1
        if entry_idx >= len(keys_1321):
            return None
        entry_date = keys_1321[entry_idx]
        if entry_date not in ticker_closes:
            return None
        entry_price = ticker_closes[entry_date]
        last_i = entry_idx
        for i in range(entry_idx + 1, min(entry_idx + max_days + 1, len(keys_1321))):
            day = keys_1321[i]
            if day not in ticker_closes:
                continue
            r = ticker_closes[day] / entry_price - 1
            last_i = i
            if tp_pct is not None and r >= tp_pct:
                return entry_date, day, r
            if r <= -sl_pct:
                return entry_date, day, r
        return entry_date, keys_1321[last_i], ticker_closes[keys_1321[last_i]] / entry_price - 1

    trades = []
    for d0 in shocks:
        if d0 not in high_1321:
            continue
        dd = 1 - closes_1321[d0] / high_1321[d0]
        if dd < dd_th:
            w = window_for(d0, closes_1321, None, 0.30)
            side = "1321(ロング)"
        else:
            w = window_for(d0, closes_1571, 0.05, 0.18)
            side = "1571(ベア代替)"
        if w is None:
            continue
        entry_date, exit_date, r = w
        net = r - COST_ROUNDTRIP
        trades.append((d0, entry_date, exit_date, side, net))

    print(f"検出したトレード数: {len(trades)}\n")
    for d0, ed, xd, side, net in trades:
        print(f"  {d0}(検知)→{ed}〜{xd}  {side}  リターン{net*100:+.2f}%")

    pnls = [t[4] for t in trades]
    if pnls:
        wins = sum(1 for p in pnls if p > 0)
        print(f"\n単純加算: 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
              f"平均{pystats.mean(pnls)*100:+.2f}% 中央値{pystats.median(pnls)*100:+.2f}% "
              f"合計{sum(pnls)*100:+.1f}%")

    # 複利(1321買い持ちベース+トレードのタイミングで差し替え)
    equity = 1.0
    last_end = None
    for d0, ed, xd, side, net in trades:
        if last_end is None:
            equity *= closes_1321[ed] / closes_1321[keys_1321[idx_1321[common_start]]]
        else:
            equity *= closes_1321[ed] / closes_1321[last_end]
        equity *= (1 + net)
        last_end = xd
    if last_end:
        equity *= closes_1321[keys_1321[-1]] / closes_1321[last_end]
    buyhold = closes_1321[keys_1321[-1]] / closes_1321[keys_1321[idx_1321[common_start]]]
    print(f"\n複利(1321買い持ち+ショック時だけ切替): {equity:.2f}倍")
    print(f"比較: 1321をそのまま買い持ちした場合: {buyhold:.2f}倍")


if __name__ == "__main__":
    main()
