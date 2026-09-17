#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAX効果(宝くじ的値動き選好アノマリー)の検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

Bali, Cakici & Whitelaw (2011)「過去1ヶ月の最大日次リターン(MAX)が高い銘柄ほど、
その後のリターンが低い」というアノマリーを検証する。価格データのみで計算可能
(決算データ不要)なため、academic_factors_lab.pyのモメンタム/低ボラ検証と同じ
「月次スナップショット・ステップ21営業日」の枠組みを使う。

日本での既存研究(Chee 2012)は単純な1変量ソートでは効果を検出できなかったと
報告しているため、先入観なくフラットに確認する。

★先読みバイアス対策★
各時点iで「過去21営業日の最大日次リターン」を計算し、その後の21営業日
(約1ヶ月)・60営業日(約3ヶ月)の株価変化と比較する(academic_factors_lab.pyの
モメンタム計算と同じ考え方)。

使い方: python max_effect_lab.py --prime
"""
from __future__ import annotations
import csv
import json
import os
import sys
import statistics as pystats
from collections import defaultdict

import yfinance as yf

CHECKPOINT_EVERY = 25
FORWARD_STEPS = [21, 60]  # 約1ヶ月・3ヶ月
LOOKBACK = 21  # MAX計算の窓(過去1ヶ月)
STEP = 21  # 月次スナップショット


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def analyze_stock(code: str) -> list[dict]:
    out = []
    try:
        hist = yf.Ticker(f"{code}.T").history(period="7y", interval="1d")
    except Exception:
        return out
    if hist is None or len(hist) < LOOKBACK + max(FORWARD_STEPS) + 50:
        return out
    closes = hist["Close"].tolist()
    n = len(closes)

    for i in range(LOOKBACK, n - max(FORWARD_STEPS), STEP):
        window = closes[i - LOOKBACK:i]
        daily_rets = [window[j] / window[j - 1] - 1 for j in range(1, len(window))]
        if len(daily_rets) < LOOKBACK - 2:
            continue
        max_ret = max(daily_rets)
        obs = {"code": code, "date": hist.index[i].date().isoformat(), "max_ret": max_ret}
        for m in FORWARD_STEPS:
            obs[f"fwd{m}"] = closes[i + m] / closes[i] - 1
        out.append(obs)
    return out


def main() -> None:
    universe = load_universe()
    tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"max_effect_checkpoint_{tag}.json"
    cache_path = f"max_effect_cache_{tag}.json"

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
        print(f"{tag}、残り{len(todo)}/{len(universe)}銘柄の株価データを取得中...")
        for i, (code, name) in enumerate(todo, 1):
            all_obs += analyze_stock(code)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"observations": all_obs, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(観測数 累計{len(all_obs)}、チェックポイント保存)...")

        json.dump(all_obs, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n合計観測数: {len(all_obs)}\n")

    # 角度1: 全期間プール、3分位
    print("=" * 70)
    print("=== 角度1: 全期間プール、3分位(MAX低群 vs MAX高群) ===")
    print("=" * 70)
    # 時点(月)ごとにグルーピングして、その月のクロスセクションで3分位比較してからプール
    by_date = defaultdict(list)
    for o in all_obs:
        by_date[o["date"]].append(o)

    pooled_low = defaultdict(list)
    pooled_high = defaultdict(list)
    for date, obs_list in by_date.items():
        obs_sorted = sorted(obs_list, key=lambda o: o["max_ret"])
        n = len(obs_sorted)
        tercile = n // 3
        if tercile < 5:
            continue
        low_group = obs_sorted[:tercile]  # MAXが低い(宝くじ的でない)
        high_group = obs_sorted[-tercile:]  # MAXが高い(宝くじ的、理論上その後不振のはず)
        for m in FORWARD_STEPS:
            pooled_low[m] += [o[f"fwd{m}"] for o in low_group if o.get(f"fwd{m}") is not None]
            pooled_high[m] += [o[f"fwd{m}"] for o in high_group if o.get(f"fwd{m}") is not None]

    CAP = 2.0
    for m in FORWARD_STEPS:
        lo = [r for r in pooled_low[m] if abs(r) <= CAP]
        hi = [r for r in pooled_high[m] if abs(r) <= CAP]
        label = "約1ヶ月後" if m == 21 else "約3ヶ月後"
        if lo and hi:
            diff = (pystats.mean(lo) - pystats.mean(hi)) * 100
            print(f"{label}: MAX低群(宝くじ的でない)={pystats.mean(lo)*100:+.2f}%"
                  f"(中央値{pystats.median(lo)*100:+.2f}%, n={len(lo)}) / "
                  f"MAX高群(宝くじ的)={pystats.mean(hi)*100:+.2f}%"
                  f"(中央値{pystats.median(hi)*100:+.2f}%, n={len(hi)}) / "
                  f"差={diff:+.2f}pt(プラスなら理論通り=MAX低群の方が良い)")
        else:
            print(f"{label}: サンプル不足")

    print("\n注意: 東証プライム全銘柄・月次スナップショット(ステップ21営業日)でのプール検証。"
          "生存バイアス(現行構成銘柄のみ)・DSR等の多重検定補正は未実施。"
          "日本での先行研究(Chee 2012)はこの効果を検出できなかったと報告している。")


if __name__ == "__main__":
    main()
