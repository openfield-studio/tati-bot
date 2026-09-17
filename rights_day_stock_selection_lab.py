#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
権利付き最終日効果: 銘柄選定がIS/OOSで再現するかの検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

seasonal_effects_lab.py(項目45)で権利付き最終日効果そのものは統計的に
極めて強いと確認済み(全銘柄プールでt=53.1)。しかし「リターンが見込めそうな
20銘柄を選ぶ」という個別銘柄選定は話が別: 1銘柄あたりの観測数が7年で平均
10件程度しかなく、少ないデータでの「たまたま良かった銘柄」を拾ってしまう
リスク(後出しジャンケンの罠)が高い。

research_agents.pyと同じ65%/35%のIS/OOS分割(時系列で前65%を学習用、
残り35%を検証用)を行い、「IS期間の平均リターンが良い上位20銘柄」を選んだ場合、
その同じ20銘柄がOOS期間でも(a)ランダム選定・(b)全銘柄平均を上回るかを確認する。

使い方: python rights_day_stock_selection_lab.py --prime
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import os
import random
import statistics as pystats
import sys

import yfinance as yf

CHECKPOINT_EVERY = 25
IS_RATIO = 0.65
RET_CAP = 2.0
TOP_N = 20


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def analyze_stock(code: str) -> list[dict]:
    """[{code, date(isoformat), ret}] のリストを返す(権利付き最終日の値動き)。"""
    try:
        ticker = yf.Ticker(f"{code}.T")
        df = ticker.history(period="7y", interval="1d")
        divs = ticker.dividends
    except Exception:
        return []
    df = df.dropna(subset=["Close"])
    if len(df) < 300 or divs is None or len(divs) == 0:
        return []
    closes = df["Close"].tolist()
    dates = [d.date() for d in df.index]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n = len(closes)

    out = []
    for div_date, _ in divs.items():
        d = div_date.date()
        idx = date_to_idx.get(d)
        if idx is None:
            best = None
            for i2, dt2 in enumerate(dates):
                diff = abs((dt2 - d).days)
                if diff <= 3 and (best is None or diff < best[1]):
                    best = (i2, diff)
            idx = best[0] if best else None
        if idx is None or idx < 2 or idx >= n:
            continue
        ret = closes[idx - 1] / closes[idx - 2] - 1
        if abs(ret) > RET_CAP:
            continue
        out.append({"code": code, "date": dates[idx - 1].isoformat(), "ret": ret})
    return out


def main() -> None:
    universe = load_universe()
    tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"rights_selection_checkpoint_{tag}.json"
    cache_path = f"rights_selection_cache_{tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        all_events = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            saved = json.load(open(checkpoint_path, encoding="utf-8"))
            all_events = saved["events"]
            done_codes = set(saved["done_codes"])
            print(f"チェックポイントから再開: {len(done_codes)}銘柄処理済み")
        else:
            all_events = []
            done_codes = set()

        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{tag}、残り{len(todo)}/{len(universe)}銘柄を処理中...")
        for i, (code, name) in enumerate(todo, 1):
            all_events += analyze_stock(code)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"events": all_events, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(イベント累計{len(all_events)})...")

        json.dump(all_events, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n総イベント数: {len(all_events)}\n")

    all_events.sort(key=lambda e: e["date"])
    split_idx = int(len(all_events) * IS_RATIO)
    split_date = all_events[split_idx]["date"]
    is_events = [e for e in all_events if e["date"] < split_date]
    oos_events = [e for e in all_events if e["date"] >= split_date]
    print(f"IS期間: 〜{split_date}(n={len(is_events)}) / OOS期間: {split_date}〜(n={len(oos_events)})")

    # 銘柄ごとのIS平均リターンを計算(最低3件は観測がある銘柄のみ対象)
    from collections import defaultdict
    is_by_code = defaultdict(list)
    for e in is_events:
        is_by_code[e["code"]].append(e["ret"])
    oos_by_code = defaultdict(list)
    for e in oos_events:
        oos_by_code[e["code"]].append(e["ret"])

    MIN_IS_EVENTS = 3
    candidates = [(code, pystats.mean(rets), len(rets)) for code, rets in is_by_code.items()
                  if len(rets) >= MIN_IS_EVENTS]
    candidates.sort(key=lambda c: c[1], reverse=True)
    top20 = candidates[:TOP_N]

    print(f"\nIS期間で観測{MIN_IS_EVENTS}件以上の銘柄: {len(candidates)}")
    print(f"\n=== IS期間トップ{TOP_N}銘柄(IS平均リターン順) ===")
    for code, avg, n in top20:
        oos_rets = oos_by_code.get(code, [])
        oos_avg_str = f"{pystats.mean(oos_rets)*100:+.2f}%(n={len(oos_rets)})" if oos_rets else "OOSデータなし"
        print(f"  {code}: IS平均{avg*100:+.2f}%(n={n}) → OOS平均{oos_avg_str}")

    # top20のOOS平均(そのままOOSデータがある銘柄だけプール)
    top20_oos_rets = []
    for code, avg, n in top20:
        top20_oos_rets += oos_by_code.get(code, [])

    # 全銘柄のOOS平均(ベースライン)
    all_oos_rets = [e["ret"] for e in oos_events]

    # ランダム20銘柄選定を100回試行した場合の分布(比較用)
    is_codes_with_min = [code for code, avg, n in candidates]
    random.seed(42)
    random_oos_means = []
    for _ in range(200):
        sample_codes = random.sample(is_codes_with_min, min(TOP_N, len(is_codes_with_min)))
        sample_rets = []
        for c in sample_codes:
            sample_rets += oos_by_code.get(c, [])
        if sample_rets:
            random_oos_means.append(pystats.mean(sample_rets))

    print(f"\n=== 比較: OOS期間での平均リターン ===")
    if top20_oos_rets:
        print(f"IS上位{TOP_N}銘柄のOOS平均: {pystats.mean(top20_oos_rets)*100:+.3f}%"
              f"(中央値{pystats.median(top20_oos_rets)*100:+.3f}%, n={len(top20_oos_rets)})")
    else:
        print(f"IS上位{TOP_N}銘柄のOOSデータなし")
    print(f"全銘柄OOS平均(ベースライン): {pystats.mean(all_oos_rets)*100:+.3f}%(n={len(all_oos_rets)})")
    if random_oos_means:
        print(f"ランダム{TOP_N}銘柄選定(200回試行)のOOS平均の分布: "
              f"平均{pystats.mean(random_oos_means)*100:+.3f}%, "
              f"標準偏差{pystats.pstdev(random_oos_means)*100:.3f}%")
        if top20_oos_rets:
            z = (pystats.mean(top20_oos_rets) - pystats.mean(random_oos_means)) / pystats.pstdev(random_oos_means) if pystats.pstdev(random_oos_means) > 0 else None
            print(f"IS選定20銘柄 vs ランダム選定の差: "
                  f"{(pystats.mean(top20_oos_rets)-pystats.mean(random_oos_means))*100:+.3f}pt"
                  + (f"(z={z:+.2f})" if z is not None else ""))

    print("\n注意: IS期間の銘柄あたり観測数が少ない(最低3件)ため、個別銘柄選定は")
    print("      統計的に不安定になりやすい。全銘柄プールでの効果(項目45)とは")
    print("      別物として評価すること。")


if __name__ == "__main__":
    main()
