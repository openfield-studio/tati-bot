#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
実際のトレーダーが使う3つの手法の検証(一目均衡表・ボリンジャーバンド・月末月初効果)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

学術論文ベースのアノマリーではなく、実務のトレーダーが実際に使っている
テクニカル手法3つを検証する(stock_signal_lab.pyと同じ枠組み、東証プライム
全銘柄・チェックポイント方式):

  1. 一目均衡表の雲抜け(Ichimoku Cloud Breakout): 日本人(細田悟一氏)考案で
     日本の個人トレーダーに特に人気。株価が雲(先行スパンA・Bの間)を上抜けたら
     「上昇トレンド入り」のシグナルとされる。
  2. ボリンジャーバンド逆張り: 20日移動平均±2標準偏差の下限バンドにタッチしたら
     「売られすぎ、反発が近い」とされる(平均回帰トレーダーに広く使われる)。
  3. 月末月初効果(Turn-of-month effect): 月末4営業日+月初3営業日のリターンが
     他の日より高いというカレンダー効果。海外の実証研究では日本市場で特に
     強い効果(月間リターンの139%をこの期間だけで稼ぐ)が報告されている。

使い方: python trader_methods_lab.py --prime
"""
from __future__ import annotations
import csv
import statistics as pystats
import sys
from collections import defaultdict

import yfinance as yf

TENKAN, KIJUN, SENKOU_B = 9, 26, 52
CLOUD_SHIFT = 26
BB_WINDOW, BB_STD = 20, 2.0
FORWARD_DAYS = [20, 60]
TOM_END_DAYS = 4   # 月末最後の4営業日
TOM_START_DAYS = 3  # 月初最初の3営業日


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def rolling_mid(highs, lows, i, window):
    if i - window + 1 < 0:
        return None
    h = max(highs[i - window + 1:i + 1])
    l = min(lows[i - window + 1:i + 1])
    return (h + l) / 2


def analyze_stock(code: str, dates):
    try:
        df = yf.Ticker(f"{code}.T").history(period="3y", interval="1d")
    except Exception:
        return None
    df = df.dropna(subset=["Close", "High", "Low"])  # NaN/inf混入銘柄への対策
    if len(df) < SENKOU_B + CLOUD_SHIFT + max(FORWARD_DAYS) + 10:
        return None

    closes = df["Close"].tolist()
    highs = df["High"].tolist()
    lows = df["Low"].tolist()
    idx_dates = df.index
    n = len(closes)
    import math
    if any(not math.isfinite(x) for x in closes + highs + lows):
        return None  # inf/nan混入銘柄はスキップ(データ品質異常)

    # --- 一目均衡表: 先行スパンA・Bを計算し、CLOUD_SHIFT日先にずらす ---
    span_a_raw = [None] * n
    span_b_raw = [None] * n
    for i in range(n):
        tenkan = rolling_mid(highs, lows, i, TENKAN)
        kijun = rolling_mid(highs, lows, i, KIJUN)
        if tenkan is not None and kijun is not None:
            span_a_raw[i] = (tenkan + kijun) / 2
        span_b_raw[i] = rolling_mid(highs, lows, i, SENKOU_B)

    cloud_top = [None] * n  # 現在の雲の上限(CLOUD_SHIFT日前に計算された値)
    for i in range(n):
        src = i - CLOUD_SHIFT
        if src >= 0 and span_a_raw[src] is not None and span_b_raw[src] is not None:
            cloud_top[i] = max(span_a_raw[src], span_b_raw[src])

    # --- ボリンジャーバンド下限 ---
    bb_lower = [None] * n
    for i in range(BB_WINDOW - 1, n):
        window = closes[i - BB_WINDOW + 1:i + 1]
        mean = sum(window) / BB_WINDOW
        std = pystats.pstdev(window)
        bb_lower[i] = mean - BB_STD * std

    events = defaultdict(list)
    start = max(SENKOU_B + CLOUD_SHIFT, BB_WINDOW)
    for i in range(start, n - max(FORWARD_DAYS)):
        if cloud_top[i - 1] is not None and cloud_top[i] is not None:
            if closes[i - 1] <= cloud_top[i - 1] and closes[i] > cloud_top[i]:
                events["ichimoku_breakout"].append(i)
        if bb_lower[i] is not None and closes[i] <= bb_lower[i]:
            events["bb_lower_touch"].append(i)

    result = {}
    for name, idxs in events.items():
        for fd in FORWARD_DAYS:
            rets = [closes[i + fd] / closes[i] - 1 for i in idxs if i + fd < n]
            result.setdefault(name, {})[fd] = rets

    baseline = {}
    for fd in FORWARD_DAYS:
        rets = [closes[i + fd] / closes[i] - 1 for i in range(start, n - fd)]
        baseline[fd] = rets

    # --- 月末月初効果: 日次リターンをTOM窓/それ以外に分類 ---
    daily_rets_by_month_flag = {"tom": [], "other": []}
    # 月ごとに営業日をグルーピングし、月末側/月初側を判定
    month_key = lambda d: (d.year, d.month)
    groups = defaultdict(list)
    for i, d in enumerate(idx_dates):
        groups[month_key(d.to_pydatetime())].append(i)
    is_tom_day = [False] * n
    sorted_months = sorted(groups.keys())
    for mi, mk in enumerate(sorted_months):
        idxs_in_month = groups[mk]
        for j in idxs_in_month[-TOM_END_DAYS:]:
            is_tom_day[j] = True
        if mi + 1 < len(sorted_months):
            next_idxs = groups[sorted_months[mi + 1]]
            for j in next_idxs[:TOM_START_DAYS]:
                is_tom_day[j] = True
    for i in range(1, n):
        r = closes[i] / closes[i - 1] - 1
        daily_rets_by_month_flag["tom" if is_tom_day[i] else "other"].append(r)

    return result, baseline, daily_rets_by_month_flag


CHECKPOINT_EVERY = 25


def main() -> None:
    import json
    import os

    universe = load_universe()
    tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"trader_methods_checkpoint_{tag}.json"
    cache_path = f"trader_methods_cache_{tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        state = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            state = json.load(open(checkpoint_path, encoding="utf-8"))
            print(f"チェックポイントから再開: {len(state['done_codes'])}銘柄処理済み"
                  f"(有効{state['processed']})")
        else:
            state = {"signal_rets": {}, "baseline_rets": {}, "tom_rets": [], "other_rets": [],
                      "done_codes": [], "processed": 0}

        done_codes = set(state["done_codes"])
        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{tag}、残り{len(todo)}/{len(universe)}銘柄のシグナル検証中...")
        for i, (code, name) in enumerate(todo, 1):
            out = analyze_stock(code, None)
            if out:
                signals, baseline, tom_flag = out
                for sig_name, fd_dict in signals.items():
                    state["signal_rets"].setdefault(sig_name, {})
                    for fd, rets in fd_dict.items():
                        state["signal_rets"][sig_name].setdefault(str(fd), [])
                        state["signal_rets"][sig_name][str(fd)] += rets
                for fd, rets in baseline.items():
                    state["baseline_rets"].setdefault(str(fd), [])
                    state["baseline_rets"][str(fd)] += rets
                state["tom_rets"] += tom_flag["tom"]
                state["other_rets"] += tom_flag["other"]
                state["processed"] += 1
            state["done_codes"].append(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump(state, open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(有効{state['processed']}、チェックポイント保存)...")

        json.dump(state, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    processed = state["processed"]
    all_signal_rets = {name: {int(fd): rets for fd, rets in fd_dict.items()}
                        for name, fd_dict in state["signal_rets"].items()}
    all_baseline_rets = {int(fd): rets for fd, rets in state["baseline_rets"].items()}
    tom_rets = state["tom_rets"]
    other_rets = state["other_rets"]

    print(f"\n有効データが取れた銘柄数: {processed}/{len(universe)}\n")

    RET_CAP = 2.0  # |r|>200%は外れ値(データ不具合含む)として除外

    def cap(rets):
        return [r for r in rets if abs(r) <= RET_CAP]

    print("=" * 70)
    print("=== 1. 一目均衡表の雲抜け(Ichimoku Cloud Breakout) ===")
    print("=" * 70)
    print("=== 2. ボリンジャーバンド下限タッチ(逆張り) ===")
    SIGNAL_LABELS = {
        "ichimoku_breakout": "一目均衡表: 雲を上抜け(上昇トレンド入りシグナル)",
        "bb_lower_touch": "ボリンジャーバンド下限タッチ(売られすぎ、反発期待)",
    }
    for sig_name, label in SIGNAL_LABELS.items():
        fd_dict = all_signal_rets.get(sig_name, {})
        if not fd_dict:
            print(f"\n[{label}] データなし")
            continue
        print(f"\n[{label}]")
        for fd in FORWARD_DAYS:
            rets = cap(fd_dict.get(fd, []))
            base_rets = cap(all_baseline_rets[fd])
            if not rets or not base_rets:
                continue
            base = pystats.mean(base_rets)
            avg = pystats.mean(rets)
            med = pystats.median(rets)
            print(f"  {fd}営業日後: 平均{avg*100:+.2f}%(中央値{med*100:+.2f}%, n={len(rets)}) "
                  f"/ ベースライン{base*100:+.2f}%(n={len(base_rets)}) / 差{((avg-base)*100):+.2f}pt")

    print("\n" + "=" * 70)
    print("=== 3. 月末月初効果(Turn-of-month effect) ===")
    print("=" * 70)
    tom_rets_capped = cap(tom_rets)
    other_rets_capped = cap(other_rets)
    if tom_rets_capped and other_rets_capped:
        tom_avg = pystats.mean(tom_rets_capped)
        other_avg = pystats.mean(other_rets_capped)
        print(f"月末月初の窓(月末{TOM_END_DAYS}営業日+月初{TOM_START_DAYS}営業日)の日次平均リターン: "
              f"{tom_avg*100:+.4f}%(n={len(tom_rets_capped)}, 除外{len(tom_rets)-len(tom_rets_capped)}件)")
        print(f"それ以外の日の日次平均リターン: {other_avg*100:+.4f}%"
              f"(n={len(other_rets_capped)}, 除外{len(other_rets)-len(other_rets_capped)}件)")
        print(f"差: {((tom_avg-other_avg)*100):+.4f}pt/日"
              f"(プラスなら月末月初効果あり)")
        # 月換算(営業日約20日中、TOM窓は7日)での寄与度
        tom_days_per_month = TOM_END_DAYS + TOM_START_DAYS
        monthly_from_tom = tom_avg * tom_days_per_month
        monthly_from_other = other_avg * (21 - tom_days_per_month)
        monthly_total = monthly_from_tom + monthly_from_other
        if monthly_total != 0:
            print(f"月間リターンに占めるTOM窓の寄与(概算): "
                  f"{monthly_from_tom*100:+.3f}pt / 月合計{monthly_total*100:+.3f}pt "
                  f"({monthly_from_tom/monthly_total*100:.0f}%)")
    else:
        print("データ不足")

    print("\n注意: 東証プライム全銘柄・過去3年の日足データでの検証。生存バイアス・"
          "DSR等の多重検定補正は未実施。")


if __name__ == "__main__":
    main()
