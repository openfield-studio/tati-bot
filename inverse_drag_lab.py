#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#30: インバース型ETF(1571)のボラティリティドラッグ検証。

事前登録(2026-10-16):
 段階① 現行regime_shiftの各1571保有エピソードごとに
        gap = (日経日次リターン×-1の複利) - (-1×日経の期間リターン)
        ITバブル崩壊(2000-09〜2003)のエピソード平均gapがリーマン(2008-09〜2009)より
        マイナス方向に大きく、差がIS期間(前半65%)のエピソードgapの標準偏差より大きければ合格。
 参考   2008年以降は1571.Tの実価格で実リターンと理論(日次-1倍)のずれを報告。
 ①合格時のみ ② MAX_HOLD=10で3シナリオ全改善 ③ 7/15日で符号不変 ④ 取引回数
"""
from __future__ import annotations

import datetime as dt
import statistics as st

import pandas as pd
import yfinance as yf

MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
IS_RATIO = 0.65


def close(t: str) -> pd.Series:
    s = yf.Ticker(t).history(period="max", auto_adjust=True)["Close"].dropna()
    s.index = pd.to_datetime(s.index.date)
    return s


n225 = close("^N225")
dates = [d.date() for d in n225.index]
px = [float(v) for v in n225.values]
n = len(px)
rets = [0.0] + [px[i] / px[i - 1] - 1 for i in range(1, n)]
ma_f = n225.rolling(MA_FAST).mean().values
ma_s = n225.rolling(MA_SLOW).mean().values
bear_regime = [(not pd.isna(ma_f[i]) and not pd.isna(ma_s[i]) and ma_f[i] < ma_s[i]) for i in range(n)]
split = int(n * IS_RATIO)


def base_states() -> list[str]:
    s = ["long"] * n
    holding, entry_i, last_shock = "long", 0, -10**9
    for i in range(MA_SLOW, n):
        if holding == "bear":
            rr = -(px[i] / px[entry_i] - 1)
            if rr >= BEAR_TP or rr <= -BEAR_SL or i - entry_i >= MAX_HOLD:
                holding, entry_i = "long", i
        else:
            if rets[i] <= SHOCK_TH:
                if (i - last_shock) >= COOLDOWN and bear_regime[i]:
                    holding, entry_i = "bear", i
                last_shock = i
        s[i] = holding
    return s


def episodes(states: list[str]) -> list[tuple[int, int]]:
    """(切替日i0, 復帰日i1)。保有リターンはi0終値→i1終値(evaluateと同じく切替日の翌日から)。"""
    out, i0 = [], None
    for i in range(1, n):
        if states[i] == "bear" and states[i - 1] != "bear":
            i0 = i
        elif states[i] != "bear" and states[i - 1] == "bear" and i0 is not None:
            out.append((i0, i))
            i0 = None
    return out


def gap(i0: int, i1: int) -> tuple[float, float, float]:
    comp = 1.0
    for k in range(i0 + 1, i1 + 1):
        comp *= 1 - rets[k]
    daily = comp - 1
    simple = -(px[i1] / px[i0] - 1)
    return daily - simple, daily, simple


def main() -> None:
    eps = episodes(base_states())
    rows = [(i0, i1, *gap(i0, i1)) for i0, i1 in eps]
    print(f"1571保有エピソード総数: {len(rows)}")

    def sel(a, b):
        return [r for r in rows if dt.date(*a) <= dates[r[0]] <= dt.date(*b)]

    it = sel((2000, 9, 1), (2003, 12, 31))
    lb = sel((2008, 9, 1), (2009, 12, 31))
    is_ = [r for r in rows if r[0] < split]
    g = lambda rs: [r[2] for r in rs]
    m_it, m_lb = st.mean(g(it)), st.mean(g(lb))
    sd_is = st.stdev(g(is_))
    print(f"ITバブル崩壊(2000-09〜2003) n={len(it)} 平均gap {m_it*100:+.3f}%")
    print(f"リーマン(2008-09〜2009)     n={len(lb)} 平均gap {m_lb*100:+.3f}%")
    print(f"IS期間 n={len(is_)} gap標準偏差 {sd_is*100:.3f}%  (平均 {st.mean(g(is_))*100:+.3f}%)")
    print(f"全エピソード平均gap {st.mean(g(rows))*100:+.3f}%  最小 {min(g(rows))*100:+.3f}%  最大 {max(g(rows))*100:+.3f}%")
    diff = m_it - m_lb
    ok = (diff < 0) and (abs(diff) > sd_is)
    print(f"差(IT−リーマン) {diff*100:+.3f}%pt、|差|>IS標準偏差か: {abs(diff) > sd_is}、マイナス方向か: {diff < 0}")
    print(f"段階①判定: {'合格' if ok else 'NO-GO'}")

    # 参考: 1571.T実価格
    try:
        e = close("1571.T")
        print(f"\n1571.T データ: {e.index[0].date()}〜{e.index[-1].date()} (n={len(e)})")
        devs = []
        for i0, i1, gp, daily, simple in rows:
            d0, d1 = pd.Timestamp(dates[i0]), pd.Timestamp(dates[i1])
            if d0 < e.index[0]:
                continue
            a = e[e.index <= d0]
            b = e[e.index <= d1]
            if len(a) == 0 or len(b) == 0 or a.index[-1] != d0 or b.index[-1] != d1:
                continue
            actual = b.iloc[-1] / a.iloc[-1] - 1
            devs.append((dates[i0], i1 - i0, actual, daily, actual - daily))
        if devs:
            dv = [x[4] for x in devs]
            hd = [x[1] for x in devs]
            print(f"実価格と照合できたエピソード n={len(devs)}、平均保有{st.mean(hd):.1f}営業日")
            print(f"実リターン−理論(日次-1倍) 平均 {st.mean(dv)*100:+.3f}%  中央値 {st.median(dv)*100:+.3f}%  "
                  f"標準偏差 {st.stdev(dv)*100:.3f}%  (1営業日あたり平均 {st.mean([x[4]/x[1] for x in devs])*100:+.4f}%)")
        else:
            print("実価格と照合できるエピソードなし")
    except Exception as ex:  # noqa: BLE001
        print(f"1571.T 取得失敗: {type(ex).__name__}")


if __name__ == "__main__":
    main()
