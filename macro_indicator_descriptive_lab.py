#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
株価以外のマクロ価格指標(銅÷金比率・米国信用スプレッド)が「じわじわ型下落」を
警告できるかの段階①(記述統計)検証。FACTOR_RESEARCH_LESSONS.md第2節の早期打ち切り基準に従う。

事前登録した合格基準(データを見る前に決定、2026-10-05):
  警告 = 指標の12ヶ月(252営業日)変化が悪い方向(銅÷金は下落、スプレッドは拡大)
  米国データは日本の取引時間後に確定するため1営業日ラグ
  ITバブル崩壊期(2000-04〜2003-03)の警告日比率 >= 70%
  平時の上昇相場(2003-04〜2007-06, 2012-12〜2015-06, 2016-07〜2017-12)の誤警報率 <= 30%
  両者の差 >= 40pt
使い方: python macro_indicator_descriptive_lab.py
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
import requests
import yfinance as yf

LOOKBACK = 252
TARGET = (dt.date(2000, 4, 1), dt.date(2003, 3, 31))
CALM = [(dt.date(2003, 4, 1), dt.date(2007, 6, 30)),
        (dt.date(2012, 12, 1), dt.date(2015, 6, 30)),
        (dt.date(2016, 7, 1), dt.date(2017, 12, 31))]
REF = {"リーマン(2008-09〜2009-03)": (dt.date(2008, 9, 1), dt.date(2009, 3, 31)),
       "コロナ(2020-02〜2020-04)": (dt.date(2020, 2, 15), dt.date(2020, 4, 30))}


def yf_close(ticker: str) -> pd.Series:
    df = yf.Ticker(ticker).history(period="max", auto_adjust=True)
    s = df["Close"].dropna()
    s.index = pd.to_datetime(s.index.date)
    return s


def fred(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().set_index("date")["value"]


def frac(warn: pd.Series, periods) -> tuple[float, int]:
    mask = pd.Series(False, index=warn.index)
    for a, b in periods:
        mask |= (warn.index >= pd.Timestamp(a)) & (warn.index <= pd.Timestamp(b))
    w = warn[mask].dropna()
    return (float(w.mean()) if len(w) else float("nan")), len(w)


def main() -> None:
    n225 = yf_close("^N225")
    ma_f, ma_s = n225.rolling(120).mean(), n225.rolling(350).mean()
    bear = (ma_f < ma_s)

    indicators: dict[str, tuple[pd.Series, int]] = {}
    try:
        hg, gc = yf_close("HG=F"), yf_close("GC=F")
        ratio = (hg / gc).dropna()
        indicators["銅÷金比率(HG=F/GC=F)"] = (ratio, -1)
    except Exception as e:
        print(f"銅/金の取得失敗: {type(e).__name__}")
    try:
        tnx, irx = yf_close("^TNX"), yf_close("^IRX")
        curve = (tnx - irx).dropna()
        indicators["米長短金利差(10年-3ヶ月、^TNX-^IRX)"] = (curve, -1)
    except Exception as e:
        print(f"米金利の取得失敗: {type(e).__name__}")
    for sid, label in [("BAA10Y", "社債Baa-米10年債スプレッド(BAA10Y)"),
                       ("BAMLH0A0HYM2", "ハイイールド債スプレッド(BAMLH0A0HYM2)")]:
        try:
            indicators[label] = (fred(sid), +1)
        except Exception as e:
            print(f"{sid}の取得失敗: {type(e).__name__}")

    for label, (s, bad_dir) in indicators.items():
        print(f"\n=== {label} ===  データ期間 {s.index[0].date()}〜{s.index[-1].date()} (n={len(s)})")
        chg = s.diff(LOOKBACK)
        warn_us = (chg * bad_dir > 0).where(chg.notna())
        # 日本の営業日に合わせ、米国側は1営業日ラグ(前日までに確定した値のみ使う)
        warn_us = warn_us.shift(1)
        warn = warn_us.reindex(n225.index, method="ffill")

        t, nt = frac(warn, [TARGET])
        c, nc = frac(warn, CALM)
        tb, ntb = frac(warn[bear], [TARGET])
        ok = (t >= 0.70) and (c <= 0.30) and (t - c >= 0.40)
        print(f"  ITバブル崩壊期の警告日比率: {t*100:.1f}% (n={nt})"
              f"  うちデッドクロス中の日: {tb*100:.1f}% (n={ntb})")
        print(f"  平時上昇相場の誤警報率:     {c*100:.1f}% (n={nc})")
        print(f"  差: {(t-c)*100:+.1f}pt  → 段階①判定: {'合格' if ok else 'NO-GO'}")
        for name, per in REF.items():
            r, nr = frac(warn, [per])
            print(f"  参考 {name}: {r*100:.1f}% (n={nr})")

        # 警告の初発時期: ITバブル崩壊期前後で警告が連続で立ち始めた日
        w = warn[(warn.index >= pd.Timestamp("1999-06-01")) & (warn.index <= pd.Timestamp("2003-03-31"))]
        on = w[w == 1]
        if len(on):
            print(f"  1999-06以降で最初に警告が出た日: {on.index[0].date()}")
        dc = bear[(bear.index >= pd.Timestamp("1999-06-01")) & bear]
        if len(dc):
            print(f"  (参考)日経のデッドクロス初発: {dc.index[0].date()}")


if __name__ == "__main__":
    main()
