#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ビットコイン(BTC-USD)日足の時系列モメンタム 検証ラボ(バックテストのみ)
=====================================================================
※本体には組み込まない。口座・発注なし。btc_anomaly_reference.md #2の検証。

ルール: 直近L日リターン>0なら翌日1日保有(ロングのみ)、そうでなければ現金。
  シグナルは日次終値で判定し、翌日のリターンに適用する(先読みなし)。BTCは24時間
  取引なので「翌日始値≒当日終値」とみなす。切替ごとに片道コストを引く。
比較: 買い持ち。L={7,14,21,30,60,90,120,180}を全部並べ、IS(前65%)の
  Sharpe最良のLをOOS(後35%)で確認する(後出しで最良を選ばない)。試行数は8。

使い方: python btc_tsmom_lab.py
"""
from __future__ import annotations
import math
import statistics as pystats
from collections import defaultdict

import yfinance as yf

LOOKBACKS = [7, 14, 21, 30, 60, 90, 120, 180]
COST = 0.0015  # 片道15bps(手数料10+スリッページ5)
IS_RATIO = 0.65
DAYS = 365


def fetch():
    df = yf.Ticker("BTC-USD").history(period="max", auto_adjust=True).dropna(subset=["Close"])
    return [d.date() for d in df.index], [float(x) for x in df["Close"].tolist()]


def strategy_returns(p, L, cost):
    """日次純リターン(index t = p[t-1]→p[t]のリターン)と保有フラグ。t<=Lは保有なし。"""
    n = len(p)
    pos = [0] * n  # pos[t]: t日終値時点のシグナル(t+1日に保有)
    for t in range(L, n):
        pos[t] = 1 if p[t] / p[t - L] - 1 > 0 else 0
    rets = [0.0] * n
    held = [0] * n
    for t in range(1, n):
        prev = pos[t - 1]
        prev2 = pos[t - 2] if t >= 2 else 0
        rets[t] = prev * (p[t] / p[t - 1] - 1) - cost * abs(prev - prev2)
        held[t] = prev
    return rets, held


def stats(rets, held=None):
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
    n = len(rets)
    sd = pystats.stdev(rets) if n > 1 else 0.0
    sharpe = pystats.mean(rets) / sd * math.sqrt(DAYS) if sd > 0 else 0.0
    ann = eq ** (DAYS / n) - 1 if n > 0 and eq > 0 else -1.0
    exp = sum(held) / n if held is not None and n else 1.0
    trades = 0
    if held is not None:
        trades = sum(1 for i in range(1, n) if held[i] == 1 and held[i - 1] == 0)
    return {"total": (eq - 1) * 100, "ann": ann * 100, "sharpe": sharpe,
            "mdd": mdd * 100, "exp": exp * 100, "trades": trades}


def line(label, s):
    return (f"{label:<10s} 累計{s['total']:>+10.0f}% 年率{s['ann']:>+6.1f}% Sharpe{s['sharpe']:>5.2f} "
            f"最大DD{s['mdd']:>5.1f}% 保有率{s['exp']:>4.0f}% 買い{s['trades']:>3d}回")


def main():
    dates, p = fetch()
    n = len(p)
    split = int(n * IS_RATIO)
    start = max(LOOKBACKS) + 1  # 全Lで共通の比較開始位置(公平に揃える)
    print(f"BTC-USD日足 {dates[0]}〜{dates[-1]} {n}本 / 比較区間は{dates[start]}〜(全Lで揃える)")
    print(f"IS/OOS分割日: {dates[split]} / 片道コスト{COST*1e4:.0f}bps / 試行数{len(LOOKBACKS)}\n")

    bh = [0.0] + [p[t] / p[t - 1] - 1 for t in range(1, n)]
    segs = {"全期間": (start, n), "IS": (start, split), "OOS": (split, n)}

    results = {}
    for L in LOOKBACKS:
        rets, held = strategy_returns(p, L, COST)
        results[L] = (rets, held)

    for name, (a, b) in segs.items():
        print("=" * 92)
        print(f"{name}({dates[a]}〜{dates[b-1]}, {b-a}日)")
        print("=" * 92)
        print(line("買い持ち", stats(bh[a:b])))
        for L in LOOKBACKS:
            rets, held = results[L]
            print(line(f"モメンタム{L}日", stats(rets[a:b], held[a:b])))
        print()

    # IS Sharpe最良のLを選び、OOSで確認
    a, b = segs["IS"]
    best = max(LOOKBACKS, key=lambda L: stats(results[L][0][a:b], results[L][1][a:b])["sharpe"])
    print("=" * 92)
    print(f"IS期間のSharpe最良 = {best}日 → OOSで確認")
    print("=" * 92)
    oa, ob = segs["OOS"]
    s_oos = stats(results[best][0][oa:ob], results[best][1][oa:ob])
    b_oos = stats(bh[oa:ob])
    print(line("買い持ち", b_oos))
    print(line(f"モメンタム{best}日", s_oos))
    beat = sum(1 for L in LOOKBACKS
               if stats(results[L][0][oa:ob], results[L][1][oa:ob])["sharpe"] > b_oos["sharpe"])
    lowdd = sum(1 for L in LOOKBACKS
                if stats(results[L][0][oa:ob], results[L][1][oa:ob])["mdd"] < b_oos["mdd"])
    print(f"→ OOSで買い持ちよりSharpeが高いL: {beat}/{len(LOOKBACKS)}、最大DDが小さいL: {lowdd}/{len(LOOKBACKS)}")

    # 暦年別(IS選択のL)
    print("\n" + "=" * 92)
    print(f"暦年別({best}日) vs 買い持ち")
    print("=" * 92)
    by_year = defaultdict(list)
    for t in range(start, n):
        by_year[dates[t].year].append(t)
    wins = 0
    rows = 0
    print(f"{'年':>5s} {'モメンタム':>10s} {'買い持ち':>9s} {'保有率':>6s}")
    for y in sorted(by_year):
        idx = by_year[y]
        if len(idx) < 120:
            continue
        r = [results[best][0][t] for t in idx]
        h = [results[best][1][t] for t in idx]
        rb = [bh[t] for t in idx]
        s, sb = stats(r, h), stats(rb)
        rows += 1
        wins += s["total"] > sb["total"]
        print(f"{y:>5d} {s['total']:>+9.1f}% {sb['total']:>+8.1f}% {s['exp']:>5.0f}%")
    print(f"→ 買い持ちに勝った年 {wins}/{rows}")

    # コスト感度(全期間、best)
    print("\n" + "=" * 92)
    print(f"コスト感度(全期間、{best}日、片道bps)")
    print("=" * 92)
    a, b = segs["全期間"]
    for c in (0, 5, 15, 30, 60):
        rets, held = strategy_returns(p, best, c / 1e4)
        print(line(f"{c}bps", stats(rets[a:b], held[a:b])))


if __name__ == "__main__":
    main()
