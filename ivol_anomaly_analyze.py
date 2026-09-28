#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IVOLアノマリーの分析: 3分位スプレッド、プールt値、年度単位の独立集計(ルール9準拠)。"""
from __future__ import annotations
import json
import datetime as dt
from collections import defaultdict
import statistics as st
import math

with open("ivol_observations_cache.json", encoding="utf-8") as f:
    obs = json.load(f)
for o in obs:
    o["date"] = dt.date.fromisoformat(o["date"])

print(f"総観測数: {len(obs)}")

by_date = defaultdict(list)
for o in obs:
    by_date[o["date"]].append(o)

RET_CAP = 2.0  # |リターン|>200%は異常値として除外(project既存ルール)


def tercile_spread(period_key: str):
    """各スナップショット日ごとに3分位に分け、下位(低IVOL)-上位(高IVOL)ではなく
    上位(高IVOL)-下位(低IVOL)のスプレッドを計算(アノマリー予想=マイナス)。"""
    low_all, high_all = [], []
    per_date_spread = {}
    for d, rows in by_date.items():
        rows = [r for r in rows if abs(r[period_key]) <= RET_CAP]
        if len(rows) < 30:
            continue
        rows_sorted = sorted(rows, key=lambda r: r["ivol"])
        n = len(rows_sorted)
        low = rows_sorted[: n // 3]
        high = rows_sorted[-(n // 3):]
        low_rets = [r[period_key] for r in low]
        high_rets = [r[period_key] for r in high]
        low_all += low_rets
        high_all += high_rets
        per_date_spread[d] = st.mean(high_rets) - st.mean(low_rets)
    return low_all, high_all, per_date_spread


for period_key, label in [("fwd6", "6ヶ月後"), ("fwd12", "12ヶ月後")]:
    print(f"\n{'='*80}\n{label}リターン\n{'='*80}")
    low_all, high_all, per_date_spread = tercile_spread(period_key)

    low_mean = st.mean(low_all) * 100
    high_mean = st.mean(high_all) * 100
    spread = high_mean - low_mean
    print(f"低IVOL群(下位1/3): 平均{low_mean:+.2f}pt (n={len(low_all)})")
    print(f"高IVOL群(上位1/3): 平均{high_mean:+.2f}pt (n={len(high_all)})")
    print(f"スプレッド(高IVOL-低IVOL): {spread:+.2f}pt  ※アノマリー予想はマイナス(高IVOLほど低リターン)")

    # プールt検定(参考値、過大評価に注意)
    pooled = [r for r in high_all] + [-r for r in low_all]  # 簡易的にスプレッド分布を作る近似ではなく、単純に両群のt検定
    if len(low_all) > 1 and len(high_all) > 1:
        m1, m2 = st.mean(high_all), st.mean(low_all)
        v1, v2 = st.variance(high_all), st.variance(low_all)
        n1, n2 = len(high_all), len(low_all)
        se = math.sqrt(v1/n1 + v2/n2)
        t_pooled = (m1 - m2) / se if se > 0 else 0.0
        print(f"プールt値(参考、過大評価注意): t={t_pooled:.2f}")

    # 年度単位の独立集計(ルール9): スナップショット日ごとのスプレッドを年で平均→年度間t検定
    by_year = defaultdict(list)
    for d, sp in per_date_spread.items():
        by_year[d.year].append(sp)
    year_means = {y: st.mean(vs) * 100 for y, vs in by_year.items()}
    n_years = len(year_means)
    n_neg = sum(1 for v in year_means.values() if v < 0)
    print(f"\n年度単位の集計(独立な年度数={n_years}):")
    for y in sorted(year_means):
        print(f"  {y}: {year_means[y]:+.2f}pt")
    print(f"マイナス(アノマリー予想と一致)の年度数: {n_neg}/{n_years}")
    yvals = list(year_means.values())
    if len(yvals) > 1:
        ymean = st.mean(yvals)
        ystd = st.stdev(yvals)
        yse = ystd / math.sqrt(len(yvals))
        yt = ymean / yse if yse > 0 else 0.0
        print(f"年度間平均スプレッド: {ymean:+.2f}pt, 年度間t値(年度を1観測): t={yt:.2f}")
