#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
純株式発行アノマリーの「下げ相場限定」検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

net_share_issuance_lab.py --prime の全期間3分位結果が外れ値除外前後で符号が
入れ替わる境界線上の結果だったため、defensive_stock_lab.py / new_factors_crash_lab.py
と同じ実際の急落局面に限定して、自社株買い方向(低発行)の銘柄が下げ相場に
強いか(防御力があるか)を検証する。

★先読みバイアス対策★
各急落局面の開始(peak)より前に開示済み(FYE+60日 <= peak)の最新の発行済株式数
データだけを使う。

対象の下落局面(new_factors_crash_lab.pyと同じ):
  2024年8月急落: 2024-07-11(高値)〜2024-08-05(底)
  2025年4月急落: 2024-12-27(高値)〜2025-04-07(底)

使い方: python net_share_issuance_crash_lab.py --prime
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import os
import sys
import statistics as pystats

import yfinance as yf

CHECKPOINT_EVERY = 25

CRASHES = [
    {"name": "2024年8月急落", "peak": "2024-07-11", "trough": "2024-08-05"},
    {"name": "2025年4月急落(2024年末からの続落)", "peak": "2024-12-27", "trough": "2025-04-07"},
]


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def crash_return(ticker_obj, peak: str, trough: str) -> float | None:
    end = (dt.date.fromisoformat(trough) + dt.timedelta(days=3)).isoformat()
    try:
        df = ticker_obj.history(start=peak, end=end, interval="1d")
    except Exception:
        return None
    if df.empty or len(df) < 2:
        return None
    trough_date = dt.date.fromisoformat(trough)
    df_up_to_trough = df[df.index.date <= trough_date]
    if df_up_to_trough.empty:
        return None
    return float(df_up_to_trough["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1


def g(df, key, col):
    try:
        v = df.loc[key, col]
        return float(v) if v == v else None
    except (KeyError, TypeError):
        return None


def latest_known_issuance(bs, cutoff_date: dt.date) -> float | None:
    """cutoff_date(急落開始日)より前に開示済みの最新の純株式発行率を返す。"""
    if "Ordinary Shares Number" not in bs.index:
        return None
    bs_cols = sorted(bs.columns)
    best = None
    for i in range(1, len(bs_cols)):
        fye = bs_cols[i]
        reveal = fye.to_pydatetime().date() + dt.timedelta(days=60)
        if reveal > cutoff_date:
            continue
        shares_cur = g(bs, "Ordinary Shares Number", fye)
        shares_prev = g(bs, "Ordinary Shares Number", bs_cols[i - 1])
        if not shares_cur or not shares_prev or shares_prev <= 0:
            continue
        best = (reveal, shares_cur / shares_prev - 1)
    return best[1] if best else None


def collect(code: str) -> dict:
    result = {}
    try:
        t = yf.Ticker(f"{code}.T")
        bs = t.balance_sheet
    except Exception:
        return result
    if bs is None or bs.empty:
        return result

    for crash in CRASHES:
        cutoff = dt.date.fromisoformat(crash["peak"])
        issuance = latest_known_issuance(bs, cutoff)
        if issuance is None:
            continue
        cret = crash_return(yf.Ticker(f"{code}.T"), crash["peak"], crash["trough"])
        if cret is None:
            continue
        result[crash["name"]] = {"net_share_issuance": issuance, "crash_return": cret}
    return result


def main() -> None:
    universe = load_universe()
    tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"nsi_crash_checkpoint_{tag}.json"
    cache_path = f"nsi_crash_cache_{tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        all_data = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            saved = json.load(open(checkpoint_path, encoding="utf-8"))
            all_data = saved["data"]
            done_codes = set(saved["done_codes"])
            print(f"チェックポイントから再開: {len(done_codes)}銘柄処理済み")
        else:
            all_data = {}
            done_codes = set()

        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{tag}、残り{len(todo)}/{len(universe)}銘柄を処理中...")
        for i, (code, name) in enumerate(todo, 1):
            r = collect(code)
            if r:
                all_data[code] = r
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"data": all_data, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(有効銘柄 累計{len(all_data)})...")

        json.dump(all_data, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n有効銘柄数: {len(all_data)}\n")

    for crash in CRASHES:
        cname = crash["name"]
        print(f"\n{'='*70}\n=== {cname}({crash['peak']}〜{crash['trough']}) ===\n{'='*70}")
        try:
            mkt_ret = crash_return(yf.Ticker("^N225"), crash["peak"], crash["trough"])
            print(f"日経225自体の下落率: {mkt_ret*100:+.1f}%" if mkt_ret else "日経225下落率: 取得失敗")
        except Exception:
            pass

        rows = [(code, d[cname]["net_share_issuance"], d[cname]["crash_return"])
                for code, d in all_data.items() if cname in d]
        if len(rows) < 15:
            print(f"\n--- サンプル不足(n={len(rows)}) ---")
            continue
        rows.sort(key=lambda r: r[1])
        n = len(rows)
        tercile = n // 3
        low_group = rows[:tercile]    # 発行少ない(自社株買い方向)
        high_group = rows[-tercile:]  # 発行多い(希薄化)
        low_avg = pystats.mean([r[2] for r in low_group])
        high_avg = pystats.mean([r[2] for r in high_group])
        print(f"\n--- 純株式発行アノマリー(n={n}) ---")
        print(f"  低発行群平均: {low_avg*100:+.1f}%(n={len(low_group)}) / "
              f"高発行群平均: {high_avg*100:+.1f}%(n={len(high_group)}) / "
              f"差={((low_avg-high_avg)*100):+.1f}pt(プラスなら低発行の方が下げに強かった)")

    print("\n注意: 2局面とも同じ2024年マクロショック由来の可能性があり完全独立ではない。"
          "n数が少ないため統計的なブレが大きい点に留意。")


if __name__ == "__main__":
    main()
