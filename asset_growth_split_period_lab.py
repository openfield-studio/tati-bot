#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
資産成長アノマリーの期間分割再現チェック
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

本体組み込みの昇格基準は「DSR通過(または同等の統計的有意性)」と「複数回・
別の期間での再現」の両方。前者は multi_testing_correction_lab.py で
Bonferroni補正後もp=0.0059と確認済み(SESSION_LOG項目40)。後者を確かめるため、
6年分(2021〜2026年度)のキャッシュ済みデータを前半・後半の2つの独立した期間に
分割し、それぞれで効果の方向・大きさが再現するかを見る(新規データ取得なし)。

前半: 2021〜2023年度 / 後半: 2024〜2026年度

使い方: python asset_growth_split_period_lab.py
"""
from __future__ import annotations
import json
import statistics as pystats

from scipy import stats

CAP = 2.0
FACTORS = [
    ("gross_profitability", "粗利益収益性(高い方が良いはず)", False),
    ("accruals", "アクルーアル(低い方が良いはず)", True),
    ("asset_growth", "資産成長率(低い方が良いはず)", True),
]


def tercile_groups(obs_with_key, key, low_is_good, ret_key):
    years = sorted(set(o["fiscal_year"] for o in obs_with_key))
    good, bad = [], []
    for year in years:
        yr_obs = sorted([o for o in obs_with_key if o["fiscal_year"] == year], key=lambda o: o[key])
        n = len(yr_obs)
        tercile = n // 3
        if tercile < 5:
            continue
        low_group = yr_obs[:tercile]
        high_group = yr_obs[-tercile:]
        g, b = (low_group, high_group) if low_is_good else (high_group, low_group)
        good += [o[ret_key] for o in g if o.get(ret_key) is not None]
        bad += [o[ret_key] for o in b if o.get(ret_key) is not None]
    good = [r for r in good if abs(r) <= CAP]
    bad = [r for r in bad if abs(r) <= CAP]
    return good, bad


def report(label, good, bad):
    if len(good) < 10 or len(bad) < 10:
        print(f"  {label}: サンプル不足(n_good={len(good)}, n_bad={len(bad)})")
        return
    diff_pt = (pystats.mean(good) - pystats.mean(bad)) * 100
    t_stat, p_value = stats.ttest_ind(good, bad, equal_var=False)
    print(f"  {label}: 差={diff_pt:+.1f}pt(n={len(good)}/{len(bad)}), "
          f"生のp値={p_value:.4f}{'(有意)' if p_value < 0.05 else '(非有意)'}")


def main() -> None:
    all_obs = json.load(open("new_factors_cache_prime.json", encoding="utf-8"))
    years = sorted(set(o["fiscal_year"] for o in all_obs))
    mid = years[len(years) // 2]
    first_half_years = [y for y in years if y < mid] or years[:len(years)//2]
    second_half_years = [y for y in years if y >= mid]
    print(f"対象年度: {years}")
    print(f"前半期間: {first_half_years} / 後半期間: {second_half_years}\n")

    for key, label, low_is_good in FACTORS:
        print(f"{'='*70}\n=== {label} ===\n{'='*70}")
        obs_with_key = [o for o in all_obs if key in o]
        for period_name, period_years in [("前半", first_half_years), ("後半", second_half_years)]:
            period_obs = [o for o in obs_with_key if o["fiscal_year"] in period_years]
            print(f"\n--- {period_name}({period_years}) ---")
            for m, ret_key in [(6, "ret6"), (12, "ret12")]:
                good, bad = tercile_groups(period_obs, key, low_is_good, ret_key)
                report(f"{m}ヶ月後", good, bad)

    print("\n注意: 2つの期間は完全に独立ではなく連続した時系列の前後半分割。"
          "真の意味での『別サイクルでの再現』(次の弱気相場等)とは異なる簡易チェック。")


if __name__ == "__main__":
    main()
