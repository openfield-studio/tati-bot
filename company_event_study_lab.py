#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
個別企業イベント(company_events.json)の実際の株価反応 検証ラボ
=====================================================================
※本体には組み込まない。「実際のニュースで動いたらリターンはどうなったか(ベア/空売りも
含めて)」の検証。

company_events.jsonに載せた不正・データ改ざん・需要ショックの各事象について、
発表日前後の実際の株価と、1306(TOPIX ETF)を市場ベンチマークとした超過リターンを
yfinanceで取得して確認する。予測モデルではなく事後の記述的検証(何が起きたかの確認)。

★分割の断崖チェック★ fetch_yf.py/jpx_investor_flow_lab.pyと同じ「遡って係数補正」方式。
auto_adjust=Trueでも稀に未調整の分割が混入する実例(2026年1306の1:10分割)があるため。

★ベア(空売り)シミュレーション★ direction="down"のイベントについて、ニュース当日(d0)に
反応して即エントリーするのは先読み(多くは取引時間外の発表)になるため、jpx_investor_flow_lab.py
と同じ「早耳(REACT+1、d0の次の営業日)/安全(REACT+2、さらに1日空ける)」の2パターンで
空売りエントリーし、+5営業日/+20営業日で決済した場合の損益(グロス・コスト後)を計算する。
コストは往復50bpsの仮置き(信用売りの貸株料+スプレッドの粗い見積り、要検証)。
**個別銘柄が実際に貸株可能(品貸料が付かず借りられる)かは未確認**(規制銘柄・貸株ゼロの
可能性がある。ルール9に準拠しここでは断定しない)。

