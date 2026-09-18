#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPO長期アンダーパフォーマンスの実証検証(Ritter 1991)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

新規上場企業は上場後3〜5年で市場平均を下回る傾向があるとされる
(Ritter 1991 "The Long-Run Performance of Initial Public Offerings")。
ロックアップ解除効果(#29、上場90日後の短期的な下落)とは全く異なる時間軸の
長期アノマリー。

★データソースと限界★
2020年のIPO銘柄一覧(kabukiso.com、2026-09-18取得)から37銘柄の上場日を収集。
今日(2026-09-18)時点で上場から約5.7〜6.6年経過しており、3年・5年後の
パフォーマンスを検証できる。

使い方: python ipo_longrun_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats

import yfinance as yf
from scipy import stats

RET_CAP = 5.0  # 個別IPO株は値動きが大きいため緩めのキャップ

# (証券コード, 上場日) — 出典: kabukiso.com「2020年のIPO銘柄一覧」(2026-09-18取得)
IPOS_2020 = [
    ("7081", "2020-02-07"), ("7082", "2020-02-07"), ("7083", "2020-02-25"),
    ("7085", "2020-03-02"), ("7086", "2020-03-06"), ("7087", "2020-03-06"),
    ("4493", "2020-03-26"), ("7093", "2020-03-26"), ("7317", "2020-04-06"),
    ("2987", "2020-10-02"), ("7357", "2020-11-26"), ("4015", "2020-11-19"),
    ("4016", "2020-11-25"), ("4020", "2020-12-17"), ("4166", "2020-12-17"),
    ("7095", "2020-03-31"), ("7094", "2020-03-30"), ("1444", "2020-03-30"),
    ("5071", "2020-03-25"), ("5690", "2020-03-24"), ("5368", "2020-03-19"),
    ("9326", "2020-03-19"), ("4492", "2020-03-19"), ("5070", "2020-03-17"),
    ("7091", "2020-03-17"), ("7688", "2020-03-17"), ("7687", "2020-03-16"),
    ("7692", "2020-10-16"), ("4012", "2020-09-30"), ("4011", "2020-09-29"),
    ("4060", "2020-09-28"), ("4933", "2020-09-25"), ("2932", "2020-09-25"),
    ("4059", "2020-09-24"), ("4930", "2020-09-24"), ("4058", "2020-09-24"),
    ("1375", "2020-09-17"),
]


def window_return(symbol: str, start: str, end: str) -> float | None:
    try:
        df = yf.Ticker(symbol).history(start=start, end=end, interval="1d")
    except Exception:
        return None
    if df.empty or len(df) < 2:
        return None
    return float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1


def main() -> None:
    results = {36: [], 60: []}
    for code, listing_str in IPOS_2020:
        listing = dt.date.fromisoformat(listing_str)
        start = (listing + dt.timedelta(days=10)).isoformat()  # 初値形成直後を避ける
        for months in (36, 60):
            end = (listing + dt.timedelta(days=int(months * 30.4))).isoformat()
            stock_ret = window_return(f"{code}.T", start, end)
            mkt_ret = window_return("^N225", start, end)
            if stock_ret is not None and mkt_ret is not None:
                results[months].append(stock_ret - mkt_ret)

    for months in (36, 60):
        data = [r for r in results[months] if abs(r) <= RET_CAP]
        if not data:
            print(f"{months}ヶ月後: サンプル不足")
            continue
        win = sum(1 for r in data if r > 0) / len(data) * 100
        t, p = stats.ttest_1samp(data, 0)
        print(f"上場{months}ヶ月後の対^N225超過リターン: 平均{pystats.mean(data)*100:+.1f}%"
              f"(中央値{pystats.median(data)*100:+.1f}%, 勝率{win:.1f}%, n={len(data)}, "
              f"t={t:.2f}, p={p:.4f})")

    print(f"\n対象IPO銘柄数: {len(IPOS_2020)}(2020年上場)")
    print("注意: 上場から10日後を起点とし初値形成直後の乱高下を除外。生存バイアス"
          "(検証時点まで上場廃止・非公開化していない銘柄のみ)に留意。")


if __name__ == "__main__":
    main()
