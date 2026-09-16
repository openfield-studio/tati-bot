#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
個別銘柄の「上がる予兆・下がる予兆」の検証(テクニカルシグナル)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

よく言われる4つのテクニカルシグナルが、実際にその後の値動きを予告しているか
日経225全銘柄・過去3年分の日足データで検証する:
  1. ゴールデンクロス: 25日移動平均が75日移動平均を上抜けた直後 →「上がる予兆」と言われる
  2. デッドクロス: 25日移動平均が75日移動平均を下抜けた直後 →「下がる予兆」と言われる
  3. 出来高急増: 出来高が過去20日平均の2倍以上 →「大きく動く予兆」と言われる(方向不定)
  4. 52週高値更新: 直近252営業日の高値を更新 →「モメンタム継続(さらに上がる)」と言われる
  5. 52週安値更新: 直近252営業日の安値を更新 →「さらに下がる」または「反発(買い場)」、
     どちらの予兆として働くか(1306のRSI逆張りロジックとの整合性チェックにもなる)

各シグナル発生後、20営業日・60営業日後のリターンを全銘柄・全発生回でプールして平均する。
比較対象として「シグナルなしの場合の平均的な20/60営業日リターン」も算出する。

使い方: python stock_signal_lab.py
"""
from __future__ import annotations
import statistics as pystats
from collections import defaultdict

import yfinance as yf

from value_screener import NIKKEI225

MA_SHORT, MA_LONG = 25, 75
LOOKBACK_52W = 252
VOLUME_SPIKE_WINDOW = 20
VOLUME_SPIKE_RATIO = 2.0
FORWARD_DAYS = [20, 60]


def analyze_stock(code: str):
    """1銘柄分の全シグナル発生日と、その後のリターンを収集する。"""
    try:
        df = yf.Ticker(f"{code}.T").history(period="3y", interval="1d")
    except Exception:
        return None
    if len(df) < LOOKBACK_52W + MA_LONG + max(FORWARD_DAYS) + 10:
        return None

    closes = df["Close"].tolist()
    volumes = df["Volume"].tolist()
    n = len(closes)

    ma_short = [None] * n
    ma_long = [None] * n
    for i in range(MA_LONG - 1, n):
        ma_short[i] = sum(closes[i - MA_SHORT + 1:i + 1]) / MA_SHORT
        ma_long[i] = sum(closes[i - MA_LONG + 1:i + 1]) / MA_LONG

    events = defaultdict(list)  # signal_name -> [(index, )]

    for i in range(MA_LONG, n - max(FORWARD_DAYS)):
        # --- ゴールデンクロス/デッドクロス ---
        if ma_short[i - 1] is not None and ma_long[i - 1] is not None:
            if ma_short[i - 1] <= ma_long[i - 1] and ma_short[i] > ma_long[i]:
                events["golden_cross"].append(i)
            if ma_short[i - 1] >= ma_long[i - 1] and ma_short[i] < ma_long[i]:
                events["dead_cross"].append(i)

        # --- 出来高急増 ---
        if i >= VOLUME_SPIKE_WINDOW:
            avg_vol = sum(volumes[i - VOLUME_SPIKE_WINDOW:i]) / VOLUME_SPIKE_WINDOW
            if avg_vol > 0 and volumes[i] >= avg_vol * VOLUME_SPIKE_RATIO:
                events["volume_spike"].append(i)

        # --- 52週高値/安値更新 ---
        if i >= LOOKBACK_52W:
            window = closes[i - LOOKBACK_52W:i]
            if closes[i] > max(window):
                events["new_52w_high"].append(i)
            if closes[i] < min(window):
                events["new_52w_low"].append(i)

    result = {}
    for name, idxs in events.items():
        for fd in FORWARD_DAYS:
            rets = [closes[i + fd] / closes[i] - 1 for i in idxs if i + fd < n]
            result.setdefault(name, {})[fd] = rets

    # ベースライン(シグナル無関係の平均的なfd日リターン、全日から算出)
    baseline = {}
    for fd in FORWARD_DAYS:
        rets = [closes[i + fd] / closes[i] - 1 for i in range(MA_LONG, n - fd)]
        baseline[fd] = rets

    return result, baseline


def main() -> None:
    all_signal_rets = defaultdict(lambda: defaultdict(list))
    all_baseline_rets = defaultdict(list)

    print(f"日経225、{len(NIKKEI225)}銘柄のシグナル検証中...")
    processed = 0
    for i, (code, name) in enumerate(NIKKEI225, 1):
        out = analyze_stock(code)
        if out:
            signals, baseline = out
            for sig_name, fd_dict in signals.items():
                for fd, rets in fd_dict.items():
                    all_signal_rets[sig_name][fd] += rets
            for fd, rets in baseline.items():
                all_baseline_rets[fd] += rets
            processed += 1
        if i % 50 == 0:
            print(f"  {i}/{len(NIKKEI225)}件処理済み...")

    print(f"\n有効データが取れた銘柄数: {processed}/{len(NIKKEI225)}\n")
    print("=== ベースライン(シグナルと無関係の平均的なリターン) ===")
    for fd in FORWARD_DAYS:
        rets = all_baseline_rets[fd]
        print(f"  {fd}営業日後: 平均{pystats.mean(rets)*100:+.2f}% (n={len(rets)})")

    print("\n=== 各シグナル発生後のリターン(ベースラインとの差に注目) ===")
    SIGNAL_LABELS = {
        "golden_cross": "ゴールデンクロス(上がる予兆と言われる)",
        "dead_cross": "デッドクロス(下がる予兆と言われる)",
        "volume_spike": "出来高急増(大きく動く予兆と言われる)",
        "new_52w_high": "52週高値更新(モメンタム継続と言われる)",
        "new_52w_low": "52週安値更新(さらなる下落 or 反発?)",
    }
    for sig_name, label in SIGNAL_LABELS.items():
        fd_dict = all_signal_rets.get(sig_name, {})
        if not fd_dict:
            continue
        print(f"\n[{label}]")
        for fd in FORWARD_DAYS:
            rets = fd_dict.get(fd, [])
            if not rets:
                continue
            base = pystats.mean(all_baseline_rets[fd])
            avg = pystats.mean(rets)
            med = pystats.median(rets)
            print(f"  {fd}営業日後: 平均{avg*100:+.2f}%(中央値{med*100:+.2f}%, n={len(rets)}) "
                  f"/ ベースライン{base*100:+.2f}% / 差{((avg-base)*100):+.2f}pt")


if __name__ == "__main__":
    main()
