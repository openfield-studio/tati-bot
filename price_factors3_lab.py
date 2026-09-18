#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学術ファクター第3弾(株価・出来高ベース2個)の一括検証: Amihud非流動性・無視された銘柄効果
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

  1. Amihud非流動性プレミアム(Amihud 2002): 出来高に対して値動きが大きい
     (価格インパクトが大きい=流動性が低い)銘柄ほど将来リターンが高いとされる。
     ILLIQ = 平均(|日次リターン| / 売買代金)
  2. 無視された銘柄効果(Arbel & Strebel 1983): アナリストのカバレッジが薄い
     銘柄が超過リターンを持つという説を、平均売買代金(規模)で代理する
     (直接のアナリスト数データはyfinanceでは取得不可)。

price_factors2_lab.pyと同じ月次スナップショット方式。

使い方: python price_factors3_lab.py --prime
"""
from __future__ import annotations
import csv
import statistics as pystats
import sys
import os
import json
from collections import defaultdict

import yfinance as yf

CHECKPOINT_EVERY = 25
FORWARD_MONTHS = [6, 12]
RET_CAP = 2.0
LOOKBACK_MONTHS = 12
STEP_MONTHS = 6


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def monthly_snapshots(hist):
    """(月末日, 終値, その月のAmihud非流動性, その月の平均売買代金)のリストを返す。"""
    df = hist.dropna(subset=["Close", "Volume"])
    if df.empty:
        return []
    df = df.copy()
    df["dollar_vol"] = df["Close"] * df["Volume"]
    df["ret"] = df["Close"].pct_change()
    df["illiq"] = (df["ret"].abs() / df["dollar_vol"]).replace([float("inf")], None)

    by_month = defaultdict(list)
    for idx, row in df.iterrows():
        by_month[(idx.year, idx.month)].append((idx.date(), row))

    out = []
    for key in sorted(by_month.keys()):
        rows = by_month[key]
        last_date, last_row = rows[-1]
        illiq_vals = [r["illiq"] for _, r in rows if r["illiq"] is not None and r["illiq"] == r["illiq"]]
        dv_vals = [r["dollar_vol"] for _, r in rows if r["dollar_vol"] is not None and r["dollar_vol"] == r["dollar_vol"]]
        if not illiq_vals or not dv_vals:
            continue
        out.append((last_date, float(last_row["Close"]),
                     pystats.mean(illiq_vals), pystats.mean(dv_vals)))
    return out


def collect(code: str) -> list[dict]:
    try:
        hist = yf.Ticker(f"{code}.T").history(period="max", interval="1d")
    except Exception:
        return []
    if hist.empty:
        return []
    snaps = monthly_snapshots(hist)
    if len(snaps) < LOOKBACK_MONTHS + max(FORWARD_MONTHS) + 1:
        return []
    n = len(snaps)
    out = []
    for i in range(LOOKBACK_MONTHS, n - max(FORWARD_MONTHS), STEP_MONTHS):
        window = snaps[i - LOOKBACK_MONTHS:i]
        illiq_avg = pystats.mean(w[2] for w in window)
        dv_avg = pystats.mean(w[3] for w in window)
        d0, p0 = snaps[i][0], snaps[i][1]
        obs = {"code": code, "date": d0.isoformat(), "illiq": illiq_avg, "dollar_vol": dv_avg}
        for m in FORWARD_MONTHS:
            steps = m
            if i + steps < n:
                obs[f"ret{m}"] = snaps[i + steps][1] / p0 - 1
        out.append(obs)
    return out


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"price3_checkpoint_{universe_tag}.json"
    cache_path = f"price3_cache_{universe_tag}.json"

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
            all_obs += collect(code)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"observations": all_obs, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(観測数 累計{len(all_obs)})...")

        json.dump(all_obs, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n合計観測数: {len(all_obs)}\n")

    for key, label, low_is_good in [("illiq", "Amihud非流動性(高い方が良いはず)", False),
                                     ("dollar_vol", "無視された銘柄効果(売買代金が低い方が良いはず)", True)]:
        print(f"{'='*70}\n=== {label} ===\n{'='*70}")
        obs_with_key = [o for o in all_obs if key in o and f"ret6" in o]
        dates_ = sorted(set(o["date"][:7] for o in obs_with_key))
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

    print("注意: 月次スナップショット(6ヶ月おき、直近12ヶ月平均)、東証プライム全銘柄。"
          "サイズファクター(#1)との相関(小型株ほど非流動的・売買代金も少ない)が"
          "強いと予想される点に留意。生存バイアス・DSR等の多重検定補正は未実施。")


if __name__ == "__main__":
    main()
