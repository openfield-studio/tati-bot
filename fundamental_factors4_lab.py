#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学術ファクター第4弾(財務諸表ベース9個)の一括検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

  1. Mohanram Gスコア(簡易版、Mohanram 2005): Piotroski Fスコアの成長株版。
     ROA・CFO/TA・CFO>NI・R&D集約度・CapEx集約度の5criteria(原著は8、
     利益/売上高成長の安定性・広告費は年度内クロスセクショナル分散の計算が
     複雑なため簡易的に省略)を、年度内中央値との比較で0-5点に採点。
  2. 年金負債の積立不足アノマリー(Franzoni & Marin 2006): 年金・退職給付
     引当金 / 時価総額。高いほど将来リターンが低いとされる。
  3. 実効税率: 法人税等 / 税引前利益。低いほど(節税)将来リターンが高いか
     どうかの検証(方向は先行研究でも一致していない)。
  4. CapEx/減価償却比率: 設備投資が減価償却を上回るペース(過剰投資の代理)。
     高いほど将来リターンが低いとされる。
  5. インタレストカバレッジレシオ: EBIT/支払利息。高いほど安全(質が高い)。
  6. 自社株買い実施額(グロス、$ベース): -Net Common Stock Issuance/時価総額。
     純株式発行アノマリー(#25、株式「数」ベース)とは異なる金額ベースの指標。
  7. フリーキャッシュフロー対有利子負債比率: FCF/有利子負債。高いほど安全。
  8. 有形固定資産集約度(Novy-Marx系資産軽量化論): Net PPE/総資産。
     低い(資産が軽い)方が良いとされる。
  9. 運転資本効率性: Change In Working Capital/総資産。プラス(効率化)の
     方が良いとされる。

使い方: python fundamental_factors4_lab.py --prime
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
        hist = t.history(period="7y")
    except Exception:
        return []
    if inc is None or bs is None or cf is None or hist.empty:
        return []
    price_map = to_price_map(hist)

    bs_cols = sorted(bs.columns)
    out = []
    for fye in bs_cols:
        ta = g(bs, "Total Assets", fye)
        shares = g(bs, "Ordinary Shares Number", fye)
        if not ta or not shares:
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
        ebit = g(inc, "EBIT", fye) if fye in inc.columns else None
        int_exp = g(inc, "Interest Expense", fye) if fye in inc.columns else None
        tax = g(inc, "Tax Provision", fye) if fye in inc.columns else None
        pretax = g(inc, "Pretax Income", fye) if fye in inc.columns else None
        rd = g(inc, "Research And Development", fye) if fye in inc.columns else None
        capex = abs(g(cf, "Capital Expenditure", fye) or 0) if fye in cf.columns else None
        depr = g(inc, "Reconciled Depreciation", fye) if fye in inc.columns else None
        fcf = g(cf, "Free Cash Flow", fye) if fye in cf.columns else None
        total_debt = g(bs, "Total Debt", fye) or 0.0
        net_stock_issuance = g(cf, "Net Common Stock Issuance", fye) if fye in cf.columns else None
        net_ppe = g(bs, "Net PPE", fye)
        chg_wc = g(cf, "Change In Working Capital", fye) if fye in cf.columns else None
        pension1 = g(bs, "Employee Benefits", fye) or 0.0
        pension2 = g(bs, "Non Current Pension And Other Postretirement Benefit Plans", fye) or 0.0

        if ni is not None:
            obs["roa"] = ni / ta
        if ocf is not None:
            obs["cfo_ta"] = ocf / ta
            if ni is not None:
                obs["cfo_minus_ni"] = ocf - ni
        if rd is not None and rd > 0:
            obs["rd_ta"] = rd / ta
        if capex is not None:
            obs["capex_ta"] = capex / ta
            if depr and depr > 0:
                obs["capex_depr"] = capex / depr

        if pension1 or pension2:
            obs["pension_underfunding"] = (pension1 + pension2) / market_cap
        if tax is not None and pretax and pretax > 0:
            obs["eff_tax_rate"] = tax / pretax
        if ebit is not None and int_exp and int_exp > 0:
            obs["interest_coverage"] = ebit / int_exp
        if net_stock_issuance is not None:
            obs["buyback_amount"] = -net_stock_issuance / market_cap
        if fcf is not None and total_debt > 0:
            obs["fcf_debt"] = fcf / total_debt
        if net_ppe is not None:
            obs["ppe_intensity"] = net_ppe / ta
        if chg_wc is not None:
            obs["wc_efficiency"] = chg_wc / ta

        keys = ("pension_underfunding", "eff_tax_rate", "capex_depr", "interest_coverage",
                "buyback_amount", "fcf_debt", "ppe_intensity", "wc_efficiency",
                "roa", "cfo_ta")
        if any(k in obs for k in keys):
            out.append(obs)
    return out


def compute_gscore(all_obs: list[dict]) -> None:
    """年度内クロスセクショナル中央値との比較でGスコア(簡易版0-5点)を各観測に付与する。"""
    by_year = defaultdict(list)
    for o in all_obs:
        by_year[o["fiscal_year"]].append(o)
    for year, obs_list in by_year.items():
        def median_of(key):
            vals = [o[key] for o in obs_list if key in o]
            return pystats.median(vals) if vals else None

        med_roa = median_of("roa")
        med_cfo_ta = median_of("cfo_ta")
        med_rd_ta = median_of("rd_ta")
        med_capex_ta = median_of("capex_ta")

        for o in obs_list:
            score = 0
            counted = 0
            if "roa" in o and med_roa is not None:
                score += 1 if o["roa"] > med_roa else 0
                counted += 1
            if "cfo_ta" in o and med_cfo_ta is not None:
                score += 1 if o["cfo_ta"] > med_cfo_ta else 0
                counted += 1
            if "cfo_minus_ni" in o:
                score += 1 if o["cfo_minus_ni"] > 0 else 0
                counted += 1
            if "rd_ta" in o and med_rd_ta is not None:
                score += 1 if o["rd_ta"] > med_rd_ta else 0
                counted += 1
            if "capex_ta" in o and med_capex_ta is not None:
                score += 1 if o["capex_ta"] > med_capex_ta else 0
                counted += 1
            if counted >= 3:
                o["gscore"] = score


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"fund4_checkpoint_{universe_tag}.json"
    cache_path = f"fund4_cache_{universe_tag}.json"

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

    compute_gscore(all_obs)
    print(f"\n合計観測数: {len(all_obs)}\n")

    factors = [
        ("gscore", "Mohanram Gスコア簡易版(高い方が良いはず)", False),
        ("pension_underfunding", "年金負債の積立不足(低い方が良いはず)", True),
        ("eff_tax_rate", "実効税率(低い方が良いはず)", True),
        ("capex_depr", "CapEx/減価償却比率(低い方が良いはず)", True),
        ("interest_coverage", "インタレストカバレッジレシオ(高い方が良いはず)", False),
        ("buyback_amount", "自社株買い実施額(グロス、高い方が良いはず)", False),
        ("fcf_debt", "FCF/有利子負債(高い方が良いはず)", False),
        ("ppe_intensity", "有形固定資産集約度(低い方が良いはず)", True),
        ("wc_efficiency", "運転資本効率性(高い方が良いはず)", False),
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
          "Gスコアは簡易近似(原著8criteriaのうち5つ、業種別ではなく全銘柄中央値で比較)。"
          "R&D集約度が絡む項目(Gスコア)は開示銘柄のみでサンプルが少数になる可能性。"
          "生存バイアス・DSR等の多重検定補正は未実施。")


if __name__ == "__main__":
    main()
