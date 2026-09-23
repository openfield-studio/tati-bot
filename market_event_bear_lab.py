#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
market_events.json(1306/TOPIX全体イベント)のベア(空売り)シミュレーション 検証ラボ
=====================================================================
※本体には組み込まない。company_event_study_lab.pyと同じ手法を1306単体に適用する検証。
「1306全体でも同じベア検証をやってみて」を受けて作成。

対象: market_events.jsonのdirection="down"のイベント。
先読み防止のため、ニュース当日(d0、多くは取引時間外の発表)には反応せず、
翌営業日(早耳REACT+1)/さらに1日空けた翌々営業日(安全REACT+2)にエントリーし、
+5営業日・+20営業日で決済する空売りを想定する。

★除外ルール(重要)★ "底値"(トラフ)としてラベル付けした2件
(2020-03-19コロナショック底値、2025-04-07トランプ関税ショック底値)は、
そもそも下落が終わった地点を指すため「そこから空売り」は方向が逆(むしろ買い場)になり、
このシミュレーションの趣旨(下落トリガーの直後に空売り)に合わない。対応するトリガー日
(2020-03-11 WHOパンデミック宣言、2025-04-02 トランプ関税リベレーションデー発表)側を使う。

コストは往復20bps仮置き(1306は主要ETFで個別株より低コストと想定、要検証)。
1306が実際に貸株可能(一般的に大型ETFは信用売りの対象になりやすいと考えられるが未確認)かは
断定しない(ルール9に準拠)。

使い方: python market_event_bear_lab.py
"""
from __future__ import annotations
import datetime as dt
import json
import statistics as pystats

import yfinance as yf

EVENTS_FILE = "market_events.json"
TICKER = "1306.T"
COST_ROUNDTRIP = 0.002
EXCLUDE_TROUGHS = {"2020-03-19", "2025-04-07"}  # 底値ラベル、空売り起点として不適(理由は上記)


def fetch_split_safe(ticker: str) -> dict[dt.date, float]:
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


def price_on_or_before(closes: dict[dt.date, float], target: dt.date):
    keys = sorted(d for d in closes if d <= target)
    return (keys[-1], closes[keys[-1]]) if keys else None


def trading_day_offset(closes: dict[dt.date, float], anchor: dt.date, n: int):
    keys = sorted(d for d in closes if d >= anchor)
    return (keys[n], closes[keys[n]]) if len(keys) > n else None


def first_trading_day_after(closes: dict[dt.date, float], d0: dt.date, skip: int = 0):
    keys = sorted(d for d in closes if d > d0)
    return keys[skip] if len(keys) > skip else None


def main():
    events = json.load(open(EVENTS_FILE, encoding="utf-8"))
    closes = fetch_split_safe(TICKER)
    print(f"1306データ範囲: {min(closes)}〜{max(closes)}\n")

    down_events = [e for e in events if e["direction"] == "down" and e["date"] not in EXCLUDE_TROUGHS]
    print(f"対象(direction=down、底値ラベル{len(EXCLUDE_TROUGHS)}件を除外): {len(down_events)}件\n")

    short_trades: dict[str, dict[str, float]] = {}
    for ev in down_events:
        d0 = dt.date.fromisoformat(ev["date"])
        anchor = price_on_or_before(closes, d0)
        if anchor is None:
            print(f"[スキップ] {ev['date']} {ev['name']}: 価格データが無い期間")
            continue

        print("=" * 100)
        print(f"{ev['date']}  {ev['name']}  信頼度:{ev['confidence']}")
        short_trades[ev["date"]] = {}
        printed_any = False
        for react_label, skip in [("早耳(REACT+1)", 0), ("安全(REACT+2)", 1)]:
            entry_date = first_trading_day_after(closes, d0, skip=skip)
            if entry_date is None:
                continue
            entry_price = closes[entry_date]
            for hold_label, n_days in [("+5営業日", 5), ("+20営業日", 20)]:
                exit_ = trading_day_offset(closes, entry_date, n_days)
                if exit_ is None:
                    continue
                exit_date, exit_price = exit_
                r = exit_price / entry_price - 1
                gross = -r
                net = gross - COST_ROUNDTRIP
                key = f"{react_label}/{hold_label}"
                short_trades[ev["date"]][key] = net
                printed_any = True
                print(f"  {react_label}エントリー({entry_date})→{hold_label}決済({exit_date}): "
                      f"1306 {r*100:+.2f}% → 空売りグロス{gross*100:+.2f}% / コスト後{net*100:+.2f}%")
        if not printed_any:
            print("  [まだ判定不可] イベントが直近すぎて+5/+20営業日分のデータが揃っていない")
        print()

    print("=" * 100)
    print(f"集計: ベア(空売り)シミュレーションの損益(コスト後、往復{COST_ROUNDTRIP*10000:.0f}bps仮定)")
    print("=" * 100)
    for react_label in ["早耳(REACT+1)", "安全(REACT+2)"]:
        for hold_label in ["+5営業日", "+20営業日"]:
            key = f"{react_label}/{hold_label}"
            pnls = [t[key] for t in short_trades.values() if key in t]
            if not pnls:
                continue
            wins = sum(1 for p in pnls if p > 0)
            print(f"  {key}: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
                  f"/ 平均損益{pystats.mean(pnls)*100:+.2f}% / 中央値{pystats.median(pnls)*100:+.2f}% "
                  f"/ 合計(単純加算){sum(pnls)*100:+.1f}%")

    print("\n個別イベント一覧(早耳+20営業日、良い順):")
    ranked = sorted(short_trades.items(), key=lambda kv: kv[1].get("早耳(REACT+1)/+20営業日", 0), reverse=True)
    for date, trades in ranked:
        v = trades.get("早耳(REACT+1)/+20営業日")
        if v is not None:
            name = next(e["name"] for e in down_events if e["date"] == date)
            print(f"  {v*100:+7.2f}%  {date}  {name}")

    print("\n注意: n=十数件・多重検定なし・記述的検証(統計的検定ではない)。")
    print("市場全体を揺るがす単発ショック(1日で急落するVaRショック・地震等)は、その日のうちに")
    print("下落の大半が起きてしまうため、翌営業日以降の空売りエントリーでは既に手遅れになりやすい")
    print("(これは弱点ではなく『後追いでは稼げない』という設計上の想定通りの結果)。")


if __name__ == "__main__":
    main()
