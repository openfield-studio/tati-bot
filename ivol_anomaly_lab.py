#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
イディオシンクラティック・ボラティリティ・アノマリー(IVOLパズル)の実証検証
=====================================================================
調査待ちキュー#1(Ang, Hodrick, Xing, Zhang 2006 "The Cross-Section of Volatility
and Expected Returns", Journal of Finance)。個別銘柄の株価変動を市場モデルに回帰し、
市場要因で説明できない残差(固有ボラティリティ)が大きい銘柄ほど将来リターンが低い、
という国際的に頑健なアノマリー。

方法(先読みバイアス対策・多角的検証・ルール9準拠):
- 東証プライム全銘柄(market_breadth_cache.json、今日取得済みのキャッシュを再利用)
- 市場モデルの「市場」には日経平均(^N225)を使用(TOPIX長期データはyfinance未提供のため)
- 約1ヶ月(21営業日)ごとのスナップショット時点で、各銘柄の直近60営業日リターンを
  日経平均の同期間リターンに回帰し、残差の標準偏差をIVOLとする(先読みなし、過去60日のみ使用)
- スナップショット時点から先の6ヶ月・12ヶ月リターンを計測
- 各スナップショット時点でIVOLの3分位に分け、上位(高IVOL)と下位(低IVOL)のリターン差を見る
- 判定はプールしたt値だけでなく、年度単位で独立に数えた統計(ルール9)も併記

使い方: python ivol_anomaly_lab.py
"""
from __future__ import annotations
import datetime as dt
import json
from collections import defaultdict

import numpy as np
import yfinance as yf

SNAPSHOT_STEP = 21       # 約1ヶ月ごとにスナップショット
BETA_WINDOW = 60         # 固有ボラ計算に使う直近営業日数
FORWARD_MONTHS = [6, 12]
TRADING_DAYS_PER_MONTH = 21

print("=== データ読み込み ===")
with open("market_breadth_cache.json", encoding="utf-8") as f:
    cache = json.load(f)

df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
mkt_dates = [d.date() for d in df.index]
mkt_closes = [float(c) for c in df["Close"]]
mkt_date_to_idx = {d: i for i, d in enumerate(mkt_dates)}
mkt_rets_by_date = {mkt_dates[i]: mkt_closes[i]/mkt_closes[i-1]-1 for i in range(1, len(mkt_dates))}

# 各銘柄: 日付→終値のdict、日付→インデックスのdict(list.indexの反復呼び出しを避けて高速化)
stock_prices: dict[str, dict[dt.date, float]] = {}
stock_dates: dict[str, list[dt.date]] = {}
stock_date_idx: dict[str, dict[dt.date, int]] = {}
for code, v in cache.items():
    if len(v["closes"]) < BETA_WINDOW + TRADING_DAYS_PER_MONTH * 12 + 10:
        continue
    dates = [dt.datetime.strptime(d, "%Y-%m-%d").date() for d in v["dates"]]
    stock_dates[code] = dates
    stock_prices[code] = dict(zip(dates, v["closes"]))
    stock_date_idx[code] = {d: i for i, d in enumerate(dates)}

print(f"有効銘柄数(十分な期間データあり): {len(stock_prices)}")

# スナップショット日程(日経平均の営業日グリッドを使う、BETA_WINDOW以降・FORWARD分の余裕を残す)
max_forward = max(FORWARD_MONTHS) * TRADING_DAYS_PER_MONTH
snapshot_idxs = list(range(BETA_WINDOW, len(mkt_dates) - max_forward, SNAPSHOT_STEP))
print(f"スナップショット数: {len(snapshot_idxs)}")

# 観測を蓄積: (snapshot_date, code, ivol, fwd_ret_6m, fwd_ret_12m)
observations = []

for si in snapshot_idxs:
    snap_date = mkt_dates[si]
    # 直近BETA_WINDOW日の市場リターン(配列)
    mkt_window = np.array([mkt_closes[si-k]/mkt_closes[si-k-1]-1 for k in range(BETA_WINDOW-1, -1, -1)])
    mkt_var = mkt_window.var()
    if mkt_var <= 0:
        continue

    for code, prices in stock_prices.items():
        dates = stock_dates[code]
        if snap_date not in prices:
            continue
        # 直近BETA_WINDOW日の株価リターンを取得(欠損があればスキップ)
        stock_i = stock_date_idx[code].get(snap_date)
        if stock_i is None:
            continue
        if stock_i < BETA_WINDOW:
            continue
        window_dates = dates[stock_i-BETA_WINDOW:stock_i+1]
        window_prices = [prices[d] for d in window_dates]
        stock_rets = np.array([window_prices[k]/window_prices[k-1]-1 for k in range(1, len(window_prices))])
        if len(stock_rets) != BETA_WINDOW:
            continue

        # 単純回帰: stock_ret = alpha + beta*mkt_ret + resid
        X = np.vstack([np.ones(BETA_WINDOW), mkt_window]).T
        try:
            coef, *_ = np.linalg.lstsq(X, stock_rets, rcond=None)
        except np.linalg.LinAlgError:
            continue
        resid = stock_rets - X @ coef
        ivol = float(resid.std())

        # 将来リターン
        fwd = {}
        ok = True
        for m in FORWARD_MONTHS:
            fwd_i = stock_i + m * TRADING_DAYS_PER_MONTH
            if fwd_i >= len(dates):
                ok = False
                break
            fwd_date = dates[fwd_i]
            fwd[m] = prices[fwd_date] / prices[snap_date] - 1
        if not ok:
            continue

        observations.append({"date": snap_date, "code": code, "ivol": ivol,
                              "fwd6": fwd[6], "fwd12": fwd[12]})

print(f"総観測数: {len(observations)}")

with open("ivol_observations_cache.json", "w", encoding="utf-8") as f:
    json.dump([{**o, "date": o["date"].isoformat()} for o in observations], f)
print("ivol_observations_cache.jsonに保存")
