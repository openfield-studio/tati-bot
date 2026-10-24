#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#37: 複数のデッドクロス判定ペア(MA窓幅の組)の合意度で1571の比率を段階化する。

設計(状態の段階化型): ショック(-2.5%)・COOLDOWN15・利確5%・損切り18%・最大20日は現行のまま。
窓幅の組は既存120/350を中心に対称に±25%(90/263・120/350・150/438)で機械的に固定。
エントリー条件は「ショック かつ クールダウン明け かつ 少なくとも1組がデッドクロス」、
エントリー時の1571比率 = デッドクロスしている組数/3(エントリー時に固定、保有中は動かさない)、残りは1321。
利確・損切り・最大保有の判定は現行どおり日経の値動き(比率に依らない)。

事前登録(2026-10-24、計算前に固定):
 ① ITバブル崩壊期(現行ペアのデッドクロス開始が2000-04〜2001-12)で3組のデッドクロス開始日のばらつきが20営業日以上、
    リーマン期(開始が2008年 → 実装時に「2008-09-15を含む区間」へ特定方法のみ修正)で10営業日未満、かつその差がIS期間(前半65%)の各デッドクロス区間のばらつきの標準偏差より大きい。
    P7として最も早い組のデッドクロス開始日も報告し、2001-10-15(下落期間の中間)より前であること。
 ② 2000/2006/1965年開始の3シナリオ全てで現行を上回る(清算なし・清算ありの両方)
 ③ 対称スペーシングを±15%・±35%にしても3シナリオ全てプラス(清算なし・清算ありの両方)
 ④ 現行と異なるエントリー(比率が1未満、または現行にないエントリー)が50回以上、かつ損益上位2回を現行に戻してもプラス。
    あわせて改善を分解する(P9)。

部分配分はtati_evalのstates(単一レッグ)で表現できないため、1321と1571の2つの区画を別々に追跡する評価をここに書く。
比率1(全量)のときはtati_eval.evaluate()と一致することをassertで確認する。
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

px, rets, dates, n = C.px, C.rets, C.dates, C.n
n225 = C.n225
YEARS = (2000, 2006, 1965)
BASE_STATES = [(s, 1.0) for s in C.base_states()]
IS_END = int(n * 0.65)


def pairs_for(spacing: float) -> list[tuple[int, int]]:
    out = []
    for k in (1 - spacing, 1.0, 1 + spacing):
        out.append((round(120 * k), round(350 * k)))
    return out


def bear_series(fast: int, slow: int) -> list[bool]:
    f = n225.rolling(fast).mean().values
    s = n225.rolling(slow).mean().values
    return [(not pd.isna(f[i]) and not pd.isna(s[i]) and f[i] < s[i]) for i in range(n)]


def gen(bears: list[list[bool]], shock=-0.025, cooldown=15, tp=0.05, sl=0.18, max_hold=20):
    """日次の目標1571比率w[i](0〜1)と、エントリーの記録[(entry_i, exit_i, w, rr)]。"""
    k = len(bears)
    w = [0.0] * n
    trades = []
    holding, entry_i, last_shock, cur = False, 0, -10**9, 0.0
    for i in range(350, n):
        if holding:
            rr = -(px[i] / px[entry_i] - 1)
            if rr >= tp or rr <= -sl or i - entry_i >= max_hold:
                trades[-1] = (entry_i, i, cur, rr)
                holding, entry_i, cur = False, i, 0.0
        else:
            if rets[i] <= shock:
                cnt = sum(b[i] for b in bears)
                if (i - last_shock) >= cooldown and cnt > 0:
                    holding, entry_i, cur = True, i, cnt / k
                    trades.append((i, None, cur, None))
                last_shock = i
        w[i] = cur
    return w, trades


