#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#31: Permanent Portfolio型(株・長期国債・金・現金 各25%、四半期リバランス)の検証。

事前登録(2026-10-16、計算前にユーザーへ提示):
  株=^N225、長期国債=財務省「国債金利情報」10年金利(無い時期は9年)から
      近似トータルリターン r = y/245 − 8.5×Δy(修正デュレーション8.5固定)、
  金=GC=F×JPY=X(円建て、米国データは1営業日ラグ)、現金=0%。
  ITバブル崩壊期(2000-09〜2003)に4資産が揃わなければ判定不能で終了(試行数に数えない)。
  段階① ITバブル崩壊期(2000-09〜2003-12)の最大ドローダウンが日経100%の60%以下、かつ
        データのある全期間のCAGRが現行regime_shift比で2ポイント以内の低下。
  課税は四半期リバランスで売った分の実現益に年末20.315%(年内損益通算)で近似。
"""
from __future__ import annotations

import datetime as dt
import io
import math
import os
from collections import defaultdict

import pandas as pd
import requests
import yfinance as yf

TAX = 0.20315
COST = 0.002
MOD_DUR = 8.5


def era_to_date(s: str) -> dt.date | None:
    s = s.strip()
    base = {"S": 1925, "H": 1988, "R": 2018}
    if not s or s[0] not in base:
        return None
    y, m, d = s[1:].split(".")
    return dt.date(base[s[0]] + int(y), int(m), int(d))


def jgb_series() -> pd.Series:
    path = os.path.join(os.environ.get("TEMP", "."), "jgbcm_all.csv")
    if not os.path.exists(path):
        r = requests.get("https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv", timeout=60)
        open(path, "wb").write(r.content)
    df = pd.read_csv(path, encoding="shift_jis", skiprows=1)
    df["date"] = df["基準日"].map(era_to_date)
    df = df.dropna(subset=["date"])
    y10 = pd.to_numeric(df["10年"], errors="coerce")
    y9 = pd.to_numeric(df["9年"], errors="coerce")
    y = y10.fillna(y9) / 100
    s = pd.Series(y.values, index=pd.to_datetime(df["date"].values)).dropna()
    s = s[~s.index.duplicated()]
    ret = s.shift(1) / 245 - MOD_DUR * s.diff()
    return ret.dropna()


def close(t: str) -> pd.Series:
    x = yf.Ticker(t).history(period="max", auto_adjust=True)["Close"].dropna()
    x.index = pd.to_datetime(x.index.date)
    return x[~x.index.duplicated()]


def max_dd(v: pd.Series) -> float:
    return float((1 - v / v.cummax()).max())


def cagr(v: pd.Series) -> float:
    yrs = (v.index[-1] - v.index[0]).days / 365.25
    return (v.iloc[-1] / v.iloc[0]) ** (1 / yrs) - 1


def permanent(rets: pd.DataFrame, start: pd.Timestamp) -> pd.Series:
    """四半期末に25%ずつへ戻す。売却分の含み益を実現益とし、年末に課税(年内通算)。"""
    r = rets[rets.index >= start]
    w = {c: 0.25 for c in r.columns}
    basis = {c: 0.25 for c in r.columns}  # 取得原価(金額)
    val = {c: 0.25 for c in r.columns}
    realized = defaultdict(float)
    out = []
    prev_q = None
    for i, (d, row) in enumerate(r.iterrows()):
        for c in r.columns:
            val[c] *= 1 + row[c]
        total = sum(val.values())
        q = (d.year, (d.month - 1) // 3)
        last_of_year = i == len(r) - 1 or r.index[i + 1].year != d.year
        if prev_q is not None and q != prev_q:
            tgt = total / 4
            cost = sum(abs(val[c] - tgt) * COST for c in r.columns if c != "cash")
            for c in r.columns:
                diff = val[c] - tgt
                if c == "cash":
                    continue
                if diff > 0:
                    realized[d.year] += diff * (1 - basis[c] / val[c])
                    basis[c] *= tgt / val[c]
                else:
                    basis[c] += -diff
            new_each = (total - cost) / 4
            for c in r.columns:
                val[c] = new_each
        prev_q = q
        if last_of_year and realized.get(d.year, 0) > 0:
            tax = realized[d.year] * TAX
            val["cash"] -= tax
        out.append((d, sum(val.values())))
    return pd.Series([v for _, v in out], index=[d for d, _ in out])


def main() -> None:
    n225 = close("^N225")
    jgb = jgb_series()
    gold = (close("GC=F") * close("JPY=X")).dropna()
    print(f"データ期間: 日経 {n225.index[0].date()}〜 / 国債(10年or9年金利) {jgb.index[0].date()}〜 / "
          f"金(円建て) {gold.index[0].date()}〜")

    rets = pd.DataFrame({
        "stock": n225.pct_change(),
        "bond": jgb.reindex(n225.index),
        "gold": gold.pct_change().shift(1).reindex(n225.index),
    }).dropna()
    rets["cash"] = 0.0
    start_all = rets.index[0]
    print(f"4資産が揃う期間: {start_all.date()}〜{rets.index[-1].date()} ({len(rets)}営業日)")
    if start_all > pd.Timestamp("2000-09-30"):
        print("ITバブル崩壊期(2000-09〜)に4資産が揃わない → 判定不能で終了")
        return

    # 現行regime_shift(課税考慮)を同じ開始日から
    import copper_gold_filter_lab as B
    base = [(x, 1.0) for x in B.base_states()]

    def base_equity_series(start_year_date: pd.Timestamp) -> pd.Series:
        dates = B.dates
        start_i = next(i for i, d in enumerate(dates) if pd.Timestamp(d) >= start_year_date)
        eq = last_eq = 1.0
        yearly = defaultdict(float)
        vals = []
        for i in range(start_i + 1, B.n):
            leg, w = base[i - 1]
            eq *= 1 + (B.rets[i] * w if leg == "long" else -B.rets[i])
            if base[i] != base[i - 1]:
                eq *= 1 - COST
                yearly[dates[i].year] += eq - last_eq
                last_eq = eq
            if i == B.n - 1 or dates[i + 1].year != dates[i].year:
                g = yearly.get(dates[i].year, 0.0)
                if g > 0:
                    eq -= g * TAX
                    last_eq = eq
            vals.append((pd.Timestamp(dates[i]), eq))
        return pd.Series([v for _, v in vals], index=[d for d, _ in vals])

    for label, st in (("全期間(4資産が揃う日〜)", start_all), ("2006年開始(参考)", pd.Timestamp("2006-01-01"))):
        pp = permanent(rets, st)
        bh = (1 + rets["stock"][rets.index >= st]).cumprod()
        rs = base_equity_series(st)
        it = (pd.Timestamp("2000-09-01"), pd.Timestamp("2003-12-31"))
        print(f"\n--- {label} {st.date()}〜 ---")
        print(f"CAGR: Permanent {cagr(pp)*100:.2f}% / 現行regime_shift {cagr(rs)*100:.2f}% / 日経100% {cagr(bh)*100:.2f}%"
              f"  差(Permanent−現行) {(cagr(pp)-cagr(rs))*100:+.2f}pt")
        print(f"全期間MDD: Permanent {max_dd(pp)*100:.1f}% / 現行 {max_dd(rs)*100:.1f}% / 日経 {max_dd(bh)*100:.1f}%")
        if st <= it[0]:
            p_it = pp[(pp.index >= it[0]) & (pp.index <= it[1])]
            b_it = bh[(bh.index >= it[0]) & (bh.index <= it[1])]
            r1 = max_dd(p_it) / max_dd(b_it)
            ok1 = r1 <= 0.60
            ok2 = (cagr(pp) - cagr(rs)) >= -0.02
            print(f"ITバブル崩壊期MDD: Permanent {max_dd(p_it)*100:.1f}% / 日経 {max_dd(b_it)*100:.1f}% "
                  f"→ 比 {r1*100:.0f}%(基準60%以下 → {'OK' if ok1 else 'NG'})")
            print(f"CAGR差 基準-2pt以内 → {'OK' if ok2 else 'NG'}")
            print(f"段階①判定: {'合格' if ok1 and ok2 else 'NO-GO'}")
        yrs = defaultdict(list)
        for d, v in pp.items():
            yrs[d.year].append(v)


if __name__ == "__main__":
    main()
