#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学術ファクター第2弾(財務諸表ベース8個)の一括検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

「特定の日に限らず他の研究論文をまた10個」の依頼で見つけた候補のうち、
財務諸表データ(income_stmt/balance_sheet/cashflow)から計算できる8個を
new_factors_lab.pyと同じ方式(決算期末+60日開示ラグ、年度内クロスセクショナル
下位/上位1/3比較)でまとめて検証する:

  1. キャッシュフロー利回り(CF/P) = 営業CF / 時価総額(高い方が良い)
  2. EV/EBITDA = (時価総額+有利子負債-現金) / EBITDA(低い方が良い)
  3. R&D集約度 = 研究開発費 / 時価総額(高い方が良い、Chan et al. 2001)
     ※yfinanceでR&D費用を個別開示している銘柄のみ(製薬・電機等)、サンプル少数
  4. 配当利回り = 直近1年配当合計 / 株価(高い方が良い)
  5. ROIC(簡易版) = 営業利益×(1-30%) / Invested Capital(高い方が良い)
  6. 売上高成長率 = 売上高(当期)/売上高(前期)-1(低い方が良い、
     Lakonishok, Shleifer & Vishny 1994「グラマー株の失望」)
  7. QMJ(簡易版、Asness, Frazzini & Pedersen 2019) = (ROE - 負債比率 + 配当利回り)/3
     ※本来は各構成要素を年度内パーセンタイル順位化してから合成するが、簡易的に
     生の値を平均。収益性(ROE)・安全性(負債比率の逆)・株主還元(配当利回り)の
     3要素のみ(成長性は資産成長アノマリー#17で既に検証済みのため割愛)。
  8. Oスコア(簡易版、Campbell, Hilscher & Szilagyi 2008) = 負債比率 - ROA
     ※本来のOhlson Oスコアの複雑な係数式ではなく、レバレッジと収益性の2要素のみの
     簡易近似。高いほど財務的に窮迫している(低い方が良いはず、という逆説の検証)。

使い方: python fundamental_factors2_lab.py --prime
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import os
import sys
import statistics as pystats
from collections import defaultdict

import yfinance as yf

CHECKPOINT_EVERY = 25
FORWARD_MONTHS = [6, 12]
REPORT_LAG_DAYS = 60
RET_CAP = 2.0


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def to_price_map(hist) -> dict:
    return {idx.date(): float(row["Close"]) for idx, row in hist.iterrows()}


def nearest_price(price_map: dict, target_date):
    for offset in range(10):
        d = (target_date + dt.timedelta(days=offset)).date()
        if d in price_map:
            return price_map[d]
    return None


def g(df, key, col):
    try:
        v = df.loc[key, col]
        return float(v) if v == v else None
    except (KeyError, TypeError):
        return None


def collect_observations(code: str) -> list[dict]:
    try:
        t = yf.Ticker(f"{code}.T")
        inc = t.income_stmt
        bs = t.balance_sheet
        cf = t.cashflow
        divs = t.dividends
        hist = t.history(period="7y")
    except Exception:
        return []
    if inc is None or bs is None or cf is None or hist.empty:
        return []
    price_map = to_price_map(hist)

    bs_cols = sorted(bs.columns)
    out = []
    for i, fye in enumerate(bs_cols):
        ta = g(bs, "Total Assets", fye)
        equity = g(bs, "Stockholders Equity", fye)
        shares = g(bs, "Ordinary Shares Number", fye)
        if not ta or not equity or not shares:
            continue

        reveal_date = fye.to_pydatetime() + dt.timedelta(days=REPORT_LAG_DAYS)
        price0 = nearest_price(price_map, reveal_date)
        if price0 is None:
            continue
        market_cap = price0 * shares

        rets = {}
        for m in FORWARD_MONTHS:
            target = reveal_date + dt.timedelta(days=int(m * 30.4))
            p1 = nearest_price(price_map, target)
            rets[m] = (p1 / price0 - 1) if p1 else None

        obs = {"code": code, "fiscal_year": fye.year, **{f"ret{m}": rets[m] for m in FORWARD_MONTHS}}

        ni = g(inc, "Net Income", fye) if fye in inc.columns else None
        ocf = g(cf, "Operating Cash Flow", fye) if fye in cf.columns else None
        ebitda = g(inc, "EBITDA", fye) if fye in inc.columns else None
        op_income = g(inc, "Operating Income", fye) if fye in inc.columns else None
        rd = g(inc, "Research And Development", fye) if fye in inc.columns else None
        total_debt = g(bs, "Total Debt", fye) or 0.0
        cash = g(bs, "Cash And Cash Equivalents", fye) or 0.0
        invested_capital = g(bs, "Invested Capital", fye)
        roe = ni / equity if ni is not None and equity else None
        roa = ni / ta if ni is not None else None
        leverage = total_debt / ta if ta else None

        if ocf is not None:
            obs["cf_yield"] = ocf / market_cap
        if ebitda and ebitda > 0:
            ev = market_cap + total_debt - cash
            obs["ev_ebitda"] = ev / ebitda
        if rd is not None and rd > 0:
            obs["rd_intensity"] = rd / market_cap
        if divs is not None and len(divs) > 0:
            window_start_d = (reveal_date - dt.timedelta(days=365)).date()
            reveal_d = reveal_date.date()
            total_div = sum(v for d, v in divs.items() if window_start_d <= d.date() <= reveal_d)
            obs["div_yield"] = total_div / price0
        if op_income is not None and invested_capital and invested_capital > 0:
            obs["roic"] = (op_income * 0.7) / invested_capital
        if i > 0:
            rev_cur = g(inc, "Total Revenue", fye) if fye in inc.columns else None
            rev_prev = g(inc, "Total Revenue", bs_cols[i - 1]) if bs_cols[i - 1] in inc.columns else None
            if rev_cur and rev_prev and rev_prev > 0:
                obs["sales_growth"] = rev_cur / rev_prev - 1
        if roe is not None and leverage is not None:
            div_yield_for_qmj = obs.get("div_yield", 0.0)
            obs["qmj"] = (roe - leverage + div_yield_for_qmj) / 3
        if leverage is not None and roa is not None:
            obs["distress_score"] = leverage - roa

        keys = ("cf_yield", "ev_ebitda", "rd_intensity", "div_yield", "roic",
                "sales_growth", "qmj", "distress_score")
        if any(k in obs for k in keys):
            out.append(obs)
    return out


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"fund2_checkpoint_{universe_tag}.json"
    cache_path = f"fund2_cache_{universe_tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        all_obs = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            saved = json.load(open(checkpoint_path, encoding="utf-8"))
            all_obs = saved["observations"]
            done_codes = set(saved["done_codes"])
            print(f"チェックポイントから再開: {len(done_codes)}銘柄処理済み、観測数 累計{len(all_obs)}")
        else:
            all_obs = []
            done_codes = set()

        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{universe_tag}、残り{len(todo)}/{len(universe)}銘柄を取得中...")
        for i, (code, name) in enumerate(todo, 1):
            all_obs += collect_observations(code)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"observations": all_obs, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(観測数 累計{len(all_obs)})...")

        json.dump(all_obs, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n合計観測数: {len(all_obs)}\n")

    factors = [
        ("cf_yield", "キャッシュフロー利回り(CF/P、高い方が良いはず)", False),
        ("ev_ebitda", "EV/EBITDA(低い方が良いはず)", True),
        ("rd_intensity", "R&D集約度(高い方が良いはず、サンプル少数注意)", False),
        ("div_yield", "配当利回り(高い方が良いはず)", False),
        ("roic", "ROIC簡易版(高い方が良いはず)", False),
        ("sales_growth", "売上高成長率(低い方が良いはず、グラマー株の失望)", True),
        ("qmj", "QMJ簡易版(高い方が良いはず)", False),
        ("distress_score", "Oスコア簡易版(低い=健全な方が良いはず)", True),
    ]

    for key, label, low_is_good in factors:
        print(f"{'='*70}\n=== {label} ===\n{'='*70}")
        obs_with_key = [o for o in all_obs if key in o]
        years = sorted(set(o["fiscal_year"] for o in obs_with_key))
        pooled_good = defaultdict(list)
        pooled_bad = defaultdict(list)
        for year in years:
            yr_obs = [o for o in obs_with_key if o["fiscal_year"] == year]
            yr_sorted = sorted(yr_obs, key=lambda o: o[key])
            n = len(yr_sorted)
            tercile = n // 3
            if tercile < 5:
                continue
            low_group = yr_sorted[:tercile]
            high_group = yr_sorted[-tercile:]
            good, bad = (low_group, high_group) if low_is_good else (high_group, low_group)
            for m in FORWARD_MONTHS:
                pooled_good[m] += [o[f"ret{m}"] for o in good if o.get(f"ret{m}") is not None]
                pooled_bad[m] += [o[f"ret{m}"] for o in bad if o.get(f"ret{m}") is not None]

        print(f"有効観測数: {len(obs_with_key)}")
        for m in FORWARD_MONTHS:
            g_r = [r for r in pooled_good[m] if abs(r) <= RET_CAP]
            b_r = [r for r in pooled_bad[m] if abs(r) <= RET_CAP]
            if g_r and b_r:
                diff = (pystats.mean(g_r) - pystats.mean(b_r)) * 100
                print(f"  {m}ヶ月後: 良い群={pystats.mean(g_r)*100:+.1f}%(中央値{pystats.median(g_r)*100:+.1f}%, n={len(g_r)}) / "
                      f"悪い群={pystats.mean(b_r)*100:+.1f}%(中央値{pystats.median(b_r)*100:+.1f}%, n={len(b_r)}) / 差={diff:+.1f}pt")
            else:
                print(f"  {m}ヶ月後: サンプル不足")
        print()

    universe_label = "東証プライム全銘柄" if universe_tag == "prime" else "日経225"
    print(f"注意: {universe_label}のみでの検証。決算発表タイミングは+60日で近似。"
          "QMJ・Oスコアは簡易近似(本来の複雑な計算式・パーセンタイル順位化ではない)。"
          "R&D集約度は個別開示している銘柄のみでサンプルが少数。生存バイアス・DSR等の"
          "多重検定補正は未実施。")


if __name__ == "__main__":
    main()