def evaluate_mix(w, start_year: int, principal: float = 9_181_229, cost: float = 0.002,
                 liquidate: bool = False, tax_rate: float = E.TAX_RATE) -> dict:
    """1321区画Lと1571区画Bを別々に追跡する。w[i]は日iの引け後の目標1571比率。"""
    si = next(i for i, d in enumerate(dates) if d >= dt.date(start_year, 1, 1))
    L, B = principal * (1 - w[si]), principal * w[si]
    bL, bB = L, B
    realized: dict[int, float] = {}
    peak, mdd, taxes, switches = principal, 0.0, 0.0, 0

    def sell(val, basis, a, y):
        nonlocal_cost = cost * a
        realized[y] = realized.get(y, 0.0) + (a - nonlocal_cost - basis * (a / val))
        return val - a, basis * (1 - a / val), a - nonlocal_cost

    for i in range(si + 1, n):
        y = dates[i].year
        L *= 1 + rets[i]
        B *= 1 - rets[i]
        if w[i] != w[i - 1]:
            eq = L + B
            target_b = w[i] * eq
            if target_b > B:
                a = min(L, target_b - B)
                L, bL, got = sell(L, bL, a, y)
                B += got
                bB += got
            else:
                a = min(B, B - target_b)
                B, bB, got = sell(B, bB, a, y)
                L += got
                bL += got
            switches += 1
        last_day = i == n - 1 or dates[i + 1].year != y
        if last_day:
            if liquidate and i == n - 1:
                for val, bas in ((L, bL), (B, bB)):
                    if val > 0:
                        realized[y] = realized.get(y, 0.0) + (val * (1 - cost) - bas)
                L, B = L * (1 - cost), B * (1 - cost)
                bL, bB = L, B
            tax = tax_rate * max(0.0, realized.get(y, 0.0))
            if tax > 0:
                f = tax / (L + B)
                L, B, bL, bB = L * (1 - f), B * (1 - f), bL * (1 - f), bB * (1 - f)
                taxes += tax
        eq = L + B
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    return {"equity": L + B, "mdd": mdd, "taxes": taxes, "switches": switches}


def base_w() -> list[float]:
    return [1.0 if s == "bear" else 0.0 for s, _ in BASE_STATES]


def pct(w, liq: bool) -> dict:
    wb = base_w()
    return {y: (evaluate_mix(w, y, liquidate=liq)["equity"] / evaluate_mix(wb, y, liquidate=liq)["equity"] - 1) * 100
            for y in YEARS}


def fmt(d: dict) -> str:
    return " / ".join(f"{d[y]:+.1f}%" for y in YEARS)


def self_check() -> None:
    wb = base_w()
    for y in YEARS:
        for liq in (False, True):
            a = evaluate_mix(wb, y, liquidate=liq)["equity"]
            b = E.evaluate(BASE_STATES, rets, dates, y, liquidate=liq)["equity"]
            assert abs(a / b - 1) < 1e-9, (y, liq, a, b)
    same = bear_series(120, 350)
    w, _ = gen([same, same, same])
    assert w == wb, "3組とも120/350でベースラインを再現できない"
    print("自己検証: 2区画評価=tati_eval(比率1)、3組とも120/350=現行 … 一致")


def onsets(b: list[bool]) -> list[int]:
    return [i for i in range(1, n) if b[i] and not b[i - 1]]


def stage1() -> bool:
    bears = [bear_series(f, s) for f, s in pairs_for(0.25)]
    base_on = onsets(bears[1])
    on_by = [onsets(b) for b in bears]

    def disp(k: int):
        idx = []
        for ons in on_by:
            cand = [j for j in ons if abs(j - k) <= 250]
            if not cand:
                return None, None
            idx.append(min(cand, key=lambda j: abs(j - k)))
        return max(idx) - min(idx), min(idx)

    rows = [(k, *disp(k)) for k in base_on]
    is_d = [d for k, d, _ in rows if k < IS_END and d is not None]
    sd = statistics.pstdev(is_d)
    print(f"現行ペアのデッドクロス開始 {len(base_on)}回、IS期間のばらつき: 平均{statistics.mean(is_d):.1f}営業日・標準偏差{sd:.1f}"
          f"(組が見つからない区間 {sum(1 for _, d, _ in rows if d is None)}件)")
    it = [(k, d, f) for k, d, f in rows if dt.date(2000, 4, 1) <= dates[k] <= dt.date(2001, 12, 31)]
    # リーマン期は「2008-09-15を含むデッドクロス区間」で特定する(事前登録の「開始が2008年」では、
    # 現行ペアの開始が2007-12-06のため区間が見つからなかった。閾値は変えず、区間の特定方法だけ直した)
    lehman = next(i for i, d in enumerate(dates) if d >= dt.date(2008, 9, 15))
    lb = [max(((k, d, f) for k, d, f in rows if k <= lehman), key=lambda r: r[0])]
    for name, lst in (("ITバブル", it), ("リーマン", lb)):
        for k, d, f in lst:
            print(f"  {name}: 現行開始 {dates[k]} ばらつき {d}営業日 最も早い組 {dates[f] if f is not None else None}")
    if not it or not lb or any(d is None for _, d, _ in it + lb):
        print("段階①: NO-GO(区間が特定できない)")
        return False
    d_it, d_lb = it[0][1], lb[0][1]
    first = dates[it[0][2]]
    ok = d_it >= 20 and d_lb < 10 and (d_it - d_lb) > sd and first < dt.date(2001, 10, 15)
    print(f"  基準: IT≥20({d_it}) リーマン<10({d_lb}) 差{d_it - d_lb}>IS標準偏差{sd:.1f} 最も早い組{first}<2001-10-15")
    print(f"段階①: {'合格' if ok else 'NO-GO'}")
    return ok


