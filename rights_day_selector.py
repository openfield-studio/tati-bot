#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
権利付き最終日イベントの銘柄候補選定(年2回イベント用)
=====================================================================
※本体には組み込まない。表示・候補提示のみ、自動発注はしない。

rights_day_stock_selection_lab.py(過去の成績で銘柄を選ぶのはノイズを拾う
だけと判明)を踏まえ、過去リターンではなく**流動性(出来高)と予算内で
買えるか**を基準に候補を選ぶ。

★重要な制約★
yfinanceの配当データ(.dividends)は「過去の実績」のみで、将来の正確な
権利確定日はまだ載っていない(発表され次第、直前にならないと反映されない)。
そのため、このスクリプトは「過去2〜3年、対象月(3月 or 9月)に配当実績がある
銘柄」を候補として抽出するだけで、**実際の権利付き最終日は別途ニュース等で
確認すること**(自動発注はしない前提のため、これで十分)。

使い方: python rights_day_selector.py --prime --month 9 --budget 500000 --n 5
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import os
import sys

import yfinance as yf

CHECKPOINT_EVERY = 25
LOOKBACK_YEARS = 3
MIN_YEARS_WITH_DIVIDEND = 2  # 過去3年中、最低何回その月に配当実績があれば「定例」とみなすか


def load_universe() -> list[tuple[str, str]]:
    with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
        return [(row["code"], row["name"]) for row in csv.DictReader(f)]


def check_stock(code: str, name: str, target_month: int, budget_per_position: float) -> dict | None:
    try:
        ticker = yf.Ticker(f"{code}.T")
        divs = ticker.dividends
        hist = ticker.history(period="3mo")
    except Exception:
        return None
    if divs is None or len(divs) == 0 or hist is None or hist.empty:
        return None

    this_year = dt.date.today().year
    years_with_div = set()
    for d, _ in divs.items():
        dd = d.date()
        if dd.month == target_month and dd.year >= this_year - LOOKBACK_YEARS:
            years_with_div.add(dd.year)
    if len(years_with_div) < MIN_YEARS_WITH_DIVIDEND:
        return None  # 対象月の配当実績が乏しい(定例的でない)銘柄は除外

    price = float(hist["Close"].iloc[-1])
    avg_volume = float(hist["Volume"].mean())
    lot_cost = price * 100  # 日本株の単元(100株)あたりコスト
    if lot_cost > budget_per_position or lot_cost <= 0:
        return None  # 予算オーバーは除外
    if avg_volume < 10000:
        return None  # 極端に薄い出来高(流動性リスク)は除外

    return {
        "code": code, "name": name, "price": round(price, 1),
        "lot_cost": round(lot_cost), "avg_volume": round(avg_volume),
        "years_with_dividend": sorted(years_with_div),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prime", action="store_true")
    parser.add_argument("--month", type=int, required=True, help="対象月(3 or 9)")
    parser.add_argument("--budget", type=float, default=500000, help="総予算(円)")
    parser.add_argument("--n", type=int, default=5, help="選定する銘柄数")
    args = parser.parse_args()

    universe = load_universe()
    tag = f"month{args.month}"
    checkpoint_path = f"rights_selector_checkpoint_{tag}.json"
    cache_path = f"rights_selector_cache_{tag}.json"

    budget_per_position = args.budget / args.n

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        candidates = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            saved = json.load(open(checkpoint_path, encoding="utf-8"))
            candidates = saved["candidates"]
            done_codes = set(saved["done_codes"])
            print(f"チェックポイントから再開: {len(done_codes)}銘柄処理済み")
        else:
            candidates = []
            done_codes = set()

        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"東証プライム全{len(universe)}銘柄から{args.month}月の定例配当銘柄を"
              f"予算{budget_per_position:,.0f}円/銘柄以内で抽出中...")
        for i, (code, name) in enumerate(todo, 1):
            r = check_stock(code, name, args.month, budget_per_position)
            if r:
                candidates.append(r)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"candidates": candidates, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(候補{len(candidates)}件)...")

        json.dump(candidates, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    candidates.sort(key=lambda c: c["avg_volume"], reverse=True)
    top = candidates[:args.n]

    print(f"\n候補銘柄(予算内かつ{args.month}月に過去{MIN_YEARS_WITH_DIVIDEND}年以上の配当実績、"
          f"流動性順): 全{len(candidates)}件中上位{len(top)}件\n")
    for r in top:
        print(f"  {r['code']} {r['name']:12s} 株価{r['price']:.0f}円 "
              f"単元コスト{r['lot_cost']:,}円 平均出来高{r['avg_volume']:,}株 "
              f"配当実績年: {r['years_with_dividend']}")

    total_cost = sum(r["lot_cost"] for r in top)
    print(f"\n合計必要資金(単元×{len(top)}銘柄): {total_cost:,}円(予算{args.budget:,.0f}円)")
    print("\n注意: これは過去の配当実績パターンからの候補抽出であり、実際の権利確定日は")
    print("      別途会社発表・証券会社の権利付き最終日カレンダー等で確認すること。")
    print("      自動発注はしない(候補提示のみ)。")


if __name__ == "__main__":
    main()