使い方: python company_event_study_lab.py
"""
from __future__ import annotations
import datetime as dt
import json
import statistics as pystats

import yfinance as yf

EVENTS_FILE = "company_events.json"
BENCH_TICKER = "1306.T"
COST_ROUNDTRIP = 0.005  # 空売り往復コストの仮置き(貸株料+スプレッド、要検証)

# ticker未記載(複数銘柄にまたがる)イベント用のバスケット定義
BASKETS = {
    "タイ大洪水によるサプライチェーン寸断": ["7267.T", "6758.T", "7203.T"],  # ホンダ/ソニー/トヨタ
    "Apple業績警告(中国iPhone需要減)": ["6981.T", "6762.T", "6770.T"],  # 村田/TDK/アルプスアルパイン
    "コロナ後の巣ごもり需要・車載半導体不足による需要急増": ["8035.T", "6857.T", "6723.T"],  # 東京エレクトロン/アドバンテスト/ルネサス
    "生成AI・GPU需要ブームによる半導体関連株上昇": ["8035.T", "6857.T", "9984.T"],  # 東京エレクトロン/アドバンテスト/SoftBankG
}

_price_cache: dict[str, dict[dt.date, float]] = {}


def fetch_split_safe(ticker: str) -> dict[dt.date, float]:
    """fetch_yf.py/jpx_investor_flow_lab.pyと同じ方式: auto_adjust済みでも残る
    未調整分割の断崖を検出し、スキップではなく遡って係数補正する。"""
    if ticker in _price_cache:
        return _price_cache[ticker]
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
    result = dict(zip(dates, px_list))
    _price_cache[ticker] = result
    return result


def price_on_or_before(closes: dict[dt.date, float], target: dt.date) -> tuple[dt.date, float] | None:
    keys = sorted(d for d in closes if d <= target)
    if not keys:
        return None
    return keys[-1], closes[keys[-1]]


def trading_day_offset(closes: dict[dt.date, float], anchor: dt.date, n: int) -> tuple[dt.date, float] | None:
    """anchor以降の営業日リストでn番目(0=anchor当日以降の最初の日)の日付・価格。"""
    keys = sorted(d for d in closes if d >= anchor)
    if len(keys) <= n:
        return None
    return keys[n], closes[keys[n]]


def first_trading_day_after(closes: dict[dt.date, float], d0: dt.date, skip: int = 0) -> dt.date | None:
    """d0より後(d0を含まない)の最初の営業日。skip=1なら、さらにもう1日後(REACT+2用)。"""
    keys = sorted(d for d in closes if d > d0)
    if len(keys) <= skip:
        return None
    return keys[skip]


def basket_window_return(tickers: list[str], bench: dict[dt.date, float],
                          entry_date: dt.date, n_days: int) -> tuple[float, float] | None:
    """entry_date(営業日)からbenchのカレンダーでn_days後の営業日まで、
    バスケット平均の生リターンとbenchリターンを返す。"""
    target = trading_day_offset(bench, entry_date, n_days)
    if target is None:
        return None
    d_target = target[0]
    r_bench = bench[d_target] / bench[entry_date] - 1
    rets = []
    for t in tickers:
        closes = fetch_split_safe(t)
        p0 = price_on_or_before(closes, entry_date)
        p1 = price_on_or_before(closes, d_target)
        if p0 and p1 and p0[1] > 0 and p1[0] >= p0[0]:
            rets.append(p1[1] / p0[1] - 1)
    if not rets:
        return None
    return pystats.mean(rets), r_bench


def main():
    events = json.load(open(EVENTS_FILE, encoding="utf-8"))
    bench = fetch_split_safe(BENCH_TICKER)
    print(f"ベンチマーク(1306)データ範囲: {min(bench)}〜{max(bench)}\n")

    rows = []
    short_trades: dict[str, dict[str, float]] = {}
    for ev in events:
        d0 = dt.date.fromisoformat(ev["date"])
        tickers = [ev["ticker"]] if ev.get("ticker") else BASKETS.get(ev["name"])
        if not tickers:
            print(f"[スキップ] {ev['date']} {ev['name']}: 対応銘柄が特定できない")
            continue

        anchor = price_on_or_before(bench, d0)
        if anchor is None:
            print(f"[スキップ] {ev['date']} {ev['name']}: 1306側にデータが無い期間")
            continue
        d_minus1 = anchor[0]

        results = {}
        for label, n_days in [("当日(t0)", 1), ("t+5営業日", 6), ("t+20営業日", 21)]:
            offs = trading_day_offset(bench, d_minus1, n_days)
            if offs is None:
                continue
            d_target = offs[0]
            r_bench = bench[d_target] / bench[d_minus1] - 1
            # 銘柄側(バスケット平均)も同じ日付ウィンドウで
            stock_rets = []
            for t in tickers:
                closes = fetch_split_safe(t)
                p_start = price_on_or_before(closes, d_minus1)
                p_end = price_on_or_before(closes, d_target)
                if p_start and p_end and p_start[1] > 0 and p_end[0] >= p_start[0]:
                    stock_rets.append(p_end[1] / p_start[1] - 1)
            if not stock_rets:
                continue
            r_stock = pystats.mean(stock_rets)
            results[label] = (r_stock, r_bench, r_stock - r_bench)

        if not results:
            print(f"[スキップ] {ev['date']} {ev['name']}: 価格データ不足")
            continue

        rows.append((ev, results))
        print("=" * 100)
        print(f"{ev['date']}  {ev['name']}  [{ev.get('company','')}]  想定方向:{ev['direction']}  信頼度:{ev['confidence']}")
        print(f"  対象: {', '.join(tickers)}")
        for label, (r_s, r_b, r_ex) in results.items():
            print(f"  {label}: 個別{r_s*100:+.2f}% / 1306(市場){r_b*100:+.2f}% / 超過{r_ex*100:+.2f}%")

        # ---- ベア(空売り)シミュレーション: downイベントのみ ----
        if ev["direction"] == "down":
            print("  --- ベア(空売り)シミュレーション(先読みなし、翌営業日以降にエントリー) ---")
            short_trades[ev["date"]] = {}
            for react_label, skip in [("早耳(REACT+1)", 0), ("安全(REACT+2)", 1)]:
                entry_date = first_trading_day_after(bench, d0, skip=skip)
                if entry_date is None:
                    continue
                for hold_label, n_days in [("+5営業日", 5), ("+20営業日", 20)]:
                    wr = basket_window_return(tickers, bench, entry_date, n_days)
                    if wr is None:
                        continue
                    r_stock, r_bench2 = wr
                    gross = -r_stock  # 空売りなので株価下落が利益
                    net = gross - COST_ROUNDTRIP
                    key = f"{react_label}/{hold_label}"
                    short_trades[ev["date"]][key] = net
                    print(f"    {react_label}エントリー({entry_date})→{hold_label}決済: "
                          f"個別{r_stock*100:+.2f}% → 空売りグロス{gross*100:+.2f}% / コスト後{net*100:+.2f}%")
        print()

    # ---- 集計 ----
    print("=" * 100)
    print("集計: 想定方向(direction)と実際のt+20営業日の超過リターンの符号が一致したか")
    print("=" * 100)
    hit, total = 0, 0
    for ev, results in rows:
        if "t+20営業日" not in results:
            continue
        _, _, r_ex = results["t+20営業日"]
        if ev["direction"] == "up" and r_ex > 0:
            hit += 1
        elif ev["direction"] == "down" and r_ex < 0:
            hit += 1
        elif ev["direction"] == "mixed":
            continue
        else:
            pass
        if ev["direction"] in ("up", "down"):
            total += 1
        mark = "○" if ((ev["direction"] == "up") == (r_ex > 0)) else "×"
        print(f"  {mark} {ev['date']} {ev['name']}: 想定{ev['direction']} / 実際の超過{r_ex*100:+.2f}%")
    if total:
        print(f"\n→ 想定方向と一致: {hit}/{total} ({hit/total*100:.0f}%)")

    print("\n" + "=" * 100)
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

    print("\n注意: n=十数件・多重検定なし・個別イベントの記述的確認(統計的検定ではない)。")
    print("バスケット銘柄は代表選定であり、その銘柄が実際にそのニュースをどれだけ強く受けたかは別途要検討。")
    print("空売りコストは往復50bpsの仮置き、個別銘柄の貸株可否(品貸料・規制)は未確認(ルール9に準拠、断定しない)。")


if __name__ == "__main__":
    main()
