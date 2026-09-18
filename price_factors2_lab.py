#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学術ファクター第2弾(株価ベース2個)の一括検証: 長期リバーサル・BAB
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

  1. 長期リバーサル(De Bondt & Thaler 1985、日本では加藤1990・Chou et al. 2007):
     過去36ヶ月の負け組が勝ち組を上回る(日本は勝ち組の反落が特に強いとの報告)。
  2. Betting Against Beta(Frazzini & Pedersen 2014): 低βが高βを上回るかを、
     通常期間(急落局面限定ではない)の月次スナップショットで検証する。
     既存の低β検証(defensive_stock_lab.py)は急落局面限定の防御力測定であり、
     本検証は構築法が異なる(通常時のクロスセクショナル比較)。

academic_factors_lab.py/max_effect_lab.pyと同じ月次スナップショット方式
(先読み回避: 各月末時点で確定済みの過去データのみ使用)。

使い方: python price_factors2_lab.py --prime
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
RET_CAP = 2.0
LOOKBACK_MONTHS_REVERSAL = 36
LOOKBACK_MONTHS_BETA = 24
STEP_MONTHS = 6  # スナップショット間隔(重複を減らすため)


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def monthly_series(hist):
    """月末終値のリスト(日付昇順)を返す。"""
    df = hist.dropna(subset=["Close"])
    by_month = {}
    for idx, row in df.iterrows():
        key = (idx.year, idx.month)
        by_month[key] = (idx.date(), float(row["Close"]))
    return [by_month[k] for k in sorted(by_month.keys())]


def collect(code: str, mkt_monthly) -> list[dict]:
    try:
        hist = yf.Ticker(f"{code}.T").history(period="max", interval="1d")
    except Exception:
        return []
    if hist.empty:
        return []
    monthly = monthly_series(hist)
    if len(monthly) < LOOKBACK_MONTHS_REVERSAL + max(FORWARD_MONTHS) + 1:
        return []
    n = len(monthly)
    mkt_dates = [d for d, _ in mkt_monthly]
    mkt_closes = {d: c for d, c in mkt_monthly}

    out = []
    for i in range(LOOKBACK_MONTHS_REVERSAL, n - max(FORWARD_MONTHS), STEP_MONTHS):
        d0, p0 = monthly[i]
        obs = {"code": code, "date": d0.isoformat()}

        # 長期リバーサル: 過去36ヶ月リターン
        d_rev, p_rev = monthly[i - LOOKBACK_MONTHS_REVERSAL]
        obs["past_36m_ret"] = p0 / p_rev - 1

        # BAB: 過去24ヶ月の月次リターンから対TOPIX(1306)ベータを回帰
        if i - LOOKBACK_MONTHS_BETA >= 0:
            stock_rets, mkt_rets = [], []
            for j in range(i - LOOKBACK_MONTHS_BETA + 1, i + 1):
                d_prev, p_prev = monthly[j - 1]
                d_cur, p_cur = monthly[j]
                if d_prev in mkt_closes and d_cur in mkt_closes:
                    stock_rets.append(p_cur / p_prev - 1)
                    mkt_rets.append(mkt_closes[d_cur] / mkt_closes[d_prev] - 1)
            if len(stock_rets) >= 18:
                mean_m = pystats.mean(mkt_rets)
                var_m = sum((r - mean_m) ** 2 for r in mkt_rets)
                if var_m > 0:
                    mean_s = pystats.mean(stock_rets)
                    cov = sum((mkt_rets[k] - mean_m) * (stock_rets[k] - mean_s) for k in range(len(stock_rets)))
                    obs["beta"] = cov / var_m

        # 前方リターン(月次刻みで近似)
        for m in FORWARD_MONTHS:
            steps = round(m / 1)  # 月次データなのでmヶ月=mステップ
            if i + steps < n:
                d1, p1 = monthly[i + steps]
                obs[f"ret{m}"] = p1 / p0 - 1

        if "past_36m_ret" in obs or "beta" in obs:
            out.append(obs)
    return out


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"price2_checkpoint_{universe_tag}.json"
    cache_path = f"price2_cache_{universe_tag}.json"

    mkt_hist = yf.Ticker("1306.T").history(period="max", interval="1d")
    mkt_monthly = monthly_series(mkt_hist)

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
        print(f"{universe_tag}、残り{len(todo)}/{len(universe)}銘柄を処理中...")
        for i, (code, name) in enumerate(todo, 1):
            all_obs += collect(code, mkt_monthly)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"observations": all_obs, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(観測数 累計{len(all_obs)})...")

        json.dump(all_obs, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n合計観測数: {len(all_obs)}\n")

    for key, label, low_is_good in [("past_36m_ret", "長期リバーサル(過去36ヶ月、低い=負け組が良いはず)", True),
                                     ("beta", "BAB(過去24ヶ月ベータ、低い方が良いはず)", True)]:
        print(f"{'='*70}\n=== {label} ===\n{'='*70}")
        obs_with_key = [o for o in all_obs if key in o]
        dates_ = sorted(set(o["date"][:7] for o in obs_with_key))  # 年月でグルーピング
        pooled_good = defaultdict(list)
        pooled_bad = defaultdict(list)
        for ym in dates_:
            yr_obs = [o for o in obs_with_key if o["date"][:7] == ym]
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

    print("注意: 月次スナップショット(6ヶ月おき)、東証プライム全銘柄。生存バイアス・"
          "DSR等の多重検定補正は未実施。BABは本来のレバレッジ調整・ベータ中立化を"
          "行わない簡易版(単純なテルシル比較)。")


if __name__ == "__main__":
    main()
