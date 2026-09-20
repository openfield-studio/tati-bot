#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
業種ニュートラル化の検証(value_screener改善案の裏付け取り)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

2026-09-20、Kaggle「JPX Tokyo Stock Exchange Prediction」上位解法調査で
「業種別に独立したモデルを組んだチームが上位だった」という知見を得た。これが
value_screener.pyの改善(全市場一律ランキング→業種内ランキング)に本当に効くか、
既存のfund5_cache_prime.json(B/M・質スコア・ret12のパネル)にyfinanceのsector
(業種、11分類)を突き合わせて検証する。

検証方法: 年度×業種でB/M+質の複合スコアを算出し、(a)全市場一律の三分位スプレッドと
(b)業種内での三分位スプレッド(業種ごとに三分位を取ってから全業種プール)を比較する。

使い方: python sector_neutral_lab.py
"""
from __future__ import annotations
import csv
import json
import os
import time
import statistics as pystats
from collections import defaultdict

import yfinance as yf
from scipy import stats

CHECKPOINT_EVERY = 25


def load_universe():
    with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
        return [(row["code"], row["name"]) for row in csv.DictReader(f)]


def fetch_sectors():
    cache_path = "sector_map_cache.json"
    checkpoint_path = "sector_map_checkpoint.json"
    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        return json.load(open(cache_path, encoding="utf-8"))

    universe = load_universe()
    if os.path.exists(checkpoint_path):
        state = json.load(open(checkpoint_path, encoding="utf-8"))
        print(f"チェックポイントから再開: {len(state['done'])}銘柄処理済み")
    else:
        state = {"map": {}, "done": []}

    done = set(state["done"])
    todo = [(c, n) for c, n in universe if c not in done]
    print(f"業種情報を取得中: 残り{len(todo)}/{len(universe)}銘柄...")
    for i, (code, name) in enumerate(todo, 1):
        try:
            sector = yf.Ticker(f"{code}.T").info.get("sector")
        except Exception:
            sector = None
        if sector:
            state["map"][code] = sector
        state["done"].append(code)
        if i % CHECKPOINT_EVERY == 0:
            json.dump(state, open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  {i}/{len(todo)}件処理済み...")
        time.sleep(0.05)

    json.dump(state["map"], open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
    return state["map"]


def load_panel(sector_map):
    d = json.load(open("fund5_cache_prime.json", encoding="utf-8"))
    panel = []
    for o in d:
        r = o.get("ret12")
        if r is None or abs(r) > 2.0:
            continue
        sector = sector_map.get(o["code"])
        if not sector:
            continue
        bm = o.get("book_to_market")
        roic = o.get("roic")
        if bm is None or roic is None:
            continue
        panel.append({"code": o["code"], "cohort": o["fiscal_year"], "ret12": r,
                      "sector": sector, "bm": bm, "roic": roic})
    return panel


def pct_rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    n = len(values)
    for rank, idx in enumerate(order):
        ranks[idx] = rank / max(1, n - 1)
    return ranks


def combo_score(rows):
    bm_r = pct_rank([r["bm"] for r in rows])
    roic_r = pct_rank([r["roic"] for r in rows])
    for r, b, o in zip(rows, bm_r, roic_r):
        r["score"] = (b + o) / 2


def market_wide_spread(rows_by_year):
    spreads = {}
    for year, rows in rows_by_year.items():
        if len(rows) < 100:
            continue
        combo_score(rows)
        rs = sorted(rows, key=lambda r: r["score"], reverse=True)
        n = len(rs)
        top = [r["ret12"] for r in rs[:n // 3]]
        bot = [r["ret12"] for r in rs[-(n // 3):]]
        spreads[year] = (pystats.mean(top) - pystats.mean(bot)) * 100
    return spreads


def sector_neutral_spread(rows_by_year):
    spreads = {}
    for year, rows in rows_by_year.items():
        by_sector = defaultdict(list)
        for r in rows:
            by_sector[r["sector"]].append(r)
        top_all, bot_all = [], []
        for sector, srows in by_sector.items():
            if len(srows) < 15:
                continue
            combo_score(srows)
            rs = sorted(srows, key=lambda r: r["score"], reverse=True)
            n = len(rs)
            top_all += [r["ret12"] for r in rs[:n // 3]]
            bot_all += [r["ret12"] for r in rs[-(n // 3):]]
        if len(top_all) < 30:
            continue
        spreads[year] = (pystats.mean(top_all) - pystats.mean(bot_all)) * 100
    return spreads


def fm_summary(vals: dict) -> str:
    v = list(vals.values())
    if len(v) < 2:
        return "年度数不足"
    mean = pystats.mean(v)
    sd = pystats.stdev(v)
    t = mean / (sd / len(v) ** 0.5) if sd > 0 else float("inf")
    pos = sum(1 for x in v if x > 0)
    detail = "  ".join(f"{y}:{s:+.1f}" for y, s in sorted(vals.items()))
    return f"平均{mean:+.1f}pt 年度間t={t:+.2f} プラス{pos}/{len(v)}年度 [{detail}]"


def main():
    sector_map = fetch_sectors()
    print(f"\n業種マッピング成功: {len(sector_map)}銘柄\n")
    sector_counts = defaultdict(int)
    for s in sector_map.values():
        sector_counts[s] += 1
    print("業種別銘柄数:", dict(sorted(sector_counts.items(), key=lambda x: -x[1])))

    panel = load_panel(sector_map)
    print(f"\nパネル(B/M・ROIC・ret12・業種すべて揃う観測): {len(panel)}件\n")

    by_year = defaultdict(list)
    for r in panel:
        by_year[r["cohort"]].append(r)

    mw = market_wide_spread(by_year)
    sn = sector_neutral_spread(by_year)

    print("=" * 70)
    print("全市場一律ランキング(業種を無視、B/M+ROIC複合スコア三分位スプレッド)")
    print(fm_summary(mw))
    print("\n業種内ランキング(業種ごとに三分位→全業種プール)")
    print(fm_summary(sn))
    print("=" * 70)


if __name__ == "__main__":
    main()
