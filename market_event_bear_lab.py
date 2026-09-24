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


def stoploss_exit(closes: dict[dt.date, float], entry_date: dt.date, stop_pct: float | None,
                   max_days: int = 20) -> tuple[dt.date, float, bool] | None:
    """entry_dateの終値をエントリー価格とし、翌営業日以降を日次で監視する。
    価格がentry_priceからstop_pct以上上昇(＝空売りの損失がstop_pct以上)したら
    その日の終値で即カバー(損切り)。stop_pct=Noneなら損切りなし(固定期間保有)。
    どちらでも上限max_days営業日で強制手仕舞い。戻り値: (手仕舞い日, 生リターン, 損切りで終わったか)。"""
    keys = sorted(d for d in closes if d >= entry_date)
    if len(keys) < 2:
        return None
    entry_price = closes[keys[0]]
    last_idx = min(max_days, len(keys) - 1)
    if last_idx < 1:
        return None
    for i in range(1, last_idx + 1):
        d = keys[i]
        r = closes[d] / entry_price - 1
        if stop_pct is not None and r >= stop_pct:
            return d, r, True
    d = keys[last_idx]
    r = closes[d] / entry_price - 1
    return d, r, False


def recent_volatility(closes: dict[dt.date, float], before_date: dt.date, window: int = 20) -> float | None:
    """before_date(エントリー日)より前のwindow営業日の日次リターンの標準偏差。
    ★先読み注意★ エントリー日より前のデータのみ使う(未来のボラは使わない)。"""
    keys = sorted(d for d in closes if d < before_date)
    if len(keys) < window + 1:
        return None
    recent = keys[-(window + 1):]
    rets = [closes[recent[i + 1]] / closes[recent[i]] - 1 for i in range(len(recent) - 1)]
    return pystats.stdev(rets) if len(rets) >= 2 else None


def vol_trailing_stop_exit(closes: dict[dt.date, float], entry_date: dt.date, k: float, max_days: int = 20):
    """固定%ではなく、エントリー時点の直近ボラ(sigma)のk倍を戻したら利確するトレーリングストップ。
    エントリー後の最安値(空売りにとって最も有利な点)を追跡し、そこからk*sigma分反発したら決済。
    戻り値: (手仕舞い日, 生リターン, 利確/期限, 手仕舞いまでの営業日数)。"""
    sigma = recent_volatility(closes, entry_date, window=20)
    if sigma is None or sigma <= 0:
        return None
    keys = sorted(d for d in closes if d >= entry_date)
    last_idx = min(max_days, len(keys) - 1)
    if last_idx < 1:
        return None
    entry_price = closes[keys[0]]
    trough_price = entry_price
    for i in range(1, last_idx + 1):
        d = keys[i]
        price = closes[d]
        trough_price = min(trough_price, price)
        if price >= trough_price * (1 + k * sigma):
            return d, price / entry_price - 1, "トレーリング利確", i
    d = keys[last_idx]
    return d, closes[d] / entry_price - 1, "期限", last_idx


def reversal_exit(closes: dict[dt.date, float], entry_date: dt.date,
                   confirm_up_days: int, max_days: int = 20):
    """固定%ではなく『値動きの反転』で利確する適応的ルール。前日比で上昇した日が
    confirm_up_days日連続したら、下落の勢い(加速度)が止まった=反発開始と判断してその日に決済。
    連続しなければmax_days営業日で強制手仕舞い。戻り値: (手仕舞い日, 生リターン, 反転検知/期限, 手仕舞いまでの営業日数)。"""
    keys = sorted(d for d in closes if d >= entry_date)
    last_idx = min(max_days, len(keys) - 1)
    if last_idx < 1:
        return None
    entry_price = closes[keys[0]]
    prev_price = entry_price
    up_streak = 0
    for i in range(1, last_idx + 1):
        d = keys[i]
        price = closes[d]
        up_streak = up_streak + 1 if price > prev_price else 0
        if up_streak >= confirm_up_days:
            return d, price / entry_price - 1, "反転検知", i
        prev_price = price
    d = keys[last_idx]
    return d, closes[d] / entry_price - 1, "期限", last_idx


def path_profile(closes: dict[dt.date, float], entry_date: dt.date, max_days: int = 20):
    """entry_dateから最大max_days営業日、日次で空売りの累積損益(コスト前)を追跡し、
    各日の(日数, 損益)のリストを返す。"""
    keys = sorted(d for d in closes if d >= entry_date)
    last_idx = min(max_days, len(keys) - 1)
    if last_idx < 1:
        return []
    entry_price = closes[keys[0]]
    return [(i, -(closes[keys[i]] / entry_price - 1)) for i in range(1, last_idx + 1)]


