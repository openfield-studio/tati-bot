#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市場ブレッド(値上がり銘柄比率)を計算し、regime_shiftのじわじわ型下落への追加対抗策
として使えるか検証する。

各銘柄の「価格が自身の200日移動平均より上か」を日次で判定し、東証プライム全銘柄での
「上回っている銘柄の割合」を集計する。この比率が大きく下がる(内部の広がりが弱まる)ことを、
デッドクロス確定中の追加エントリートリガーとして使う。

使い方: python market_breadth_analyze.py
"""
from __future__ import annotations
import datetime as dt
import json
from collections import defaultdict

import yfinance as yf

MA_WINDOW = 200
BREADTH_TH = 0.30       # 値上がり銘柄比率がこれを下回ったら「内部が弱い」と判定
BREADTH_LOOKBACK = 10   # 何日以内の下抜けを「新規」として拾うか(重複トリガー回避)

with open("market_breadth_cache.json", encoding="utf-8") as f:
    cache = json.load(f)

print("=== 各銘柄の200日MA上抜け/下抜けを計算中 ===")
all_dates = set()
per_stock_above = {}  # code -> {date: bool}
for code, v in cache.items():
    dates_str = v["dates"]
    closes = v["closes"]
    if len(closes) < MA_WINDOW + 10:
        continue
    dates = [dt.datetime.strptime(d, "%Y-%m-%d").date() for d in dates_str]
    above = {}
    s = sum(closes[:MA_WINDOW])
    for i in range(MA_WINDOW, len(closes)):
        s += closes[i] - closes[i - MA_WINDOW]
        ma = s / MA_WINDOW
        above[dates[i]] = closes[i] > ma
    per_stock_above[code] = above
    all_dates.update(above.keys())

print(f"有効銘柄数: {len(per_stock_above)}, 集計対象日数: {len(all_dates)}")

# 日付ごとに集計(全銘柄が同じ営業日を持つわけではないので、その日にデータがある銘柄のみで割合計算)
by_date_total = defaultdict(int)
by_date_above = defaultdict(int)
for code, above in per_stock_above.items():
    for d, is_above in above.items():
        by_date_total[d] += 1
        if is_above:
            by_date_above[d] += 1

breadth = {}
for d in all_dates:
    if by_date_total[d] >= 200:  # 集計対象が少なすぎる日は信頼できないので除外
        breadth[d] = by_date_above[d] / by_date_total[d]

sorted_dates = sorted(breadth)
print(f"ブレッド系列: {sorted_dates[0]} 〜 {sorted_dates[-1]} ({len(sorted_dates)}日)")

# 保存(次のバックテストスクリプトで再利用)
out = {d.isoformat(): v for d, v in breadth.items()}
with open("market_breadth_series.json", "w", encoding="utf-8") as f:
    json.dump(out, f)
print("market_breadth_series.jsonに保存")

# 2000-2003年の値を確認(今日の焦点であるITバブル崩壊期)
print("\n=== 2000-2003年のブレッド推移(月初のみ抽出) ===")
prev_month = None
for d in sorted_dates:
    if dt.date(2000, 1, 1) <= d <= dt.date(2003, 12, 31):
        if d.month != prev_month:
            print(f"  {d}: {breadth[d]*100:.1f}%")
            prev_month = d.month

print("\n=== 参考: 2008年リーマン期の推移 ===")
prev_month = None
for d in sorted_dates:
    if dt.date(2008, 1, 1) <= d <= dt.date(2009, 6, 30):
        if d.month != prev_month:
            print(f"  {d}: {breadth[d]*100:.1f}%")
            prev_month = d.month
