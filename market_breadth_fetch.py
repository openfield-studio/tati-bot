#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市場ブレッド(値上がり銘柄比率)検証のためのデータ取得。
東証プライム全銘柄(tse_prime_universe.csv)の日次終値を取得し、25銘柄ごとに
チェックポイント保存する(individual_value_backtest.pyと同じ方式、クラッシュ対策)。

使い方: python market_breadth_fetch.py
"""
from __future__ import annotations
import csv
import json
import os
import time

import yfinance as yf

CACHE_PATH = "market_breadth_cache.json"
CHECKPOINT_EVERY = 25


def load_universe() -> list[str]:
    with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
        return [r["code"] for r in csv.DictReader(f)]


def load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict) -> None:
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, CACHE_PATH)


def main() -> None:
    codes = load_universe()
    cache = load_cache()
    print(f"対象銘柄数: {len(codes)}、キャッシュ済み: {len(cache)}")

    done = 0
    for i, code in enumerate(codes):
        if code in cache:
            continue
        try:
            df = yf.Ticker(f"{code}.T").history(period="max", auto_adjust=True).dropna(subset=["Close"])
            if len(df) > 0:
                dates = [idx.strftime("%Y-%m-%d") for idx in df.index]
                closes = [round(float(c), 2) for c in df["Close"]]
                cache[code] = {"dates": dates, "closes": closes}
            else:
                cache[code] = {"dates": [], "closes": []}
        except Exception as e:
            print(f"  {code}: エラー({e}), スキップ")
            cache[code] = {"dates": [], "closes": []}

        done += 1
        if done % CHECKPOINT_EVERY == 0:
            save_cache(cache)
            print(f"  進捗: {i+1}/{len(codes)} ({len(cache)}件キャッシュ済み)")

    save_cache(cache)
    print(f"完了: {len(cache)}銘柄のデータを{CACHE_PATH}に保存")


if __name__ == "__main__":
    main()
