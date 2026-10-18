#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#33: 米国VIXの水準(>30、1営業日ラグ)をデッドクロス中のショック判定の追加条件にする。
reevaluate_tax_fix.py の再評価中に偶然見つかった事後の発見を、事前登録した基準で検証する。

設計(追加トリガー型、reevaluate_tax_fix.pyのextra_levelと同一): デッドクロス中に
「日経の前日比-2.5%以下」または「前日の米国VIX終値>閾値」で1571へ(COOLDOWN15・利確5%・損切り18%・最大20日は現行のまま)。
事前登録(2026-10-18、計算前にユーザーへ提示):
 ① ITバブル崩壊期のデッドクロス中にVIX>30の日が20日以上、かつ初出が2001-10-15(下落期間2000-04〜2003-03の中間)より前
 ② 2000/2006/1965年開始の3シナリオ全てで現行を上回る(tati_eval、清算なし・清算ありの両方)
 ③ 閾値25・35、およびVIXを2営業日ラグにしても3シナリオ全てプラス
 ④ VIX起因の追加エントリーが50回以上、かつ損益上位2回を除いてもプラス
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import sys

import pandas as pd
import yfinance as yf

import tati_eval as E

with contextlib.redirect_stdout(io.StringIO()):
    import copper_gold_filter_lab as C
    import reevaluate_tax_fix as R

px, rets, dates, bear, n = C.px, C.rets, C.dates, C.bear_regime, C.n
BASE = [(s, 1.0) for s in C.base_states()]
YEARS = (2000, 2006, 1965)

_vix = yf.Ticker("^VIX").history(period="max")["Close"].dropna()
_vix.index = pd.to_datetime(_vix.index.date)


def vix_on_jp(lag: int) -> list:
    s = _vix.shift(lag).reindex(pd.to_datetime(dates), method="ffill")
    return [None if pd.isna(v) else float(v) for v in s.values]


def gen(extra, ma_slow=350, shock=-0.025, cooldown=15, tp=0.05, sl=0.18, max_hold=20):
    """reevaluate_tax_fix.gen_switchesと同じロジック+エントリー理由の記録。"""
    events, reasons = [(0, "long")], []
    holding, entry_i, last_shock = "long", 0, -10**9
    for i in range(ma_slow, n):
        if holding == "bear":
            rr = -(px[i] / px[entry_i] - 1)
            if rr >= tp or rr <= -sl or i - entry_i >= max_hold:
                events.append((i, "long"))
                reasons[-1] = (*reasons[-1][:2], i, rr)
                holding, entry_i = "long", i
        else:
            is_shock = rets[i] <= shock
            trig = is_shock or (extra is not None and extra[i])
            if trig and (i - last_shock) >= cooldown and bear[i]:
                events.append((i, "bear"))
                reasons.append(("shock" if is_shock else "vix", i, None, None))
                holding, entry_i, last_shock = "bear", i, i
            elif trig:
                last_shock = i
    return events, reasons


def states_for(thr: float, lag: int):
    v = vix_on_jp(lag)
    extra = [x is not None and x > thr for x in v]
    ev, rs = gen(extra)
    return E.events_to_states(ev, n), rs, v


def pct(states, liq: bool) -> dict:
    out = {}
    for y in YEARS:
        b = E.evaluate(BASE, rets, dates, y, liquidate=liq)["equity"]
        c = E.evaluate(states, rets, dates, y, liquidate=liq)["equity"]
        out[y] = (c / b - 1) * 100
    return out


def fmt(d: dict) -> str:
    return " / ".join(f"{d[y]:+.1f}%" for y in YEARS)


def stage1() -> bool:
    v = vix_on_jp(1)
    a, b = dt.date(2000, 4, 1), dt.date(2003, 3, 31)
    days = [i for i in range(n) if a <= dates[i] <= b and bear[i] and v[i] is not None and v[i] > 30]
    first = dates[days[0]] if days else None
    print(f"ITバブル崩壊期(2000-04〜2003-03)のデッドクロス中でVIX>30の日: {len(days)}日")
    by_m = pd.Series(1, index=[dates[i] for i in days]).groupby(lambda d: f"{d.year}-{d.month:02d}").sum()
    print("  月別:", dict(by_m))
    print(f"  初出: {first}(基準: 2001-10-15より前)")
    ok = len(days) >= 20 and first is not None and first < dt.date(2001, 10, 15)
    print(f"段階①: {'合格' if ok else 'NO-GO'}")
    return ok


def stage2() -> bool:
    st, rs, _ = states_for(30, 1)
    ref = E.events_to_states(R.gen_switches(px, rets, bear, [x is not None and x > 30 for x in vix_on_jp(1)]), n)
    assert st == ref, "reevaluate_tax_fix.pyの実装と一致しない"
    a, b = pct(st, False), pct(st, True)
    print(f"\n段階② 閾値30・1日ラグ  清算なし {fmt(a)}  清算あり {fmt(b)}")
    ok = all(a[y] > 0 for y in YEARS) and all(b[y] > 0 for y in YEARS)
    print(f"段階②: {'合格' if ok else 'NO-GO'}")
    return ok


def stage3() -> bool:
    ok = True
    for thr, lag in ((25, 1), (35, 1), (30, 2)):
        st, _, _ = states_for(thr, lag)
        a, b = pct(st, False), pct(st, True)
        good = all(a[y] > 0 for y in YEARS) and all(b[y] > 0 for y in YEARS)
        ok &= good
        print(f"段階③ 閾値{thr}・{lag}日ラグ  清算なし {fmt(a)}  清算あり {fmt(b)}  {'OK' if good else 'NG'}")
    print(f"段階③: {'合格' if ok else 'NO-GO'}")
    return ok


def stage4() -> None:
    st, rs, _ = states_for(30, 1)
    vix_trades = [r for r in rs if r[0] == "vix" and r[2] is not None]
    print(f"\n段階④ VIX起因の追加エントリー: {len(vix_trades)}回(基準50回以上)")
    wins = sorted(vix_trades, key=lambda r: r[3], reverse=True)
    for r in wins[:5]:
        print(f"  上位 {dates[r[1]]}〜{dates[r[2]]} {r[3]*100:+.1f}%")
    top2 = {r[1] for r in wins[:2]}
    st2 = list(st)
    for r in vix_trades:
        if r[1] in top2:
            for i in range(r[1], r[2]):
                st2[i] = BASE[i]
    a = pct(st2, True)
    print(f"  上位2回を現行の状態に戻した場合(清算あり): {fmt(a)}")
    yrs = pd.Series([dates[r[1]].year for r in vix_trades]).value_counts().sort_index()
    print("  年別回数:", dict(yrs))
    ok = len(vix_trades) >= 50 and all(a[y] > 0 for y in YEARS)
    print(f"段階④: {'合格' if ok else 'NO-GO'}")


if __name__ == "__main__":
    if stage1() and stage2() and stage3():
        stage4()
