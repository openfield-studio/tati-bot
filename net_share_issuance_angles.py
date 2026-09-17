#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
net_share_issuance_lab.pyの追加検証・別角度版
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

3分位での単純比較が外れ値除外前後で符号が入れ替わる(6ヶ月+0.3pt/12ヶ月-3.6pt
→ 外れ値除外後+1.5pt/+2.6pt)という境界線上の結果だったため、標準の多角的検証
(feedback_tati_bot_multi_angle_testing.md)を実施:

  A. 5分位(クインタイル)で見た場合、両極端の差がもっとはっきりするか
  B. 個別銘柄の割安さ(PER)と組み合わせ、「PER下位1/3(割安)銘柄群の中だけ」で
     追加的なリターン予測力を持つか

使い方: python net_share_issuance_angles.py
(nsi_cache_prime.json と individual_value_backtest_cache_prime.json が
 事前に存在している必要がある)
"""
from __future__ import annotations
import json
import statistics as pystats
from collections import defaultdict

FORWARD_MONTHS = [6, 12]
CAP = 2.0


def load_nsi():
    return json.load(open("nsi_cache_prime.json", encoding="utf-8"))


def load_value():
    return json.load(open("individual_value_backtest_cache_prime.json", encoding="utf-8"))


def quintile_test(all_obs):
    print("\n" + "=" * 70)
    print("=== 角度A: 5分位(クインタイル)で見た場合 ===")
    print("=" * 70)
    years = sorted(set(o["fiscal_year"] for o in all_obs))
    pooled_good = defaultdict(list)
    pooled_bad = defaultdict(list)
    for year in years:
        yr_obs = sorted([o for o in all_obs if o["fiscal_year"] == year], key=lambda o: o["net_share_issuance"])
        n = len(yr_obs)
        q = n // 5
        if q < 5:
            continue
        low_group = yr_obs[:q]    # 発行少ない(自社株買い方向)
        high_group = yr_obs[-q:]  # 発行多い(希薄化)
        for m in FORWARD_MONTHS:
            pooled_good[m] += [o[f"ret{m}"] for o in low_group if o.get(f"ret{m}") is not None]
            pooled_bad[m] += [o[f"ret{m}"] for o in high_group if o.get(f"ret{m}") is not None]
    for m in FORWARD_MONTHS:
        g = [r for r in pooled_good[m] if abs(r) <= CAP]
        b = [r for r in pooled_bad[m] if abs(r) <= CAP]
        if g and b:
            diff = (pystats.mean(g) - pystats.mean(b)) * 100
            print(f"  {m}ヶ月後: 低発行1/5={pystats.mean(g)*100:+.1f}%(中央値{pystats.median(g)*100:+.1f}%, n={len(g)}) / "
                  f"高発行1/5={pystats.mean(b)*100:+.1f}%(中央値{pystats.median(b)*100:+.1f}%, n={len(b)}) / 差={diff:+.1f}pt")
        else:
            print(f"  {m}ヶ月後: サンプル不足")


def value_combo_test(all_obs, value_obs):
    print("\n" + "=" * 70)
    print("=== 角度B: PER下位1/3(割安)銘柄群の中だけで見た場合 ===")
    print("=" * 70)

    value_by_year = defaultdict(list)
    for o in value_obs:
        value_by_year[o["fiscal_year"]].append(o)

    cheap_keys = set()
    for year, yr_obs in value_by_year.items():
        yr_sorted = sorted(yr_obs, key=lambda o: o["per"])
        n = len(yr_sorted)
        tercile = n // 3
        if tercile < 5:
            continue
        for o in yr_sorted[:tercile]:
            cheap_keys.add((o["code"], o["fiscal_year"]))

    print(f"割安(PER下位1/3)判定できた(銘柄, 年度)組: {len(cheap_keys)}")

    obs_with_key = [o for o in all_obs if (o["code"], o["fiscal_year"]) in cheap_keys]
    years = sorted(set(o["fiscal_year"] for o in obs_with_key))
    pooled_good = defaultdict(list)
    pooled_bad = defaultdict(list)
    for year in years:
        yr_obs = sorted([o for o in obs_with_key if o["fiscal_year"] == year], key=lambda o: o["net_share_issuance"])
        n = len(yr_obs)
        tercile = n // 3
        if tercile < 5:
            continue
        low_group = yr_obs[:tercile]
        high_group = yr_obs[-tercile:]
        for m in FORWARD_MONTHS:
            pooled_good[m] += [o[f"ret{m}"] for o in low_group if o.get(f"ret{m}") is not None]
            pooled_bad[m] += [o[f"ret{m}"] for o in high_group if o.get(f"ret{m}") is not None]
    print(f"\n--- 割安銘柄群の中で純株式発行アノマリー({len(obs_with_key)}観測) ---")
    for m in FORWARD_MONTHS:
        g = [r for r in pooled_good[m] if abs(r) <= CAP]
        b = [r for r in pooled_bad[m] if abs(r) <= CAP]
        if g and b:
            diff = (pystats.mean(g) - pystats.mean(b)) * 100
            print(f"  {m}ヶ月後: 低発行={pystats.mean(g)*100:+.1f}%(n={len(g)}) / "
                  f"高発行={pystats.mean(b)*100:+.1f}%(n={len(b)}) / 差={diff:+.1f}pt")
        else:
            print(f"  {m}ヶ月後: サンプル不足")


def main():
    all_obs = load_nsi()
    value_obs = load_value()
    print(f"nsi観測数: {len(all_obs)} / value観測数: {len(value_obs)}")
    quintile_test(all_obs)
    value_combo_test(all_obs, value_obs)
    print("\n注意: 東証プライム全銘柄の既存キャッシュ済みデータの再分析(新規データ取得なし)。"
          "サンプル細分化により1グループあたりのnが減るため、統計的なブレは増える点に留意。")


if __name__ == "__main__":
    main()
