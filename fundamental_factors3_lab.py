#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学術ファクター第3弾(財務諸表ベース6個)の一括検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

前回(fundamental_factors2_lab.py)がバリュー系3つの多重共線性を示唆したため、
今回はサイズ・流動性・会計の質など異なる切り口を中心に選定した6個を
new_factors_lab.pyと同じ方式で一括検証する:

  1. サイズ(時価総額)ファクター(Fama & French 1992): 小型株が大型株を上回るか。
     以前は日経225限定(大型株中心)で検証不能だったため、全プライムで再挑戦。
  2. ネットネット株/正味流動資産バリュー(Graham): (流動資産-総負債)/時価総額。
     PER・EV/EBITDAとは異なる「解散価値」ベースのディープバリュー指標。
  3. Net Operating Assetsアノマリー(Hirshleifer, Hou, Teoh & Zhang 2004):
     ((総資産-現金)-(総負債-有利子負債))/前期総資産。高いほど貸借対照表が
     「膨張」しており将来リターンが低いとされる。
  4. 粗利益率の変化(マージン・モメンタム): 粗利益率(当期)-粗利益率(前期)。
     既存の粗利益収益性(水準、#15でNO-GO)とは別に、変化率に着目。
  5. 増配・減配アナウンスメント効果: 年間配当合計の対前年変化率。
     既存の配当利回り(水準、#45でGO)とは別に、変化に着目。
  6. Piotroski Fスコア(全プライム再検証、Piotroski 2000): 以前は日経225で
     低スコア群n=6とサンプル不足で判断不能だった(academic_factors_lab.py)。
     全プライムなら十分なサンプルが得られる可能性がある。

使い方: python fundamental_factors3_lab.py --prime
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


def piotroski_score(inc, bs, cf, cur, prev) -> int | None:
    try:
        ni_cur, ta_cur, ta_prev = g(inc, "Net Income", cur), g(bs, "Total Assets", cur), g(bs, "Total Assets", prev)
        ni_prev = g(inc, "Net Income", prev)
        ocf_cur = g(cf, "Operating Cash Flow", cur)
        ltd_cur, ltd_prev = g(bs, "Long Term Debt", cur) or 0, g(bs, "Long Term Debt", prev) or 0
        ca_cur, cl_cur = g(bs, "Current Assets", cur), g(bs, "Current Liabilities", cur) or 1
        ca_prev, cl_prev = g(bs, "Current Assets", prev), g(bs, "Current Liabilities", prev) or 1
        shares_cur, shares_prev = g(bs, "Ordinary Shares Number", cur), g(bs, "Ordinary Shares Number", prev)
        gp_cur, gp_prev = g(inc, "Gross Profit", cur), g(inc, "Gross Profit", prev)
        rev_cur, rev_prev = g(inc, "Total Revenue", cur) or 1, g(inc, "Total Revenue", prev) or 1
        if None in (ni_cur, ta_cur, ta_prev, ni_prev, ocf_cur, ca_cur, ca_prev, shares_cur, shares_prev):
            return None
        roa_cur, roa_prev = ni_cur / ta_cur, ni_prev / ta_prev
        score = 0
        score += 1 if ni_cur > 0 else 0
        score += 1 if ocf_cur > 0 else 0
        score += 1 if roa_cur > roa_prev else 0
        score += 1 if ocf_cur > ni_cur else 0
        score += 1 if (ltd_cur / ta_cur) < (ltd_prev / ta_prev) else 0
        score += 1 if (ca_cur / cl_cur) > (ca_prev / cl_prev) else 0
        score += 1 if shares_cur <= shares_prev * 1.01 else 0
        if gp_cur is not None and gp_prev is not None:
            score += 1 if (gp_cur / rev_cur) > (gp_prev / rev_prev) else 0
        score += 1 if (rev_cur / ta_cur) > (rev_prev / ta_prev) else 0
        return score
    except (ZeroDivisionError, TypeError):
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
        if i == 0:
            continue
        prev = bs_cols[i - 1]
        ta = g(bs, "Total Assets", fye)
        ta_prev = g(bs, "Total Assets", prev)
        shares = g(bs, "Ordinary Shares Number", fye)
        if not ta or not ta_prev or not shares:
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

        obs["size"] = market_cap

        ca = g(bs, "Current Assets", fye)
        tl = g(bs, "Total Liabilities Net Minority Interest", fye)
        if ca is not None and tl is not None:
            obs["ncav"] = (ca - tl) / market_cap

        cash = g(bs, "Cash And Cash Equivalents", fye) or 0.0
        total_debt = g(bs, "Total Debt", fye) or 0.0
        tl_prev = g(bs, "Total Liabilities Net Minority Interest", prev)
        total_debt_prev = g(bs, "Total Debt", prev) or 0.0
        if tl is not None:
            noa = (ta - cash) - (tl - total_debt)
            obs["noa"] = noa / ta_prev

        gp_cur = g(inc, "Gross Profit", fye) if fye in inc.columns else None
        gp_prev = g(inc, "Gross Profit", prev) if prev in inc.columns else None
        rev_cur = g(inc, "Total Revenue", fye) if fye in inc.columns else None
        rev_prev = g(inc, "Total Revenue", prev) if prev in inc.columns else None
        if gp_cur is not None and rev_cur and gp_prev is not None and rev_prev:
            obs["margin_change"] = (gp_cur / rev_cur) - (gp_prev / rev_prev)

        if divs is not None and len(divs) > 0:
            reveal_d = reveal_date.date()
            w1_start = (reveal_date - dt.timedelta(days=365)).date()
            w2_start = (reveal_date - dt.timedelta(days=730)).date()
            div_cur = sum(v for d, v in divs.items() if w1_start <= d.date() <= reveal_d)
            div_prev = sum(v for d, v in divs.items() if w2_start <= d.date() < w1_start)
            if div_prev > 0:
                obs["div_change"] = div_cur / div_prev - 1

        pscore = piotroski_score(inc, bs, cf, fye, prev)
        if pscore is not None:
            obs["fscore"] = pscore

        keys = ("ncav", "noa", "margin_change", "div_change", "fscore")
        if any(k in obs for k in keys):
            out.append(obs)
    return out


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"fund3_checkpoint_{universe_tag}.json"
    cache_path = f"fund3_cache_{universe_tag}.json"

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
        ("size", "サイズ(時価総額、低い=小型株が良いはず)", True),
        ("ncav", "ネットネット株(正味流動資産バリュー、高い方が良いはず)", False),
        ("noa", "Net Operating Assets(低い方が良いはず)", True),
        ("margin_change", "粗利益率の変化(改善方向が良いはず)", False),
        ("div_change", "増配・減配(増配方向が良いはず)", False),
        ("fscore", "Piotroski Fスコア(高い方が良いはず)", False),
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
          "生存バイアス・DSR等の多重検定補正は未実施。")


if __name__ == "__main__":
    main()
