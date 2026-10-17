#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""税計算バグ修正(tati_eval.py)後に、段階②以降で不合格にした過去案を再評価する(2026-10-16)。

各案について、現行ベースラインに対する変化率(%)を
  旧方式(legacy: 取得単価リセットのバグあり) / 新方式(清算なし) / 新方式(期末清算あり) / 新方式(清算+3年繰越)
で並べ、事前登録の段階②基準(案ごとに記載)の判定が変わるかを見る。
使い方: python reevaluate_tax_fix.py [--corr]   (--corr で#96銘柄間相関も実行、重い)
"""
from __future__ import annotations

import contextlib
import io
import math
import sys

import pandas as pd
import yfinance as yf

import tati_eval as E

YEARS = (2000, 2006, 1965)
MODES = ("legacy", "new", "new_liq", "new_liq_carry")
MODE_JA = {"legacy": "旧方式", "new": "新(清算なし)", "new_liq": "新(清算あり)", "new_liq_carry": "新(清算+繰越)"}


def quiet_import(name: str):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return __import__(name)


def report(title: str, crit_years: tuple, rows: list[tuple[str, dict]]) -> None:
    print(f"\n=== {title} ===  判定基準: {'/'.join(map(str, crit_years))}年開始が全て改善")
    for label, cmp in rows:
        cells = []
        for m in MODES:
            v = cmp[m]
            ok = all(v[y] > 0 for y in crit_years)
            cells.append(f"{MODE_JA[m]} " + " ".join(f"{v[y]:+6.1f}" for y in YEARS) + (" 合格" if ok else " 不合格"))
        print(f"  {label:<22} | " + " | ".join(cells))


# ---------- 共通: qar型の追加トリガー付き切替生成 ----------
def gen_switches(px, rets, bear, extra=None, ma_slow=350, shock=-0.025, cooldown=15,
                 tp=0.05, sl=0.18, max_hold=20, cap=True, follow_regime=False):
    n = len(px)
    events = [(0, "long")]
    holding, entry_i, last_shock = "long", 0, -10**9
    for i in range(ma_slow, n):
        if follow_regime:
            want = "bear" if bear[i] else "long"
            if want != holding:
                events.append((i, want))
                holding = want
            continue
        if holding == "bear":
            rr = -(px[i] / px[entry_i] - 1)
            held = i - entry_i
            exit_ = rr >= tp or rr <= -sl or (held >= max_hold if cap else not bear[i])
            if exit_:
                events.append((i, "long"))
                holding, entry_i = "long", i
        else:
            trig = rets[i] <= shock or (extra is not None and extra[i])
            if trig and (i - last_shock) >= cooldown and bear[i]:
                events.append((i, "bear"))
                holding, entry_i, last_shock = "bear", i, i
            elif trig:
                last_shock = i
    return events


def main() -> None:
    C = quiet_import("copper_gold_filter_lab")
    px, rets, dates, bear, n = C.px, C.rets, C.dates, C.bear_regime, C.n
    base = [(s, 1.0) for s in C.base_states()]

    # 自前の生成器が現行ベースラインを再現するか
    st0 = E.events_to_states(gen_switches(px, rets, bear), n)
    assert st0 == base, "ベースライン再現に失敗"

    # ---- #101 銅÷金フィルター ----
    rows = []
    for lb in (189, 252, 315):
        w = C.warn_series(lb)
        for label, wgt in (("現金", 0.0), ("50%", 0.5)):
            rows.append((f"{lb}日 {label}", E.compare(base, C.apply_filter(C.base_states(), w, wgt), rets, dates)))
    report("#101 銅÷金比率フィルター(2000・2006年が基準)", (2000, 2006), rows)

    # ---- #82 保有延長 ----
    rows = [("案A 20日上限撤廃", E.compare(base, E.events_to_states(gen_switches(px, rets, bear, cap=False), n), rets, dates)),
            ("案B デッドクロス中ずっと1571", E.compare(base, E.events_to_states(gen_switches(px, rets, bear, follow_regime=True), n), rets, dates))]
    report("#82 保有延長", YEARS, rows)

    # ---- #83 VIX / #84 ドル円・日経10日 ----
    def lagged_on_n225(series: pd.Series) -> list:
        s = series.copy()
        s.index = pd.to_datetime(s.index.date)
        s = s.shift(1).reindex(pd.to_datetime(dates), method="ffill")
        return [None if pd.isna(v) else float(v) for v in s.values]

    vix = yf.Ticker("^VIX").history(period="max")["Close"].dropna()
    vx = lagged_on_n225(vix)
    vx_prev = [None] + vx[:-1]
    extra_level = [v is not None and v > 30 for v in vx]
    extra_cross = [vx[i] is not None and vx_prev[i] is not None and vx[i] > 30 >= vx_prev[i] for i in range(n)]
    fx = yf.Ticker("JPY=X").history(period="max")["Close"].dropna()
    fxl = lagged_on_n225(fx)
    extra_fx = [i >= 10 and fxl[i] is not None and fxl[i - 10] is not None and fxl[i] / fxl[i - 10] - 1 <= -0.03 for i in range(n)]
    extra_nk = [i >= 10 and px[i] / px[i - 10] - 1 <= -0.06 for i in range(n)]
    rows = [("VIX>30(水準、1日ラグ)", E.compare(base, E.events_to_states(gen_switches(px, rets, bear, extra_level), n), rets, dates)),
            ("VIXが30を上抜け(1日ラグ)", E.compare(base, E.events_to_states(gen_switches(px, rets, bear, extra_cross), n), rets, dates)),
            ("ドル円10日-3%以下", E.compare(base, E.events_to_states(gen_switches(px, rets, bear, extra_fx), n), rets, dates)),
            ("日経10日-6%以下", E.compare(base, E.events_to_states(gen_switches(px, rets, bear, extra_nk), n), rets, dates))]
    report("#83 VIX / #84 ドル円・日経10日累積下落", YEARS, rows)

    # ---- #91 CUSUM ----
    U = quiet_import("cusum_regime_lab")
    ub = E.events_to_states(U.gen_switches(False, None), U.n)
    chk = U.evaluate(U.gen_switches(False, None), 2000)[0]
    assert abs(E.evaluate(ub, U.rets, U.dates, 2000, legacy=True)["equity"] - chk) < 1, "CUSUM旧方式の再現失敗"
    rows = []
    for t in (150, 250, 500):
        with contextlib.redirect_stdout(io.StringIO()):
            h = U.calibrate_h(t)
        rows.append((f"ARL{t}(h={h*100:.2f}%)", E.compare(ub, E.events_to_states(U.gen_switches(True, h), U.n), U.rets, U.dates)))
    report("#91 CUSUM", YEARS, rows)

    # ---- #95 ドローダウン継続日数 ----
    D = quiet_import("drawdown_duration_regime_lab")
    db = E.events_to_states(D.gen_switches(False, None), D.n)
    chk = D.evaluate(D.gen_switches(False, None), 2000)[0]
    assert abs(E.evaluate(db, D.rets, D.dates, 2000, legacy=True)["equity"] - chk) < 1, "継続日数旧方式の再現失敗"
    rows = [(f"閾値{th}日", E.compare(db, E.events_to_states(D.gen_switches(True, th), D.n), D.rets, D.dates))
            for th in D.candidate_ths]
    report("#95 ドローダウン継続日数", YEARS, rows)

    # ---- #96 銘柄間相関(重い、--corr指定時のみ) ----
    if "--corr" in sys.argv:
        R = quiet_import("correlation_spike_regime_lab")
        with contextlib.redirect_stdout(io.StringIO()):
            prices = R.load_price_panel()
            prets = prices.pct_change()
            mkt = prets.mean(axis=1, skipna=True)
        dc = ["bull" if not bear[i] else "bear" for i in range(n)]
        nk20 = [None] * n
        for i in range(R.NIKKEI_DECLINE_WINDOW, n):
            nk20[i] = px[i] / px[i - R.NIKKEI_DECLINE_WINDOW] - 1
        rows = []
        for w in (15, 20, 25):
            with contextlib.redirect_stdout(io.StringIO()):
                ac = R.build_avg_corr_series(prices, prets, mkt, w)
            cmap = {d.date(): v for d, v in ac.items()}
            cfd, last = [None] * n, None
            for i, d in enumerate(dates):
                if d in cmap:
                    last = cmap[d]
                cfd[i] = last
            pctls = (20, 25, 30) if w == 20 else (25,)
            for p in pctls:
                with contextlib.redirect_stdout(io.StringIO()):
                    th = R.is_threshold(ac, p)
                rb = E.events_to_states(R.gen_switches(px, dates, dc, cfd, nk20, False, th), n)
                rn = E.events_to_states(R.gen_switches(px, dates, dc, cfd, nk20, True, th), n)
                rows.append((f"窓{w} p{p}", E.compare(rb, rn, rets, dates)))
        report("#96 銘柄間相関", YEARS, rows)
    else:
        print("\n#96 銘柄間相関: --corr 未指定のためスキップ")


if __name__ == "__main__":
    main()
