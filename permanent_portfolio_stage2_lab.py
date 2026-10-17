#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調査待ちキュー#31(4資産均等、Permanent Portfolio型)の段階②〜④。段階①は permanent_portfolio_lab.py(合格)。

事前登録(2026-10-16、計算前にユーザーへ提示):
  税計算は取得単価を追跡する正しい方式(年末納税で取得単価を時価にリセットしない)、清算なし/ありを併記。
  現行regime_shiftも同じ方式で評価し直して比較する。
  段階② シャープレシオ(年率リターン÷日次リターンの年率標準偏差)とカルマーレシオ(CAGR÷最大DD)の両方が、
        2000年開始(2000-09-01〜)・2006年開始の両方で現行を上回る
  段階③ (a)前半2000-09〜2013-06・後半2013-07〜2026-09それぞれで②が成立
        (b)リバランス年1回・月1回でも②が成立
        (c)金を除く3資産(株・国債・現金 各1/3)でも最大DDが現行の60%以下
  段階④ リバランス回数50回以上
  不合格の段階で止める。
"""
from __future__ import annotations

import math
from collections import defaultdict

import pandas as pd

import copper_gold_filter_lab as B
from permanent_portfolio_lab import close, jgb_series

TAX = 0.20315
COST = 0.002
ANN = 245

STATES = B.base_states()
B_IDX = pd.DatetimeIndex([pd.Timestamp(d) for d in B.dates])


def metrics(v: pd.Series) -> dict:
    yrs = (v.index[-1] - v.index[0]).days / 365.25
    cagr = (v.iloc[-1] / v.iloc[0]) ** (1 / yrs) - 1
    dr = v.pct_change().dropna()
    vol = dr.std() * math.sqrt(ANN)
    mdd = float((1 - v / v.cummax()).max())
    return {"cagr": cagr, "sharpe": cagr / vol if vol > 0 else float("nan"),
            "calmar": cagr / mdd if mdd > 0 else float("nan"), "mdd": mdd}


def regime_series(start: pd.Timestamp, end: pd.Timestamp, liquidate: bool) -> pd.Series:
    si = int(B_IDX.searchsorted(start))
    ei = int(B_IDX.searchsorted(end, side="right")) - 1
    equity = basis = 1.0
    realized = defaultdict(float)
    out = [(B_IDX[si], equity)]
    for i in range(si + 1, ei + 1):
        y = B.dates[i].year
        leg = STATES[i - 1]
        equity *= 1 + (B.rets[i] if leg == "long" else -B.rets[i])
        if STATES[i] != STATES[i - 1]:
            equity *= 1 - COST
            realized[y] += equity - basis
            basis = equity
        last = i == ei or B.dates[i + 1].year != y
        if last:
            if liquidate and i == ei:
                equity *= 1 - COST
                realized[y] += equity - basis
                basis = equity
            tax = TAX * max(0.0, realized.get(y, 0.0))
            if tax > 0:
                f = tax / equity
                equity -= tax
                basis *= 1 - f
        out.append((B_IDX[i], equity))
    return pd.Series([v for _, v in out], index=[d for d, _ in out])


def period_key(d: pd.Timestamp, freq: str):
    if freq == "M":
        return (d.year, d.month)
    if freq == "Q":
        return (d.year, (d.month - 1) // 3)
    return d.year


def portfolio_series(rets: pd.DataFrame, assets: list[str], start: pd.Timestamp, end: pd.Timestamp,
                     freq: str, liquidate: bool) -> tuple[pd.Series, int]:
    r = rets[(rets.index >= start) & (rets.index <= end)][assets]
    k = len(assets)
    val = {c: 1.0 / k for c in assets}
    basis = {c: 1.0 / k for c in assets}
    realized = defaultdict(float)
    out, rebals, prev = [], 0, None
    idx = list(r.index)
    for i, (d, row) in enumerate(r.iterrows()):
        if i > 0:
            for c in assets:
                val[c] *= 1 + row[c]
        key = period_key(d, freq)
        if prev is not None and key != prev:
            total = sum(val.values())
            tgt = total / k
            cost = sum(abs(val[c] - tgt) * COST for c in assets if c != "cash")
            for c in assets:
                if c == "cash":
                    continue
                diff = val[c] - tgt
                if diff > 0:
                    realized[d.year] += diff * (1 - basis[c] / val[c])
                    basis[c] *= tgt / val[c]
                else:
                    basis[c] += -diff
            each = (total - cost) / k
            for c in assets:
                val[c] = each
            rebals += 1
        prev = key
        last = i == len(idx) - 1 or idx[i + 1].year != d.year
        if last:
            if liquidate and i == len(idx) - 1:
                for c in assets:
                    if c == "cash":
                        continue
                    realized[d.year] += val[c] * (1 - COST) - basis[c]
                    val[c] *= 1 - COST
                    basis[c] = val[c]
            tax = TAX * max(0.0, realized.get(d.year, 0.0))
            if tax > 0:
                total = sum(val.values())
                for c in assets:  # 税は全資産から比例で支払う(取得単価も比例縮小)
                    f = val[c] / total
                    if c != "cash" and val[c] > 0:
                        basis[c] *= 1 - (tax * f) / val[c]
                    val[c] -= tax * f
        out.append((d, sum(val.values())))
    return pd.Series([v for _, v in out], index=[d for d, _ in out]), rebals


def build_rets() -> pd.DataFrame:
    n225 = close("^N225")
    jgb = jgb_series()
    gold = (close("GC=F") * close("JPY=X")).dropna()
    rets = pd.DataFrame({
        "stock": n225.pct_change(),
        "bond": jgb.reindex(n225.index),
        "gold": gold.pct_change().shift(1).reindex(n225.index),
    }).dropna()
    rets["cash"] = 0.0
    return rets


def compare(rets, assets, start, end, freq, liquidate) -> tuple[dict, dict, int]:
    pp, nreb = portfolio_series(rets, assets, start, end, freq, liquidate)
    rs = regime_series(pp.index[0], pp.index[-1], liquidate)
    return metrics(pp), metrics(rs), nreb


def fmt(m: dict) -> str:
    return f"CAGR {m['cagr']*100:5.2f}% シャープ {m['sharpe']:.3f} カルマー {m['calmar']:.3f} MDD {m['mdd']*100:4.1f}%"


def check2(rets, assets, windows, freq, label) -> bool:
    ok_all = True
    for wl, (st, en) in windows.items():
        for liq in (False, True):
            p, r, nreb = compare(rets, assets, st, en, freq, liq)
            ok = p["sharpe"] > r["sharpe"] and p["calmar"] > r["calmar"]
            ok_all &= ok
            print(f"  [{label}] {wl} 清算{'あり' if liq else 'なし'}: "
                  f"4資産 {fmt(p)} | 現行 {fmt(r)} | リバランス{nreb}回 → {'OK' if ok else 'NG'}")
    return ok_all


def main() -> None:
    rets = build_rets()
    end = rets.index[-1]
    s0 = pd.Timestamp("2000-09-01")
    A4 = ["stock", "bond", "gold", "cash"]
    print(f"4資産が揃う期間: {rets.index[0].date()}〜{end.date()}")

    print("\n=== 段階② ===")
    w2 = {"2000年開始": (s0, end), "2006年開始": (pd.Timestamp("2006-01-01"), end)}
    ok2 = check2(rets, A4, w2, "Q", "四半期")
    print(f"段階②判定: {'合格' if ok2 else '不合格'}")
    if not ok2:
        return

    print("\n=== 段階③(a) 前半・後半 ===")
    w3 = {"前半2000-09〜2013-06": (s0, pd.Timestamp("2013-06-30")),
          "後半2013-07〜2026-09": (pd.Timestamp("2013-07-01"), end)}
    ok3a = check2(rets, A4, w3, "Q", "四半期")
    print(f"段階③(a)判定: {'合格' if ok3a else '不合格'}")
    if not ok3a:
        return

    print("\n=== 段階③(b) リバランス頻度 ===")
    ok3b = check2(rets, A4, w2, "A", "年1回") & check2(rets, A4, w2, "M", "月1回")
    print(f"段階③(b)判定: {'合格' if ok3b else '不合格'}")
    if not ok3b:
        return

    print("\n=== 段階③(c) 金を除く3資産 ===")
    ok3c = True
    for wl, (st, en) in w2.items():
        for liq in (False, True):
            p, r, _ = compare(rets, ["stock", "bond", "cash"], st, en, "Q", liq)
            ratio = p["mdd"] / r["mdd"]
            ok = ratio <= 0.60
            ok3c &= ok
            print(f"  {wl} 清算{'あり' if liq else 'なし'}: 3資産MDD {p['mdd']*100:.1f}% / 現行 {r['mdd']*100:.1f}% "
                  f"→ 比 {ratio*100:.0f}% {'OK' if ok else 'NG'}  (3資産 {fmt(p)})")
    print(f"段階③(c)判定: {'合格' if ok3c else '不合格'}")
    if not ok3c:
        return

    print("\n=== 段階④ ===")
    _, nreb = portfolio_series(rets, A4, s0, end, "Q", False)
    print(f"リバランス回数(2000-09〜、四半期): {nreb}回 → {'合格' if nreb >= 50 else '不合格'}")


if __name__ == "__main__":
    main()
