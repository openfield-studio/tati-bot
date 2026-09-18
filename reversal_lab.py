#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短期リバーサル(1日・1週間)の一括検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

  1. 短期リバーサル(1日、Jegadeesh 1990): 前日に極端な値動きをした銘柄は
     翌日に反転しやすい。既存の月次モメンタム(academic_factors_lab.py)とは
     全く異なる時間軸(日次)。
  2. 週次リバーサル(Lehmann 1990): 1週間(5営業日)の値動きの反転。
     日次と月次モメンタムの中間の時間軸。

東証プライム全銘柄、各銘柄の日次終値系列を5営業日おきにサンプリングして
クロスセクショナル比較する(全営業日を使うと組み合わせ爆発するため間引き)。

使い方: python reversal_lab.py --prime
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
RET_CAP = 0.5
SAMPLE_STEP = 5  # 営業日おきにサンプリング


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def collect(code: str) -> list[dict]:
    try:
        hist = yf.Ticker(f"{code}.T").history(period="max", interval="1d")
    except Exception:
        return []
    df = hist.dropna(subset=["Close"])
    if len(df) < 300:
        return []
    closes = df["Close"].tolist()
    dates = [d.date() for d in df.index]
    n = len(closes)

    out = []
    for i in range(10, n - 5, SAMPLE_STEP):
        past_1d = closes[i] / closes[i - 1] - 1
        past_5d = closes[i] / closes[i - 5] - 1
        fwd_1d = closes[i + 1] / closes[i] - 1
        fwd_5d = closes[i + 5] / closes[i] - 1
        out.append({"code": code, "date": dates[i].isoformat(),
                     "past_1d": past_1d, "past_5d": past_5d,
                     "fwd_1d": fwd_1d, "fwd_5d": fwd_5d})
    return out


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"reversal_checkpoint_{universe_tag}.json"
    cache_path = f"reversal_cache_{universe_tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        all_obs = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            saved = json.load(open(checkpoint_path, encoding="utf-8"))
            all_obs = saved["observations"]
            done_codes = set(saved["done_codes"])
            print(f"チェックポイントから再開: {len(done_codes)}銘柄処理済み、観測数 累計{len(all_obs)}")
        else:
            all_obs = []
            done_codes = set()

        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{universe_tag}、残り{len(todo)}/{len(universe)}銘柄を処理中...")
        for i, (code, name) in enumerate(todo, 1):
            all_obs += collect(code)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"observations": all_obs, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(観測数 累計{len(all_obs)})...")

        json.dump(all_obs, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n合計観測数: {len(all_obs)}\n")

    for past_key, fwd_key, label in [("past_1d", "fwd_1d", "短期リバーサル(1日、低い=下落した方が良いはず)"),
                                      ("past_5d", "fwd_5d", "週次リバーサル(低い=下落した方が良いはず)")]:
        print(f"{'='*70}\n=== {label} ===\n{'='*70}")
        by_date = defaultdict(list)
        for o in all_obs:
            by_date[o["date"]].append(o)
        pooled_good, pooled_bad = [], []
        for date_str, obs_list in by_date.items():
            yr_sorted = sorted(obs_list, key=lambda o: o[past_key])
            n = len(yr_sorted)
            tercile = n // 3
            if tercile < 5:
                continue
            low_group = yr_sorted[:tercile]   # 下落した銘柄(負け組)
            high_group = yr_sorted[-tercile:]  # 上昇した銘柄(勝ち組)
            pooled_good += [o[fwd_key] for o in low_group]  # リバーサル仮説: 負け組が良い
            pooled_bad += [o[fwd_key] for o in high_group]

        g_r = [r for r in pooled_good if abs(r) <= RET_CAP]
        b_r = [r for r in pooled_bad if abs(r) <= RET_CAP]
        if g_r and b_r:
            diff = (pystats.mean(g_r) - pystats.mean(b_r)) * 100
            print(f"  負け組(直近下落)={pystats.mean(g_r)*100:+.3f}%(中央値{pystats.median(g_r)*100:+.3f}%, n={len(g_r)}) / "
                  f"勝ち組(直近上昇)={pystats.mean(b_r)*100:+.3f}%(中央値{pystats.median(b_r)*100:+.3f}%, n={len(b_r)}) / 差={diff:+.3f}pt")
        else:
            print("  サンプル不足")
        print()

    print("注意: 東証プライム全銘柄、5営業日おきにサンプリング(全日を使うと組み合わせ爆発するため)。"
          "日付単位のクロスセクショナル比較(同じ日付に複数銘柄の観測が存在する前提)。"
          "取引コストを考慮すると1日保有の戦略は往復コスト(約16bps)に対して非常に不利な点に注意。"
          "DSR等の多重検定補正は未実施。")


if __name__ == "__main__":
    main()