def run(spacing: float):
    bears = [bear_series(f, s) for f, s in pairs_for(spacing)]
    return gen(bears)


def stage2() -> bool:
    w, tr = run(0.25)
    a, b = pct(w, False), pct(w, True)
    print(f"\n段階② ±25%({pairs_for(0.25)})  清算なし {fmt(a)}  清算あり {fmt(b)}")
    ok = all(a[y] > 0 for y in YEARS) and all(b[y] > 0 for y in YEARS)
    print(f"段階②: {'合格' if ok else 'NO-GO'}")
    return ok


def stage3() -> bool:
    ok = True
    for sp in (0.15, 0.35):
        w, _ = run(sp)
        a, b = pct(w, False), pct(w, True)
        good = all(a[y] > 0 for y in YEARS) and all(b[y] > 0 for y in YEARS)
        ok &= good
        print(f"段階③ ±{sp*100:.0f}%({pairs_for(sp)})  清算なし {fmt(a)}  清算あり {fmt(b)}  {'OK' if good else 'NG'}")
    print(f"段階③: {'合格' if ok else 'NO-GO'}")
    return ok


def stage4() -> None:
    w, tr = run(0.25)
    wb = base_w()
    base_entries = {i for i in range(1, n) if wb[i] == 1.0 and wb[i - 1] == 0.0}
    diff = [t for t in tr if t[1] is not None and (t[2] < 1.0 or t[0] not in base_entries)]
    print(f"\n段階④ 現行と異なるエントリー: {len(diff)}回(基準50回以上)")
    by_w = pd.Series([round(t[2], 2) for t in tr if t[1] is not None]).value_counts().sort_index()
    print("  エントリー比率の内訳:", dict(by_w), f" 現行のエントリー {len(base_entries)}回")
    new_only = [t for t in tr if t[1] is not None and t[0] not in base_entries]
    kept = [t for t in tr if t[1] is not None and t[0] in base_entries]
    lost = sorted(base_entries - {t[0] for t in tr})
    print(f"  内訳: 現行にない新規 {len(new_only)}回(比率{sorted({round(t[2],2) for t in new_only})})、"
          f"現行と同日 {len(kept)}回(うち比率<1 {sum(1 for t in kept if t[2] < 1)}回)、現行にあって消えた {len(lost)}回")

    def comp(lst):
        g = 1.0
        for t in lst:
            g *= 1 + t[2] * t[3]
        return (g - 1) * 100
    print(f"  取引そのものの複利合計(比率加重): 新規 {comp(new_only):+.1f}%  同日 {comp(kept):+.1f}%")
    # P9分解: 新規エントリーだけ足す / 同日エントリーの比率縮小だけ
    w_new = list(wb)
    for t in new_only:
        if all(wb[i] == 0.0 for i in range(t[0], t[1])):
            for i in range(t[0], t[1]):
                w_new[i] = t[2]
    w_cut = list(wb)
    for t in kept:
        for i in range(t[0], t[1]):
            w_cut[i] = t[2]
    print(f"  分解(清算あり) 新規エントリーだけ追加: {fmt(pct(w_new, True))}")
    print(f"  分解(清算あり) 同日エントリーの比率縮小だけ: {fmt(pct(w_cut, True))}")
    top = sorted(diff, key=lambda t: t[2] * t[3], reverse=True)[:2]
    w2 = list(w)
    for t in top:
        for i in range(t[0], t[1]):
            w2[i] = wb[i]
    a = pct(w2, True)
    print(f"  上位2回({[str(dates[t[0]]) for t in top]})を現行に戻す(清算あり): {fmt(a)}")
    ok = len(diff) >= 50 and all(a[y] > 0 for y in YEARS)
    print(f"段階④: {'合格' if ok else 'NO-GO'}")


if __name__ == "__main__":
    self_check()
    if stage1() and stage2() and stage3():
        stage4()
