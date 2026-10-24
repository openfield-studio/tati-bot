#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#36: 切替のトランチング(段階的エントリー/エグジット)。
既存のショック検知+デッドクロス判定・COOLDOWN15・利確5%・損切り18%・最大20日は変えず、
1321⇔1571の切替を1日で100%ではなく、N営業日かけて1/Nずつ行う(エントリー・エグジット両方向)。

事前登録(キュー#36の記載どおり、計算前に固定):
 ① 現行の切替イベントのうち、切替日から5営業日以内に切替方向と逆へ2%以上動いたケースが20%以上
    (10%未満なら打ち切り。10〜20%は支持不足として不合格扱い)
 ② N=5で、2000/2006/1965年開始の3シナリオ全てが現行を上回る(清算なし・清算あり)
 ③ N=3・N=10でも3シナリオ全てプラス
 ④ ベアエントリー50回以上、かつ改善への寄与上位2エピソードを現行に戻してもプラス。P9分解も行う
利確/損切り判定は、実際に積み上がった1571部分(各トランチの取得値の平均)の損益で行う。
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io

import tati_eval as E

with contextlib.redirect_stdout(io.StringIO()):
    import copper_gold_filter_lab as C

px, rets, dates, bear, n = C.px, C.rets, C.dates, C.bear_regime, C.n
BASE = [(s, 1.0) for s in C.base_states()]
YEARS = (2000, 2006, 1965)
TAX = E.TAX_RATE


def gen(N: int, ma_slow=350, shock=-0.025, cooldown=15, tp=0.05, sl=0.18, max_hold=20):
    """b[i] = 日iの終値時点の1571比率(0〜1)。episodes: (エントリー日, エグジット判定日)"""
    b = [0.0] * n
    w, target = 0.0, 0.0
    tranches: list[tuple[float, float]] = []   # (追加比率, 追加日の日経)
    entry_i, last_shock = None, -10**9
    episodes = []
    for i in range(ma_slow, n):
        if target == 1.0:
            # 実際に保有している1571部分の損益(トランチ加重)
            tot = sum(q for q, _ in tranches)
            rr = sum(q * -(px[i] / p0 - 1) for q, p0 in tranches) / tot
            if rr >= tp or rr <= -sl or i - entry_i >= max_hold:
                target = 0.0
                episodes.append((entry_i, i))
                tranches = []
        else:
            is_shock = rets[i] <= shock
            if is_shock and (i - last_shock) >= cooldown and bear[i]:
                target, entry_i, last_shock = 1.0, i, i
                tranches = []
                if w > 0:   # エグジット途中の残り分は既存保有として引き継ぐ
                    tranches.append((w, px[i]))
            elif is_shock:
                last_shock = i
        if w < target:
            add = min(1.0 / N, target - w)
            w += add
            tranches.append((add, px[i]))
        elif w > target:
            w = max(target, w - 1.0 / N)
        w = round(w, 12)
        b[i] = w
    return b, episodes


def evaluate(b, start_year: int, principal=9_181_229, cost=0.002, liquidate=False) -> float:
    """混合レッグ版(tati_evalと同じ課税・コスト・清算)。部分売買は売った割合だけ損益を確定。"""
    si = next(i for i, d in enumerate(dates) if d >= dt.date(start_year, 1, 1))
    equity = basis = principal
    realized: dict[int, float] = {}
    for i in range(si + 1, n):
        y = dates[i].year
        equity *= 1 + (1 - 2 * b[i - 1]) * rets[i]
        d = abs(b[i] - b[i - 1])
        if d > 0:
            equity *= 1 - cost * d
            realized[y] = realized.get(y, 0.0) + d * (equity - basis)
            basis = (1 - d) * basis + d * equity
        if i == n - 1 or dates[i + 1].year != y:
            if liquidate and i == n - 1:
                equity *= 1 - cost
                realized[y] = realized.get(y, 0.0) + (equity - basis)
                basis = equity
            tax = TAX * max(0.0, realized.get(y, 0.0))
            if tax > 0:
                f = tax / equity
                equity -= tax
                basis *= 1 - f
    return equity


def pct(b, liq: bool, ref=None) -> dict:
    out = {}
    for y in YEARS:
        base = E.evaluate(BASE, rets, dates, y, liquidate=liq)["equity"] if ref is None else evaluate(ref, y, liquidate=liq)
        out[y] = (evaluate(b, y, liquidate=liq) / base - 1) * 100
    return out


def fmt(d: dict) -> str:
    return " / ".join(f"{d[y]:+.1f}%" for y in YEARS)


def self_check() -> None:
    b1, _ = gen(1)
    st = [("bear", 1.0) if x == 1.0 else ("long", 1.0) for x in b1]
    assert st == BASE, "N=1が現行の状態列と一致しない"
    for y in YEARS:
        for liq in (False, True):
            a = evaluate(b1, y, liquidate=liq)
            r = E.evaluate(BASE, rets, dates, y, liquidate=liq)["equity"]
            assert abs(a / r - 1) < 1e-9, (y, liq, a, r)
    print("自己検証: N=1はtati_eval.evaluateの現行ベースラインと一致")


def stage1() -> bool:
    sw = [i for i in range(1, n) if BASE[i] != BASE[i - 1]]
    bad_e = bad_x = ne = nx = 0
    for i in sw:
        if i + 5 >= n:
            continue
        fut = px[i + 1:i + 6]
        if BASE[i][0] == "bear":
            ne += 1
            bad_e += max(fut) / px[i] - 1 >= 0.02
        else:
            nx += 1
            bad_x += min(fut) / px[i] - 1 <= -0.02
    tot, bad = ne + nx, bad_e + bad_x
    r = bad / tot * 100
    print(f"段階① 切替{tot}件(ベア入り{ne}・戻り{nx})のうち5営業日以内に逆方向2%以上: {bad}件 = {r:.1f}%")
    print(f"  内訳: ベア入り {bad_e}/{ne} = {bad_e/ne*100:.1f}%、戻り {bad_x}/{nx} = {bad_x/nx*100:.1f}%")
    ok = r >= 20
    print(f"段階①: {'合格' if ok else 'NO-GO'}(基準20%以上)")
    return ok


def stage2() -> bool:
    b, _ = gen(5)
    a, c = pct(b, False), pct(b, True)
    print(f"\n段階② N=5  清算なし {fmt(a)}  清算あり {fmt(c)}")
    ok = all(a[y] > 0 for y in YEARS) and all(c[y] > 0 for y in YEARS)
    print(f"段階②: {'合格' if ok else 'NO-GO'}")
    return ok


def stage3() -> bool:
    ok = True
    for N in (3, 10):
        b, _ = gen(N)
        a, c = pct(b, False), pct(b, True)
        g = all(a[y] > 0 for y in YEARS) and all(c[y] > 0 for y in YEARS)
        ok &= g
        print(f"段階③ N={N}  清算なし {fmt(a)}  清算あり {fmt(c)}  {'OK' if g else 'NG'}")
    print(f"段階③: {'合格' if ok else 'NO-GO'}")
    return ok


def stage4() -> None:
    b5, ep = gen(5)
    b1, ep1 = gen(1)
    print(f"\n段階④ ベアエントリー: N=5 {len(ep)}回 / 現行 {len(ep1)}回(基準50回以上)")
    # エピソードごとの寄与: そのエピソード区間(エントリー〜エグジット後N日)だけN=5、他は現行
    contrib = []
    for (s, e) in ep:
        hyb = list(b1)
        for i in range(s, min(n, e + 6)):
            hyb[i] = b5[i]
        contrib.append(((s, e), (evaluate(hyb, 1965, liquidate=True) / evaluate(b1, 1965, liquidate=True) - 1) * 100))
    contrib.sort(key=lambda x: x[1], reverse=True)
    for (s, e), v in contrib[:3]:
        print(f"  寄与上位 {dates[s]}〜{dates[e]} {v:+.2f}%")
    for (s, e), v in contrib[-3:]:
        print(f"  寄与下位 {dates[s]}〜{dates[e]} {v:+.2f}%")
    pos = sum(1 for _, v in contrib if v > 0)
    print(f"  寄与プラスのエピソード {pos}/{len(contrib)}")
    st2 = list(b5)
    for (s, e), _ in contrib[:2]:
        for i in range(s, min(n, e + 6)):
            st2[i] = b1[i]
    a = pct(st2, True)
    print(f"  上位2エピソードを現行に戻す(清算あり): {fmt(a)}")
    # P9分解: 保有期間・終了理由の変化
    same = sum(1 for x, y in zip(ep, ep1) if x == y)
    print(f"  エントリー日・エグジット日が現行と同じエピソード: {same}/{len(ep)}")
    hold5 = sum(e - s for s, e in ep) / len(ep)
    hold1 = sum(e - s for s, e in ep1) / len(ep1)
    print(f"  平均保有日数(エントリー〜エグジット判定): N=5 {hold5:.1f}日 / 現行 {hold1:.1f}日")
    expo5 = sum(b5) / n
    expo1 = sum(b1) / n
    print(f"  1571平均比率: N=5 {expo5*100:.2f}% / 現行 {expo1*100:.2f}%")
    ok = len(ep) >= 50 and all(a[y] > 0 for y in YEARS)
    print(f"段階④: {'合格' if ok else 'NO-GO'}")


if __name__ == "__main__":
    self_check()
    if stage1() and stage2() and stage3():
        stage4()
