#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日銀金融政策決定会合前後の値動き効果の検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

「特定の日の値動き」候補調査シリーズ#5。日銀の金融政策決定会合は年8回、
日程が事前公表されている。会合結果公表日の前後でボラティリティが高まる
とされるが、方向性のアノマリーとしての報告は薄いため実証検証する。

出典: 日本銀行公式サイト「過去の金融政策決定会合の開催日等」(2026-09-18取得、
2019〜2025年の結果公表日)

使い方: python boj_meeting_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats

import yfinance as yf
from scipy import stats

RET_CAP = 0.3

# 日銀金融政策決定会合の結果公表日(出典: boj.or.jp、2019〜2025年)
MEETING_DATES = [
    "2019-01-23", "2019-03-15", "2019-04-25", "2019-06-20", "2019-07-30",
    "2019-09-19", "2019-10-31", "2019-12-19",
    "2020-01-21", "2020-03-16", "2020-04-27", "2020-05-22", "2020-06-16",
    "2020-07-15", "2020-09-17", "2020-10-29", "2020-12-18",
    "2021-01-21", "2021-03-19", "2021-04-27", "2021-06-18", "2021-07-16",
    "2021-09-22", "2021-10-28", "2021-12-17",
    "2022-01-18", "2022-03-18", "2022-04-28", "2022-06-17", "2022-07-21",
    "2022-09-22", "2022-10-28", "2022-12-20",
    "2023-01-18", "2023-03-10", "2023-04-28", "2023-06-16", "2023-07-28",
    "2023-09-22", "2023-10-31", "2023-12-19",
    "2024-01-23", "2024-03-19", "2024-04-26", "2024-06-14", "2024-07-31",
    "2024-09-20", "2024-10-31", "2024-12-19",
    "2025-01-24", "2025-03-19", "2025-05-01", "2025-06-17", "2025-07-31",
    "2025-09-19", "2025-10-30", "2025-12-19",
]


def load_1306():
    df = yf.Ticker("1306.T").history(period="max")
    df = df[df["Close"].notna()]
    dates = sorted(idx.date() for idx in df.index)
    closes = {idx.date(): float(row["Close"]) for idx, row in df.iterrows()}
    return dates, closes


def nearest_idx(dates, target, date_idx):
    if target in date_idx:
        return date_idx[target]
    for offset in range(1, 5):
        d = target + dt.timedelta(days=offset)
        if d in date_idx:
            return date_idx[d]
    return None


def main() -> None:
    dates, closes = load_1306()
    date_idx = {d: i for i, d in enumerate(dates)}

    same_day_rets, next_day_rets = [], []
    for m in MEETING_DATES:
        target = dt.date.fromisoformat(m)
        i = nearest_idx(dates, target, date_idx)
        if i is None or i < 1 or i + 1 >= len(dates):
            continue
        same_day = closes[dates[i]] / closes[dates[i - 1]] - 1
        next_day = closes[dates[i + 1]] / closes[dates[i]] - 1
        if abs(same_day) <= RET_CAP:
            same_day_rets.append(same_day)
        if abs(next_day) <= RET_CAP:
            next_day_rets.append(next_day)

    print(f"対象会合数: {len(MEETING_DATES)}、有効n={len(same_day_rets)}")

    def report(label, data):
        if not data:
            print(f"  {label}: サンプル不足")
            return
        win = sum(1 for r in data if r > 0) / len(data) * 100
        t, p = stats.ttest_1samp(data, 0)
        print(f"  {label}: 平均={pystats.mean(data)*100:+.3f}%(勝率{win:.1f}%, n={len(data)}, t={t:.2f}, p={p:.3f})")

    report("会合結果公表当日の値動き", same_day_rets)
    report("結果公表翌営業日の値動き", next_day_rets)

    print("\n注意: 1306(TOPIX連動ETF)単体、方向性のみ検証(ボラティリティの大きさは別途未検証)。")


if __name__ == "__main__":
    main()
