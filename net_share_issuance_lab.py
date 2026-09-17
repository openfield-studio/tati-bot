#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
純株式発行(Net Share Issuance)アノマリーの検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

出典: McLean, Pontiff & Watanabe (2009) "Share Issuance and Cross-Sectional
Returns: International Evidence", Journal of Financial Economics.
日本限定の2025年査読済み追試(Pacific-Basin Finance Journal, pre-registered
report)もある(クラウド探索ルーティンが2026-09-17に発見、調査待ちキュー#1)。

定義: 純株式発行率 = 発行済株式数(当期)/発行済株式数(前期) - 1
  低い(自社株買いで減少)ほどその後のリターンが高いとされる。
  資産成長アノマリー(new_factors_lab.py, 総資産の変化)とは異なる指標
  (株式数そのものの変化。負債で資産を増やしても株式数は変わらないし、
  逆に資産をあまり増やさずに増資することもあるので別のシグナルになりうる)。

individual_value_backtest.py/new_factors_lab.pyと同じ先読みバイアス対策
(決算期末+60日後の株価を使用)・年度内クロスセクショナル比較(下位1/3 vs
上位1/3)を採用。

使い方: python net_share_issuance_lab.py --prime
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
RET_CAP = 2.0  # |r|>200%は外れ値として除外(trader_methods_lab.pyの教訓)


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


def collect_observations(code: str) -> list[dict]:
    try:
        t = yf.Ticker(f"{code}.T")
        bs = t.balance_sheet
        hist = t.history(period="7y")
    except Exception:
        return []
    if bs is None or hist.empty or "Ordinary Shares Number" not in bs.index:
        return []
    price_map = to_price_map(hist)

    def g(df, key, col):
        try:
            v = df.loc[key, col]
            return float(v) if v == v else None
        except (KeyError, TypeError):
            return None

    bs_cols = sorted(bs.columns)
    out = []
    for i in range(1, len(bs_cols)):
        fye = bs_cols[i]
        shares_cur = g(bs, "Ordinary Shares Number", fye)
        shares_prev = g(bs, "Ordinary Shares Number", bs_cols[i - 1])
        if not shares_cur or not shares_prev or shares_prev <= 0:
            continue
        issuance = shares_cur / shares_prev - 1

        reveal_date = fye.to_pydatetime() + dt.timedelta(days=REPORT_LAG_DAYS)
        price0 = nearest_price(price_map, reveal_date)
        if price0 is None:
            continue
        rets = {}
        for m in FORWARD_MONTHS:
            target = reveal_date + dt.timedelta(days=int(m * 30.4))
            p1 = nearest_price(price_map, target)
            rets[m] = (p1 / price0 - 1) if p1 else None

        out.append({"code": code, "fiscal_year": fye.year,
                     "net_share_issuance": issuance,
                     **{f"ret{m}": rets[m] for m in FORWARD_MONTHS}})
    return out


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"nsi_checkpoint_{universe_tag}.json"
    cache_path = f"nsi_cache_{universe_tag}.json"

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
        print(f"{universe_tag}、残り{len(todo)}/{len(universe)}銘柄の発行済株式数+株価を取得中...")
        for i, (code, name) in enumerate(todo, 1):
            all_obs += collect_observations(code)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"observations": all_obs, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(観測数 累計{len(all_obs)}、チェックポイント保存)...")

        json.dump(all_obs, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n合計観測数: {len(all_obs)}")

    years = sorted(set(o["fiscal_year"] for o in all_obs))
    pooled_good = defaultdict(list)
    pooled_bad = defaultdict(list)
    for year in years:
        yr_obs = [o for o in all_obs if o["fiscal_year"] == year]
        yr_sorted = sorted(yr_obs, key=lambda o: o["net_share_issuance"])
        n = len(yr_sorted)
        tercile = n // 3
        if tercile < 5:
            continue
        low_group = yr_sorted[:tercile]    # 発行少ない(自社株買い方向) = 良い群のはず
        high_group = yr_sorted[-tercile:]  # 発行多い(希薄化) = 悪い群のはず
        for m in FORWARD_MONTHS:
            g_r = [o[f"ret{m}"] for o in low_group if o.get(f"ret{m}") is not None]
            b_r = [o[f"ret{m}"] for o in high_group if o.get(f"ret{m}") is not None]
            pooled_good[m] += g_r
            pooled_bad[m] += b_r

    print(f"対象年度: {years}")
    print(f"\n{'='*70}\n=== 純株式発行アノマリー(低発行群 vs 高発行群) ===\n{'='*70}")
    for m in FORWARD_MONTHS:
        g, b = pooled_good[m], pooled_bad[m]
        if g and b:
            diff = (pystats.mean(g) - pystats.mean(b)) * 100
            print(f"  {m}ヶ月後: 低発行(自社株買い方向)={pystats.mean(g)*100:+.1f}%"
                  f"(中央値{pystats.median(g)*100:+.1f}%, n={len(g)}) / "
                  f"高発行(希薄化)={pystats.mean(b)*100:+.1f}%"
                  f"(中央値{pystats.median(b)*100:+.1f}%, n={len(b)}) / 平均差={diff:+.1f}pt")
        else:
            print(f"  {m}ヶ月後: サンプル不足")

    print("  --- |r|>200%除外 ---")
    for m in FORWARD_MONTHS:
        g = [r for r in pooled_good[m] if abs(r) <= RET_CAP]
        b = [r for r in pooled_bad[m] if abs(r) <= RET_CAP]
        if g and b:
            diff = (pystats.mean(g) - pystats.mean(b)) * 100
            print(f"  {m}ヶ月後: 低発行={pystats.mean(g)*100:+.1f}%(n={len(g)}) / "
                  f"高発行={pystats.mean(b)*100:+.1f}%(n={len(b)}) / 差={diff:+.1f}pt")

    universe_label = "東証プライム全銘柄" if universe_tag == "prime" else "日経225(大型株中心)"
    print(f"\n注意: {universe_label}のみでの検証。決算発表タイミングは+60日で近似。"
          "生存バイアス(現行構成銘柄のみ)・DSR等の多重検定補正は未実施。")


if __name__ == "__main__":
    main()
