#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学術ファクター第5弾(すぐ検証できるもの8個)の一括検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

ユーザーの「学術論文を20個ぐらい探して」を受けて発見した20候補のうち、
yfinanceのデータで実際に検証可能な8個をまとめて検証する(残り12個は
データ調達が難しいためFACTOR_RESEARCH_LOG.mdの調査待ちキューに記録のみ)。

  1. 簿価時価比率(Book-to-Market, HML, Fama & French 1992/1993):
     自己資本(Stockholders Equity) / 時価総額。高い(割安)方が良いとされる。
     今まで未検証だった王道バリュー指標(PER・EV/EBITDA・配当利回り・CF/Pは検証済み)。
  2. 異常設備投資(Abnormal Capital Investment, Titman, Wei & Xie 2004):
     CapEx当期/CapEx前期-1。急増した年は翌年以降マイナスとされる。低い方が良い。
  3. キャッシュベース収益性(Ball, Gerakos, Linnainmaa & Nikolaev 2016):
     営業CF/総資産。粗利益収益性(#15、逆転)の会計操作耐性版。高い方が良いとされる。
  4. 52週高値への近さ(連続変量版、George & Hwang 2004):
     決算発表時点の株価 / 直近252営業日高値。既存の2値版(#7、単純更新の有無)より
     精緻。高い(高値に近い)方が良いとされる。
  5. マジックフォーミュラ(Greenblatt 2005): ROIC簡易版順位+利益利回り(EBIT/EV)
     順位の合成スコア(順位が低い=良いほど良い)。ROIC単体(#46)は逆転していたが、
     利益利回りと組み合わせた複合ランクでは違う結果になるか確認。
  6. ターンアラウンド効果(赤字→黒字転換): 前期赤字・当期黒字への転換組と、
     前期・当期とも赤字のままの組を比較(通常のtercile比較ではなく2群比較)。
  7. 配当性向の変化: 当期配当性向 - 前期配当性向。増減配アノマリー(#58、
     金額ベース)とは別角度(比率の変化)。
  8. のれん(Goodwill)集約度(Gu & Lev 2011): Goodwill/総資産。M&A過多企業は
     割高になりがちで低い方が良いとされる。

使い方: python academic_factors5_lab.py --prime
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
from scipy import stats

CHECKPOINT_EVERY = 25
FORWARD_MONTHS = [6, 12]
REPORT_LAG_DAYS = 60
RET_CAP = 2.0
N_TRIALS = 69


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


def rolling_high(hist, before_date) -> float | None:
    window = hist[hist.index.date < before_date.date()].tail(252)
    if len(window) < 100:
        return None
    return float(window["Close"].max())


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
    prev_capex = None
    prev_ni = None
    prev_payout = None
    for fye in bs_cols:
        ta = g(bs, "Total Assets", fye)
        shares = g(bs, "Ordinary Shares Number", fye)
        equity = g(bs, "Stockholders Equity", fye)
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
        capex = abs(g(cf, "Capital Expenditure", fye) or 0) if fye in cf.columns else None
        total_debt = g(bs, "Total Debt", fye) or 0.0
        cash = g(bs, "Cash And Cash Equivalents", fye) or 0.0
        goodwill = g(bs, "Goodwill", fye)
        divs_paid = abs(g(cf, "Cash Dividends Paid", fye) or 0) if fye in cf.columns else None

        # 1. 簿価時価比率
        if equity is not None:
            obs["book_to_market"] = equity / market_cap

        # 2. 異常設備投資
        if capex is not None and prev_capex and prev_capex > 0:
            obs["abnormal_capex"] = capex / prev_capex - 1

        # 3. キャッシュベース収益性
        if ocf is not None:
            obs["cfo_ta"] = ocf / ta

        # 4. 52週高値への近さ(連続変量)
        high252 = rolling_high(hist, fye.to_pydatetime())
        if high252:
            obs["nearness_52w"] = price0 / high252

        # 5. マジックフォーミュラの元データ(ROIC・利益利回り)
        invested_capital = (total_debt + (equity or 0) - cash)
        if ebit is not None and invested_capital and invested_capital > 0:
            obs["roic"] = ebit / invested_capital
        ev = market_cap + total_debt - cash
        if ebit is not None and ev > 0:
            obs["earnings_yield"] = ebit / ev

        # 6. ターンアラウンド(赤字→黒字転換 vs 赤字継続)
        if ni is not None and prev_ni is not None:
            if prev_ni < 0 and ni > 0:
                obs["turnaround_group"] = "turned_profitable"
            elif prev_ni < 0 and ni < 0:
                obs["turnaround_group"] = "stayed_loss"

        # 7. 配当性向の変化
        if divs_paid is not None and ni and ni > 0:
            payout = divs_paid / ni
            if prev_payout is not None and payout < 3:  # 異常値(利益ほぼゼロでの極端な比率)除外
                obs["payout_change"] = payout - prev_payout
            prev_payout = payout if payout < 3 else prev_payout
        else:
            pass

        # 8. のれん集約度
        if goodwill is not None:
            obs["goodwill_intensity"] = goodwill / ta

        keys = ("book_to_market", "abnormal_capex", "cfo_ta", "nearness_52w",
                "roic", "earnings_yield", "turnaround_group", "payout_change",
                "goodwill_intensity")
        if any(k in obs for k in keys):
            out.append(obs)

        prev_capex = capex if capex is not None else prev_capex
        prev_ni = ni if ni is not None else prev_ni
    return out


def compute_magic_formula(all_obs: list[dict]) -> None:
    """年度内クロスセクショナル順位でROIC順位+利益利回り順位の合成スコアを付与(低いほど良い)。"""
    by_year = defaultdict(list)
    for o in all_obs:
        if "roic" in o and "earnings_yield" in o:
            by_year[o["fiscal_year"]].append(o)
    for year, obs_list in by_year.items():
        roic_ranked = sorted(obs_list, key=lambda o: o["roic"], reverse=True)
        ey_ranked = sorted(obs_list, key=lambda o: o["earnings_yield"], reverse=True)
        roic_rank = {id(o): i for i, o in enumerate(roic_ranked)}
        ey_rank = {id(o): i for i, o in enumerate(ey_ranked)}
        for o in obs_list:
            o["magic_formula"] = roic_rank[id(o)] + ey_rank[id(o)]


def report_tercile(all_obs: list[dict], key: str, label: str, low_is_good: bool) -> None:
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
        gr = [r for r in pooled_good[m] if abs(r) <= RET_CAP]
        br = [r for r in pooled_bad[m] if abs(r) <= RET_CAP]
        if len(gr) < 10 or len(br) < 10:
            print(f"  {m}ヶ月後: サンプル不足")
            continue
        diff = (pystats.mean(gr) - pystats.mean(br)) * 100
        t_stat, p_value = stats.ttest_ind(gr, br, equal_var=False)
        p_bonf = min(1.0, p_value * N_TRIALS)
        print(f"  {m}ヶ月後: 良い群={pystats.mean(gr)*100:+.1f}%(n={len(gr)}) / "
              f"悪い群={pystats.mean(br)*100:+.1f}%(n={len(br)}) / 差={diff:+.1f}pt / "
              f"t={t_stat:+.2f} p={p_value:.4f} Bonf補正後p={p_bonf:.4f}"
              f"({'有意' if p_bonf < 0.05 else '非有意'})")
    print()


def report_turnaround(all_obs: list[dict]) -> None:
    print(f"{'='*70}\n=== ターンアラウンド効果(赤字→黒字 vs 赤字継続) ===\n{'='*70}")
    turned = [o for o in all_obs if o.get("turnaround_group") == "turned_profitable"]
    stayed = [o for o in all_obs if o.get("turnaround_group") == "stayed_loss"]
    print(f"有効観測数: 転換組{len(turned)} / 継続組{len(stayed)}")
    for m in FORWARD_MONTHS:
        gr = [o[f"ret{m}"] for o in turned if o.get(f"ret{m}") is not None and abs(o[f"ret{m}"]) <= RET_CAP]
        br = [o[f"ret{m}"] for o in stayed if o.get(f"ret{m}") is not None and abs(o[f"ret{m}"]) <= RET_CAP]
        if len(gr) < 10 or len(br) < 10:
            print(f"  {m}ヶ月後: サンプル不足(転換{len(gr)}/継続{len(br)})")
            continue
        diff = (pystats.mean(gr) - pystats.mean(br)) * 100
        t_stat, p_value = stats.ttest_ind(gr, br, equal_var=False)
        p_bonf = min(1.0, p_value * N_TRIALS)
        print(f"  {m}ヶ月後: 転換組={pystats.mean(gr)*100:+.1f}%(n={len(gr)}) / "
              f"継続組={pystats.mean(br)*100:+.1f}%(n={len(br)}) / 差={diff:+.1f}pt / "
              f"t={t_stat:+.2f} p={p_value:.4f} Bonf補正後p={p_bonf:.4f}"
              f"({'有意' if p_bonf < 0.05 else '非有意'})")
    print()


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"fund5_checkpoint_{universe_tag}.json"
    cache_path = f"fund5_cache_{universe_tag}.json"

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

    compute_magic_formula(all_obs)
    print(f"\n合計観測数: {len(all_obs)}\n")

    report_tercile(all_obs, "book_to_market", "1. 簿価時価比率(B/M、高い方が良いはず)", False)
    report_tercile(all_obs, "abnormal_capex", "2. 異常設備投資(低い方が良いはず)", True)
    report_tercile(all_obs, "cfo_ta", "3. キャッシュベース収益性(高い方が良いはず)", False)
    report_tercile(all_obs, "nearness_52w", "4. 52週高値への近さ連続版(高い方が良いはず)", False)
    report_tercile(all_obs, "magic_formula", "5. マジックフォーミュラ(順位合計が低い方が良いはず)", True)
    report_turnaround(all_obs)
    report_tercile(all_obs, "payout_change", "7. 配当性向の変化(仮説: 増加の方が良い)", False)
    report_tercile(all_obs, "goodwill_intensity", "8. のれん集約度(低い方が良いはず)", True)

    print("注意: 東証プライム全銘柄のみでの検証。決算発表タイミングは+60日で近似。"
          "配当性向の変化は極端値(利益ほぼゼロでの比率)を除外。生存バイアス・"
          "DSR等の多重検定補正は未実施(Bonferroni補正のみ簡易実施)。")


if __name__ == "__main__":
    main()