def takeprofit_stoploss_exit(closes: dict[dt.date, float], entry_date: dt.date,
                              take_profit_pct: float | None, stop_pct: float | None,
                              max_days: int = 20):
    """空売りの益がtake_profit_pct以上出たら即利確、損がstop_pct以上出たら即損切り。
    どちらもNoneなら判定せず、最大max_days営業日で強制手仕舞い。"""
    keys = sorted(d for d in closes if d >= entry_date)
    last_idx = min(max_days, len(keys) - 1)
    if last_idx < 1:
        return None
    entry_price = closes[keys[0]]
    for i in range(1, last_idx + 1):
        r = closes[keys[i]] / entry_price - 1  # >0は空売りの損、<0は空売りの益
        if take_profit_pct is not None and -r >= take_profit_pct:
            return keys[i], r, "利確"
        if stop_pct is not None and r >= stop_pct:
            return keys[i], r, "損切り"
    d = keys[last_idx]
    return d, closes[d] / entry_price - 1, "期限"


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
        react_options = [
            ("同日(SAME-DAY、当日終値で反応できた場合)", anchor[0]),
            ("早耳(REACT+1)", first_trading_day_after(closes, d0, skip=0)),
            ("安全(REACT+2)", first_trading_day_after(closes, d0, skip=1)),
        ]
        for react_label, entry_date in react_options:
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
    for react_label in ["同日(SAME-DAY、当日終値で反応できた場合)", "早耳(REACT+1)", "安全(REACT+2)"]:
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

    # ---- 損切り(ストップロス)アルゴリズムの検証 ----
    print("\n" + "=" * 100)
    print("追加検証: 固定20日保有 vs 損切りルール(早耳REACT+1エントリー、最大20営業日)")
    print("=" * 100)
    print("損切りルール: エントリー価格からstop_pct以上『上昇』(＝空売りが損失)したら即カバーし、")
    print("それ以上損を広げない。stop_pctに達しなければ最大20営業日で強制手仕舞い(固定保有と同じ終点)。")
    print("★重要な限界★ 損切り判定は日次終値ベース。オーバーナイトのギャップで一晩にstop_pctを")
    print("超えて飛んだ場合、『その日の終値』時点でカバーするしかなく、ギャップそのものは避けられない")
    print("(項目85で確認した『急落も反発も夜間ギャップが主因』という制約は損切りでも解消しない)。\n")

    for stop_pct in [None, 0.08, 0.05, 0.03, 0.02]:
        label = "損切りなし(固定20日)" if stop_pct is None else f"損切り{stop_pct*100:.0f}%"
        pnls, stopped_count, hold_days = [], 0, []
        for ev in down_events:
            d0 = dt.date.fromisoformat(ev["date"])
            if price_on_or_before(closes, d0) is None:
                continue  # d0がデータ範囲(2009-01-05〜)より前 → スキップ(先の集計と同じ扱い)
            entry_date = first_trading_day_after(closes, d0, skip=0)
            if entry_date is None:
                continue
            result = stoploss_exit(closes, entry_date, stop_pct, max_days=20)
            if result is None:
                continue
            exit_date, r, was_stopped = result
            net = -r - COST_ROUNDTRIP
            pnls.append(net)
            if was_stopped:
                stopped_count += 1
            hold_days.append((exit_date - entry_date).days)
        if not pnls:
            continue
        wins = sum(1 for p in pnls if p > 0)
        print(f"  {label}: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
              f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 中央値{pystats.median(pnls)*100:+.2f}% "
              f"/ 最悪{min(pnls)*100:+.2f}% / 合計{sum(pnls)*100:+.1f}% / 損切り発動{stopped_count}件")

    # ---- 「損切りが遅い」のか「利確が遅い」のか: 20日間の途中最大益 vs 最終結果 ----
    print("\n" + "=" * 100)
    print("追加検証2: 20営業日の『途中の最大益(コスト前)』 vs 『20日目の最終結果』(早耳REACT+1)")
    print("=" * 100)
    give_backs = []
    for ev in down_events:
        d0 = dt.date.fromisoformat(ev["date"])
        if price_on_or_before(closes, d0) is None:
            continue
        entry_date = first_trading_day_after(closes, d0, skip=0)
        if entry_date is None:
            continue
        path = path_profile(closes, entry_date, max_days=20)
        if len(path) < 20:
            continue
        best_day, best_profit = max(path, key=lambda x: x[1])
        final_profit = path[-1][1]
        give_back = best_profit - final_profit  # 途中の最良点からどれだけ吐き出したか
        give_backs.append(give_back)
        print(f"  {ev['date']} {ev['name']}: 途中最大{best_profit*100:+.2f}%(day{best_day}) "
              f"→ 20日目{final_profit*100:+.2f}%  差(吐き出し){give_back*100:+.2f}%")
    if give_backs:
        print(f"\n→ 平均の吐き出し幅: {pystats.mean(give_backs)*100:+.2f}pt "
              f"(プラスなら『途中で利確していれば20日目より良かった』を意味する)")

    print("\n追加検証3.6: ボラティリティ基準のトレーリングストップ利確")
    print("(固定%ではなく、エントリー時点の直近20日ボラのk倍を最安値から戻したら利確)")
    for k in [1.0, 1.5, 2.0, 3.0]:
        pnls, exit_days, sigmas = [], [], []
        for ev in down_events:
            d0 = dt.date.fromisoformat(ev["date"])
            if price_on_or_before(closes, d0) is None:
                continue
            entry_date = first_trading_day_after(closes, d0, skip=0)
            if entry_date is None:
                continue
            result = vol_trailing_stop_exit(closes, entry_date, k, max_days=20)
            if result is None:
                continue
            _, r, reason, days = result
            net = -r - COST_ROUNDTRIP
            pnls.append(net)
            exit_days.append(days)
        if not pnls:
            continue
        wins = sum(1 for p in pnls if p > 0)
        print(f"  k={k}: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
              f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 中央値{pystats.median(pnls)*100:+.2f}% "
              f"/ 合計{sum(pnls)*100:+.1f}% / 平均保有{pystats.mean(exit_days):.1f}営業日")

    print("\n追加検証3.5: 反転検知ルール(固定%ではなく『前日比プラスの日がN日続いたら利確』)")
    print("早耳REACT+1エントリー、最大20営業日。値動きの勢いが止まった(加速度がプラスに転じた)")
    print("タイミングを固定閾値の代わりに使う、というアイデアの検証。")
    for confirm in [1, 2, 3]:
        pnls, exit_days = [], []
        for ev in down_events:
            d0 = dt.date.fromisoformat(ev["date"])
            if price_on_or_before(closes, d0) is None:
                continue
            entry_date = first_trading_day_after(closes, d0, skip=0)
            if entry_date is None:
                continue
            result = reversal_exit(closes, entry_date, confirm, max_days=20)
            if result is None:
                continue
            _, r, reason, days = result
            net = -r - COST_ROUNDTRIP
            pnls.append(net)
            exit_days.append(days)
        if not pnls:
            continue
        wins = sum(1 for p in pnls if p > 0)
        print(f"  上昇{confirm}日連続で利確: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
              f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 中央値{pystats.median(pnls)*100:+.2f}% "
              f"/ 合計{sum(pnls)*100:+.1f}% / 平均保有{pystats.mean(exit_days):.1f}営業日")

    print("\n追加検証3: 利確ルール(早耳REACT+1、損切りは併用せず利確のみ、最大20営業日)")
    print("★注意★ 閾値を細かく振って一番良い数字を探す行為自体が多重検定(過学習)リスクを孕む。")
    print("n=15の小標本でパラメータ探索した参考値であり、これ単体でGO判定はしない。")
    for tp_pct in [None, 0.08, 0.05, 0.03, 0.02, 0.01, 0.005]:
        label = "利確なし(固定20日)" if tp_pct is None else f"利確{tp_pct*100:.0f}%"
        pnls, tp_count = [], 0
        for ev in down_events:
            d0 = dt.date.fromisoformat(ev["date"])
            if price_on_or_before(closes, d0) is None:
                continue
            entry_date = first_trading_day_after(closes, d0, skip=0)
            if entry_date is None:
                continue
            result = takeprofit_stoploss_exit(closes, entry_date, tp_pct, None, max_days=20)
            if result is None:
                continue
            _, r, reason = result
            net = -r - COST_ROUNDTRIP
            pnls.append(net)
            if reason == "利確":
                tp_count += 1
        if not pnls:
            continue
        wins = sum(1 for p in pnls if p > 0)
        print(f"  {label}: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
              f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 中央値{pystats.median(pnls)*100:+.2f}% "
              f"/ 合計{sum(pnls)*100:+.1f}% / 利確発動{tp_count}件")


if __name__ == "__main__":
    main()
