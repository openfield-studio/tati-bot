#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
季節性・カレンダー効果2つの検証(権利付き最終日/権利落ち日、Sell in May)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

trader_methods_lab.py(一目均衡表・ボリンジャーバンド・月末月初効果)に続き、
「世界中から徹底的に探して特に日本で」を受けて見つけた2つのカレンダー効果を
東証プライム全銘柄で検証する:

  1. 権利付き最終日/権利落ち日効果: 日本特有の慣行(配当・株主優待の権利確定)に
     由来するアノマリー。既存の実証(systemtrade-kabu.com、東証4,083銘柄・
     45万件)では「権利付き最終日は勝率60.7%で上昇、3月末の権利落ち日は
     平均-1.53%下落、12月末の権利落ち日は逆に+0.709%」と報告されている。
     yfinanceの配当データ(.dividends、権利落ち日そのもの)を使って再現する。
  2. Sell in May効果: 11月〜4月(強気とされる半年)と5月〜10月(弱気とされる
     半年)のリターンを比較する、世界的に有名な季節性アノマリー。
     trader_methods_lab.pyの月末月初効果とは別物(半年サイクル)。

使い方: python seasonal_effects_lab.py --prime
"""
from __future__ import annotations
import csv
import json
import os
import sys
import statistics as pystats
from collections import defaultdict

import yfinance as yf

CHECKPOINT_EVERY = 25
RET_CAP = 2.0


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def analyze_stock(code: str) -> dict | None:
    try:
        ticker = yf.Ticker(f"{code}.T")
        df = ticker.history(period="7y", interval="1d")
        divs = ticker.dividends
    except Exception:
        return None
    df = df.dropna(subset=["Close"])
    if len(df) < 300:
        return None
    closes = df["Close"].tolist()
    dates = [d.date() for d in df.index]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n = len(closes)

    result = {"cum_day_rets": [], "ex_day_rets_by_month": defaultdict(list),
              "sell_in_may": [], "buy_nov_apr": []}

    # --- 1. 権利付き最終日/権利落ち日 ---
    if divs is not None and len(divs) > 0:
        for div_date, _ in divs.items():
            d = div_date.date()
            idx = date_to_idx.get(d)
            if idx is None:
                # 前後3日以内で最も近い営業日を探索(休日等でズレる場合の対策)
                best = None
                for i2, dt2 in enumerate(dates):
                    diff = abs((dt2 - d).days)
                    if diff <= 3 and (best is None or diff < best[1]):
                        best = (i2, diff)
                idx = best[0] if best else None
            if idx is None or idx < 2 or idx >= n:
                continue
            cum_day_ret = closes[idx - 1] / closes[idx - 2] - 1  # 権利付き最終日の値動き
            ex_day_ret = closes[idx] / closes[idx - 1] - 1        # 権利落ち日の値動き
            result["cum_day_rets"].append(cum_day_ret)
            result["ex_day_rets_by_month"][dates[idx].month].append(ex_day_ret)

    # --- 2. Sell in May ---
    for i in range(1, n):
        r = closes[i] / closes[i - 1] - 1
        month = dates[i].month
        if 5 <= month <= 10:
            result["sell_in_may"].append(r)
        else:
            result["buy_nov_apr"].append(r)

    return result


def main() -> None:
    universe = load_universe()
    tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"seasonal_checkpoint_{tag}.json"
    cache_path = f"seasonal_cache_{tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        state = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            state = json.load(open(checkpoint_path, encoding="utf-8"))
            print(f"チェックポイントから再開: {len(state['done_codes'])}銘柄処理済み")
        else:
            state = {"cum_day_rets": [], "ex_day_rets_by_month": {}, "sell_in_may": [],
                      "buy_nov_apr": [], "done_codes": [], "processed": 0}

        done_codes = set(state["done_codes"])
        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{tag}、残り{len(todo)}/{len(universe)}銘柄を処理中...")
        for i, (code, name) in enumerate(todo, 1):
            r = analyze_stock(code)
            if r:
                state["cum_day_rets"] += r["cum_day_rets"]
                for month, rets in r["ex_day_rets_by_month"].items():
                    state["ex_day_rets_by_month"].setdefault(str(month), [])
                    state["ex_day_rets_by_month"][str(month)] += rets
                state["sell_in_may"] += r["sell_in_may"]
                state["buy_nov_apr"] += r["buy_nov_apr"]
                state["processed"] += 1
            state["done_codes"].append(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump(state, open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(有効{state['processed']}、チェックポイント保存)...")

        json.dump(state, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    def cap(rets):
        return [r for r in rets if abs(r) <= RET_CAP]

    print(f"\n有効銘柄数: {state['processed']}/{len(universe)}\n")

    print("=" * 70)
    print("=== 1. 権利付き最終日/権利落ち日効果 ===")
    print("=" * 70)
    cum_rets = cap(state["cum_day_rets"])
    if cum_rets:
        win_rate = sum(1 for r in cum_rets if r > 0) / len(cum_rets) * 100
        print(f"権利付き最終日の値動き: 平均{pystats.mean(cum_rets)*100:+.3f}%"
              f"(中央値{pystats.median(cum_rets)*100:+.3f}%, 勝率{win_rate:.1f}%, n={len(cum_rets)})")
    print("\n権利落ち日の値動き(月別):")
    for month in sorted(state["ex_day_rets_by_month"], key=lambda m: int(m)):
        rets = cap(state["ex_day_rets_by_month"][month])
        if len(rets) < 30:
            continue
        win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
        print(f"  {int(month)}月: 平均{pystats.mean(rets)*100:+.3f}%"
              f"(中央値{pystats.median(rets)*100:+.3f}%, 勝率{win_rate:.1f}%, n={len(rets)})")

    print("\n" + "=" * 70)
    print("=== 2. Sell in May効果(5〜10月 vs 11〜4月) ===")
    print("=" * 70)
    may_rets = cap(state["sell_in_may"])
    nov_rets = cap(state["buy_nov_apr"])
    if may_rets and nov_rets:
        may_avg = pystats.mean(may_rets)
        nov_avg = pystats.mean(nov_rets)
        print(f"5〜10月の日次平均リターン: {may_avg*100:+.4f}%(n={len(may_rets)})")
        print(f"11〜4月の日次平均リターン: {nov_avg*100:+.4f}%(n={len(nov_rets)})")
        print(f"差: {(nov_avg-may_avg)*100:+.4f}pt/日(プラスなら11〜4月の方が良い=理論通り)")
        # 半年(約125営業日)換算
        half_year_days = 125
        may_half = (1 + may_avg) ** half_year_days - 1
        nov_half = (1 + nov_avg) ** half_year_days - 1
        print(f"半年複利換算: 5〜10月{may_half*100:+.2f}% / 11〜4月{nov_half*100:+.2f}% / "
              f"差{(nov_half-may_half)*100:+.2f}pt")

    print("\n注意: 東証プライム全銘柄での検証。生存バイアス・DSR等の多重検定補正は未実施。")


if __name__ == "__main__":
    main()
