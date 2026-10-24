#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#39: regime_shift全体への資金配分比率fをリスク制約付きケリー(Busseti, Ryu & Boyd 2016)で
IS期間に1回だけ決めて固定し、残り(1-f)を1321の単純買い持ちにするコア・サテライト設計。

設計(静的配分): 2口座(principal×f で現行戦略、principal×(1-f) で常時1321)を別々に tati_eval と同じ
課税ロジックで評価し、日々の評価額を合算する(以後の再リバランスなし)。
fの算出: IS期間(全データの前半65%)の日次グロスリターン R(f)=f·Ra+(1-f)·Rp について
  max E[log R(f)]  s.t.  E[R(f)^-λ] ≤ 1,  λ = log(β)/log(α)  (α=0.7, β=10%: 資産が0.7倍以下に落ちる確率≤10%)
fは1次元なので0〜1を0.001刻みでグリッド探索(cvxpy不要)。
事前登録(キュー#39の行に記載の基準を数値化):
 ① ISで求めたfが0.3〜0.9(0や1に近い退化解でない)
 ② 2000/2006/1965年開始の3シナリオ全て(清算なし・清算あり)で、合算の最大下落率が現行単独より20%以上(相対)縮小
    (参考としてCalmar、OOS区間のみの最大下落率も表示)
 ③ 隣接設定 α=0.6/0.8、β=5%/20%、およびIS開始年を2000/2006年にしても、fが0.3〜0.9かつ②の条件を満たす
 ④ P9分解: f×現行+(1-f)×1321 のCalmarが f×現行+(1-f)×現金 のCalmarを3シナリオ全てで上回る
    (下回るなら、下落率の縮小は資金を減らしただけの効果で、1321に分けた意味がない)
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import math

import numpy as np

import tati_eval as E

with contextlib.redirect_stdout(io.StringIO()):
    import copper_gold_filter_lab as C

px, rets, dates, n = C.px, C.rets, C.dates, C.n
ACTIVE = [(s, 1.0) for s in C.base_states()]
PASSIVE = [("long", 1.0)] * n
CASH = [("long", 0.0)] * n
YEARS = (2000, 2006, 1965)
PRINCIPAL = 9_181_229
IS_END = int(n * 0.65)


def eval_series(states, start_year, principal, liquidate=False):
    """tati_eval.evaluateと同一ロジック(carryforwardなし)で日次評価額の列を返す。"""
    si = next(i for i, d in enumerate(dates) if d >= dt.date(start_year, 1, 1))
    equity = basis = principal
    realized: dict[int, float] = {}
    out = {si: equity}
    for i in range(si + 1, n):
        y = dates[i].year
        leg, w = states[i - 1]
        equity *= 1 + (rets[i] * w if leg == "long" else -rets[i] * w)
        if states[i] != states[i - 1]:
            equity *= 1 - 0.002 * E._turnover(states[i - 1], states[i], rets[i])
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
        out[i] = equity
    return out


def stats(series: dict, from_i: int | None = None):
    ks = sorted(k for k in series if from_i is None or k >= from_i)
    v = np.array([series[k] for k in ks])
    peak = np.maximum.accumulate(v)
    mdd = float(np.max(1 - v / peak))
    yrs = (dates[ks[-1]] - dates[ks[0]]).days / 365.25
    cagr = (v[-1] / v[0]) ** (1 / yrs) - 1
    return mdd, cagr, (cagr / mdd if mdd > 0 else float("inf")), v[-1]


def combo(f, other, y, liq):
    a = eval_series(ACTIVE, y, PRINCIPAL * f, liq)
    b = eval_series(other, y, PRINCIPAL * (1 - f), liq)
    return {k: a[k] + b[k] for k in a}


def daily_gross(states, lo, hi):
    out = []
    for i in range(lo + 1, hi):
        leg, w = states[i - 1]
        out.append(1 + (rets[i] * w if leg == "long" else -rets[i] * w))
    return np.array(out)


def rck_f(alpha=0.7, beta=0.10, is_start_year=1965):
    lo = next(i for i, d in enumerate(dates) if d >= dt.date(is_start_year, 1, 1))
    ra, rp = daily_gross(ACTIVE, lo, IS_END), daily_gross(PASSIVE, lo, IS_END)
    lam = math.log(beta) / math.log(alpha)
    best, best_g = None, -1e9
    for f in np.arange(0, 1.0005, 0.001):
        r = f * ra + (1 - f) * rp
        if np.mean(r ** -lam) <= 1 and np.mean(np.log(r)) > best_g:
            best, best_g = float(f), float(np.mean(np.log(r)))
    return best, lam


def check2(f, label=""):
    ok = True
    for liq in (False, True):
        cells = []
        for y in YEARS:
            ma, ca, cala, _ = stats(eval_series(ACTIVE, y, PRINCIPAL, liq))
            mc, cc, calc, _ = stats(combo(f, PASSIVE, y, liq))
            moa, _, _, _ = stats(eval_series(ACTIVE, y, PRINCIPAL, liq), IS_END)
            moc, _, _, _ = stats(combo(f, PASSIVE, y, liq), IS_END)
            red = 1 - mc / ma
            ok &= red >= 0.20
            cells.append(f"{y}: MDD {ma*100:.1f}%→{mc*100:.1f}%(縮小{red*100:+.1f}%) Calmar {cala:.3f}→{calc:.3f}"
                         f" OOS-MDD {moa*100:.1f}%→{moc*100:.1f}%")
        print(f"  {label}{'清算あり' if liq else '清算なし'}  " + " | ".join(cells))
    return ok


def main():
    print(f"IS期間: {dates[0]}〜{dates[IS_END-1]}(前半65%)、OOS: {dates[IS_END]}〜{dates[-1]}")
    f, lam = rck_f()
    print(f"\n段階① α=0.7 β=10% λ={lam:.3f} → f={f}")
    if f is None or not (0.3 <= f <= 0.9):
        print("段階①: NO-GO(fが0.3〜0.9の範囲外=退化解)")
        # 参考: 制約なしケリー解と、制約を満たすfの範囲
        lo = 0
        ra, rp = daily_gross(ACTIVE, lo, IS_END), daily_gross(PASSIVE, lo, IS_END)
        g = [(float(x), float(np.mean(np.log(x * ra + (1 - x) * rp))), float(np.mean((x * ra + (1 - x) * rp) ** -lam)))
             for x in np.arange(0, 1.0001, 0.1)]
        for x, gg, cc in g:
            print(f"   参考 f={x:.1f}  E[logR]={gg*1e4:.3f}bp/日  E[R^-λ]={cc:.5f}")
        return
    print("段階①: 合格")
    print("\n段階②")
    if not check2(f):
        print("段階②: NO-GO")
        return
    print("段階②: 合格")
    print("\n段階③")
    ok = True
    for a, b, isy in ((0.6, 0.10, 1965), (0.8, 0.10, 1965), (0.7, 0.05, 1965), (0.7, 0.20, 1965),
                      (0.7, 0.10, 2000), (0.7, 0.10, 2006)):
        ff, _ = rck_f(a, b, isy)
        good = ff is not None and 0.3 <= ff <= 0.9
        print(f" α={a} β={b} IS開始{isy} → f={ff}")
        if good:
            good &= check2(ff, "   ")
        ok &= good
        print(f"   {'OK' if good else 'NG'}")
    print(f"段階③: {'合格' if ok else 'NO-GO'}")
    if not ok:
        return
    print("\n段階④ P9分解(清算あり)")
    ok = True
    for y in YEARS:
        m1, _, c1, e1 = stats(combo(f, PASSIVE, y, True))
        m0, _, c0, e0 = stats(combo(f, CASH, y, True))
        ok &= c1 > c0
        print(f"  {y}: 残り1321 MDD {m1*100:.1f}% Calmar {c1:.3f} / 残り現金 MDD {m0*100:.1f}% Calmar {c0:.3f}")
    print(f"段階④: {'合格' if ok else 'NO-GO'}")


if __name__ == "__main__":
    # tati_evalとの一致確認
    for y in YEARS:
        for liq in (False, True):
            s = eval_series(ACTIVE, y, PRINCIPAL, liq)
            ref = E.evaluate(ACTIVE, rets, dates, y, liquidate=liq)["equity"]
            assert abs(s[n - 1] - ref) < 1e-6 * ref, (y, liq)
    main()
