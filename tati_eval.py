# -*- coding: utf-8 -*-
"""研究用ラボ共通の課税考慮バックテスト評価(2026-10-16)。

旧来の各ラボのevaluate()は年末納税時に取得単価を時価へリセットしており
(`last_eq = equity`)、最終売買から年末までの含み益が以後課税されなかった。
本モジュールは取得単価を正しく追跡する。legacy=Trueで旧方式を再現できる。

states[i] = (leg, weight)  leg: 'long'(1321相当=日経) / 'bear'(1571相当=日経の日次-1倍)
                           weight: 0〜1(残りは現金・金利0)。日iのリターンには states[i-1] を使う。
状態が変わった日に、その時点の評価額で全量を売買したものとして損益を確定する(既存ラボと同じ近似)。
"""
from __future__ import annotations

import datetime as dt

TAX_RATE = 0.20315


def events_to_states(events, n: int) -> list[tuple[str, float]]:
    """qar_rebound_lab型の切替イベント[(i, 'long'|'bear'), ...]を日次状態列に変換。"""
    ev = sorted(events)
    out, cur, k = [], "long", 0
    for i in range(n):
        while k < len(ev) and ev[k][0] == i:
            cur = ev[k][1]
            k += 1
        out.append((cur, 1.0))
    return out


def _turnover(prev, cur, r_today: float) -> float:
    pl, pw = prev
    cl, cw = cur
    if pl != cl:
        return max(pw, cw)
    return abs(cw - pw)


def evaluate(states, rets, dates, start_year: int, principal: float = 9_181_229,
             cost: float = 0.002, carryforward: bool = False, liquidate: bool = False,
             legacy: bool = False) -> dict:
    n = len(rets)
    si = next(i for i, d in enumerate(dates) if d >= dt.date(start_year, 1, 1))
    equity = basis = principal
    realized: dict[int, float] = {}
    carry: list[list] = []
    peak, mdd, taxes, switches = equity, 0.0, 0.0, 0
    for i in range(si + 1, n):
        y = dates[i].year
        leg, w = states[i - 1]
        equity *= 1 + (rets[i] * w if leg == "long" else -rets[i] * w)
        if states[i] != states[i - 1]:
            equity *= 1 - cost * _turnover(states[i - 1], states[i], rets[i])
            realized[y] = realized.get(y, 0.0) + (equity - basis)
            basis = equity
            switches += 1
        last_day = i == n - 1 or dates[i + 1].year != y
        if last_day:
            if liquidate and i == n - 1 and not legacy:
                equity *= 1 - cost
                realized[y] = realized.get(y, 0.0) + (equity - basis)
                basis = equity
            net = realized.get(y, 0.0)
            if carryforward and not legacy:
                carry = [c for c in carry if y - c[0] <= 3 and c[1] > 0]
                for c in carry:
                    if net <= 0:
                        break
                    use = min(c[1], net)
                    c[1] -= use
                    net -= use
                if net < 0:
                    carry.append([y, -net])
            tax = TAX_RATE * max(0.0, net)
            if tax > 0:
                if legacy:
                    equity -= tax
                    basis = equity            # 旧方式のバグ(取得単価を時価へリセット)
                else:
                    f = tax / equity
                    equity -= tax
                    basis *= 1 - f            # 納税分だけ保有を減らす=取得単価も同率で減る
                taxes += tax
        peak = max(peak, equity)
        mdd = max(mdd, 1 - equity / peak)
    return {"equity": equity, "mdd": mdd, "taxes": taxes, "switches": switches}


def compare(states_base, states_new, rets, dates, years=(2000, 2006, 1965)) -> dict:
    """旧方式・新方式(清算なし)・新方式(清算あり)での、新案の現行比変化率(%)。"""
    out = {}
    for mode, kw in (("legacy", {"legacy": True}), ("new", {}), ("new_liq", {"liquidate": True}),
                     ("new_liq_carry", {"liquidate": True, "carryforward": True})):
        row = {}
        for y in years:
            b = evaluate(states_base, rets, dates, y, **kw)["equity"]
            c = evaluate(states_new, rets, dates, y, **kw)["equity"]
            row[y] = (c / b - 1) * 100
        out[mode] = row
    return out
