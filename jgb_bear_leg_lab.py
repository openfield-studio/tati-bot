#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#35: デッドクロス中のベア側保有資産を1571(日経-1倍)から長期国債(JGB)の近似トータルリターンに差し替える。

設計(保有資産の差し替えのみ、タイミング不変):
  ショック検知(-2.5%)・デッドクロス(MA120/350)・COOLDOWN15・利確5%/損切り18%/最大20日は現行のまま。
  利確・損切りの判定は現行どおり日経の値動き(1571相当の損益)で行い、切替日は現行と完全に同じ。
  その期間に持つ資産だけを1571→JGB近似TRに替える(JGBの損益で利確損切りを判定する案は別物として扱わない)。
  JGB近似TR = 前日利回り/245 − D×Δ利回り(財務省jgbcm_all.csv、10年、無い時期は9年。#31と同じ。D=8.5)。
  財務省データは1974年〜(10年金利は1986年〜)のため、1965年開始シナリオは不可。2000/2006年開始のみ。

事前登録(2026-10-24、計算前に固定):
 ① キュー#35の記載どおり: ITバブル崩壊期(2000-09〜2003-12に掛かるデッドクロス区間)の
    JGB近似TRの複利リターンが日経-1倍の複利リターンを上回り、その差がIS期間(全期間の前半65%)中の
    各デッドクロス区間における「JGB−日経-1倍」の複利リターン差の標準偏差より大きい。
    かつ、その優位がリーマン期(2008年のデッドクロス区間)の優位より大きい(じわじわ型でより有利)。
 ② 2000/2006年開始の両方で現行を上回る(tati_eval方式、清算なし・清算ありの両方)
 ③ 修正デュレーション6.5・10.5でも②の4つが全てプラス
 ④ 差し替えた取引(2000年以降)が50回以上、かつ改善寄与上位2回を現行に戻してもプラス。
    P9分解: 同じ期間を現金(リターン0)にした場合と比べ、改善がJGBのリターンから来ているか、
    単に1571の損を避けただけかを示す(判定には使わず報告のみ)。
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import statistics

import pandas as pd

import tati_eval as E

with contextlib.redirect_stdout(io.StringIO()):
    import copper_gold_filter_lab as C
    import permanent_portfolio_lab as P
    import reevaluate_tax_fix as R

px, rets, dates, bear, n = C.px, C.rets, C.dates, C.bear_regime, C.n
BASE = [(s, 1.0) for s in C.base_states()]
YEARS = (2000, 2006)


def jgb_rets(dur: float) -> list[float]:
    """日経の営業日に合わせたJGB近似TRの日次リターン(財務省データの無い日は0)。"""
    with contextlib.redirect_stdout(io.StringIO()):
        P.jgb_series()  # CSVのキャッシュ
    old = P.MOD_DUR
    P.MOD_DUR = dur
    try:
        r = P.jgb_series()
    finally:
        P.MOD_DUR = old
    idx = (1 + r).cumprod()
    idx = idx.reindex(idx.index.union(pd.to_datetime(dates))).ffill().reindex(pd.to_datetime(dates))
    out = idx.pct_change().values
    return [0.0 if pd.isna(v) else float(v) for v in out]


def evaluate3(states, jr, start_year, liquidate=False):
    """tati_eval.evaluate(新方式)と同じ課税ロジックで、第3レッグ'jgb'に対応。"""
    si = next(i for i, d in enumerate(dates) if d >= dt.date(start_year, 1, 1))
    equity = basis = 9_181_229.0
    realized: dict[int, float] = {}
    for i in range(si + 1, n):
        y = dates[i].year
        leg = states[i - 1][0]
        r = rets[i] if leg == "long" else (-rets[i] if leg == "bear" else jr[i])
        equity *= 1 + r
        if states[i] != states[i - 1]:
            equity *= 1 - 0.002
            realized[y] = realized.get(y, 0.0) + (equity - basis)
            basis = equity
        if i == n - 1 or dates[i + 1].year != y:
            if liquidate and i == n - 1:
                equity *= 1 - 0.002
                realized[y] = realized.get(y, 0.0) + (equity - basis)
                basis = equity
            tax = E.TAX_RATE * max(0.0, realized.get(y, 0.0))
            if tax > 0:
                f = tax / equity
                equity -= tax
                basis *= 1 - f
    return equity


def replace(states, new_leg, keep=frozenset()):
    """'bear'の区間をnew_legに替える。keepに入った取引(開始日)は現行のまま。"""
    out, start = list(states), None
    for i in range(n):
        if states[i][0] == "bear":
            if start is None:
                start = i
            if start not in keep:
                out[i] = (new_leg, 1.0)
        else:
            start = None
    return out


def trades(states):
    res, i = [], 0
    while i < n:
        if states[i][0] == "bear":
            j = i
            while j < n and states[j][0] == "bear":
                j += 1
            res.append((i, j))  # 日i〜j-1の状態がbear → リターンは日i+1〜jに効く
            i = j
        else:
            i += 1
    return res


def pct(states, jr):
    out = {}
    for y in YEARS:
        for liq in (False, True):
            b = evaluate3(BASE, jr, y, liq)
            c = evaluate3(states, jr, y, liq)
            out[(y, liq)] = (c / b - 1) * 100
    return out


def fmt(d):
    return " / ".join(f"{y}{'清算' if liq else ''} {v:+.1f}%" for (y, liq), v in d.items())


def comp(series, a, b):
    v = 1.0
    for k in range(a + 1, b + 1):
        v *= 1 + series[k]
    return v - 1


def runs():
    out, i = [], 0
    while i < n:
        if bear[i]:
            j = i
            while j < n and bear[j]:
                j += 1
            out.append((i, j - 1))
            i = j
        else:
            i += 1
    return out


def stage1(jr) -> bool:
    inv = [-r for r in rets]
    is_end = dates[int(n * 0.65)]
    jgb_start = next(i for i in range(n) if jr[i] != 0.0)
    print(f"JGB近似TRの有効開始: {dates[jgb_start]} / IS終了: {is_end}")
    diffs = []
    for a, b in runs():
        if a > jgb_start and dates[b] <= is_end and b - a >= 20:
            diffs.append(comp(jr, a, b) - comp(inv, a, b))
    sd = statistics.pstdev(diffs)
    print(f"IS期間のデッドクロス区間(20日以上、JGBデータあり) {len(diffs)}区間、差の標準偏差 {sd*100:.1f}pt")

    def period(lo, hi, label):
        sel = [(a, b) for a, b in runs() if dates[b] >= lo and dates[a] <= hi and b - a >= 20]
        j = v = 1.0
        for a, b in sel:
            j *= 1 + comp(jr, a, b)
            v *= 1 + comp(inv, a, b)
        days = sum(b - a + 1 for a, b in sel)
        print(f"  {label}: 区間{len(sel)}個・延べ{days}日  JGB {(j-1)*100:+.1f}%  日経-1倍 {(v-1)*100:+.1f}%  差 {(j-v)*100:+.1f}pt")
        for a, b in sel:
            print(f"     {dates[a]}〜{dates[b]}  JGB {comp(jr,a,b)*100:+.1f}%  日経-1倍 {comp(inv,a,b)*100:+.1f}%")
        return j - v

    it = period(dt.date(2000, 9, 1), dt.date(2003, 12, 31), "ITバブル崩壊期")
    lm = period(dt.date(2008, 1, 1), dt.date(2008, 12, 31), "リーマン期")
    # 参考(判定外): 実際に1571を持った取引期間だけで比べる
    tr = [t for t in trades(BASE) if dates[t[0]] >= dt.date(2000, 1, 1)]
    j = v = 1.0
    for a, b in tr:
        j *= 1 + comp(jr, a, b)
        v *= 1 + comp(inv, a, b)
    print(f"  参考: 2000年以降の実際の1571保有期間({len(tr)}回)の複利  JGB {(j-1)*100:+.1f}%  日経-1倍 {(v-1)*100:+.1f}%")
    ok = it > 0 and it > sd and it > lm
    print(f"段階①: {'合格' if ok else 'NO-GO'}(条件: 差>0 かつ 差>{sd*100:.1f}pt かつ ITバブル差>リーマン差)")
    return ok


def stage2(jr) -> bool:
    st = replace(BASE, "jgb")
    a = pct(st, jr)
    print(f"\n段階② D=8.5  {fmt(a)}")
    ok = all(v > 0 for v in a.values())
    print(f"段階②: {'合格' if ok else 'NO-GO'}")
    return ok


def stage3() -> bool:
    ok = True
    for d in (6.5, 10.5):
        a = pct(replace(BASE, "jgb"), jgb_rets(d))
        g = all(v > 0 for v in a.values())
        ok &= g
        print(f"段階③ D={d}  {fmt(a)}  {'OK' if g else 'NG'}")
    print(f"段階③: {'合格' if ok else 'NO-GO'}")
    return ok


def stage4(jr) -> None:
    inv = [-r for r in rets]
    tr = [t for t in trades(BASE) if dates[t[0]] >= dt.date(2000, 1, 1)]
    gain = sorted(tr, key=lambda t: comp(jr, *t) - comp(inv, *t), reverse=True)
    print(f"\n段階④ 差し替えた取引(2000年以降): {len(tr)}回(基準50回以上)")
    for a, b in gain[:3]:
        print(f"  寄与上位 {dates[a]}〜{dates[b]}  JGB {comp(jr,a,b)*100:+.1f}%  1571 {comp(inv,a,b)*100:+.1f}%")
    top2 = {t[0] for t in gain[:2]}
    a = pct(replace(BASE, "jgb", keep=frozenset(top2)), jr)
    print(f"  上位2回を1571のままにした場合: {fmt(a)}")
    wins = sum(comp(jr, *t) > comp(inv, *t) for t in tr)
    print(f"  JGBが1571を上回った取引: {wins}/{len(tr)}")
    cash = pct(replace(BASE, "cash"), [0.0] * n)
    jg = pct(replace(BASE, "jgb"), jr)
    print(f"  P9分解: 現金に替えただけ {fmt(cash)}")
    print(f"          JGBに替えた     {fmt(jg)}")
    ok = len(tr) >= 50 and all(v > 0 for v in a.values())
    print(f"段階④: {'合格' if ok else 'NO-GO'}")


def check_baseline(jr):
    for y in YEARS:
        for liq in (False, True):
            a = evaluate3(BASE, jr, y, liq)
            b = E.evaluate(BASE, rets, dates, y, liquidate=liq)["equity"]
            assert abs(a / b - 1) < 1e-9, (y, liq, a, b)
    st0 = E.events_to_states(R.gen_switches(px, rets, bear), n)
    assert st0 == BASE


if __name__ == "__main__":
    jr = jgb_rets(8.5)
    check_baseline(jr)
    print("ベースライン一致(tati_eval.evaluate)\n")
    if stage1(jr) and stage2(jr) and stage3():
        stage4(jr)
