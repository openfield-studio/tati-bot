#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_factors_lab.py(粗利益収益性・アクルーアル・資産成長率)の追加検証・別角度版
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

new_factors_lab.py --prime の結果(粗利益収益性・アクルーアルが逆転、資産成長が
プラス)を受けて、以下2つの角度から追検証する(いずれも既存キャッシュを再利用、
新規データ取得なし):

  A. 3分位ではなく5分位(クインタイル)で見た場合、上位/下位の両極端だけを
     比較すると効果がもっとはっきり(または逆にもっと曖昧に)見えるか。
  B. 個別銘柄の割安さ(PER、リーダーボード1位)と組み合わせ、「PER下位1/3
     (割安)の銘柄群の中だけ」で見た場合、粗利益収益性・アクルーアル・資産成長率が
     追加的なリターン予測力を持つか(質フィルターとしての価値があるか)。

使い方: python new_factors_angles.py
(new_factors_cache_prime.json と individual_value_backtest_cache_prime.json が
 事前に存在している必要がある)
"""
from __future__ import annotations
import json
import statistics as pystats
from collections import defaultdict

FACTORS = [
    ("gross_profitability", "粗利益収益性(高い方が良いはず)", False),
    ("accruals", "アクルーアル(低い方が良いはず)", True),
    ("asset_growth", "資産成長率(低い方が良いはず)", True),
]
FORWARD_MONTHS = [6, 12]
CAP = 2.0


def load_new_factors():
    return json.load(open("new_factors_cache_prime.json", encoding="utf-8"))


def load_value():
    return json.load(open("individual_value_backtest_cache_prime.json", encoding="utf-8"))


def quintile_test(all_obs):
    print("\n" + "=" * 70)
    print("=== 角度A: 5分位(クインタイル)で見た場合 ===")
    print("=" * 70)
    for key, label, low_is_good in FACTORS:
        obs_with_key = [o for o in all_obs if key in o]
        years = sorted(set(o["fiscal_year"] for o in obs_with_key))
        pooled_good = defaultdict(list)
        pooled_bad = defaultdict(list)
        for year in years:
            yr_obs = sorted([o for o in obs_with_key if o["fiscal_year"] == year], key=lambda o: o[key])
            n = len(yr_obs)
            q = n // 5
            if q < 5:
                continue
            low_group = yr_obs[:q]
            high_group = yr_obs[-q:]
            good, bad = (low_group, high_group) if low_is_good else (high_group, low_group)
            for m in FORWARD_MONTHS:
                pooled_good[m] += [o[f"ret{m}"] for o in good if o.get(f"ret{m}") is not None]
                pooled_bad[m] += [o[f"ret{m}"] for o in bad if o.get(f"ret{m}") is not None]
        print(f"\n--- {label} ---")
        for m in FORWARD_MONTHS:
            g = [r for r in pooled_good[m] if abs(r) <= CAP]
            b = [r for r in pooled_bad[m] if abs(r) <= CAP]
            if g and b:
                diff = (pystats.mean(g) - pystats.mean(b)) * 100
                print(f"  {m}ヶ月後: 上位1/5群={pystats.mean(g)*100:+.1f}%(中央値{pystats.median(g)*100:+.1f}%, n={len(g)}) / "
                      f"下位1/5群={pystats.mean(b)*100:+.1f}%(中央値{pystats.median(b)*100:+.1f}%, n={len(b)}) / 差={diff:+.1f}pt")
            else:
                print(f"  {m}ヶ月後: サンプル不足")


def value_combo_test(all_obs, value_obs):
    print("\n" + "=" * 70)
    print("=== 角度B: PER下位1/3(割安)銘柄群の中だけで見た場合 ===")
    print("=" * 70)

    # (code, fiscal_year)ごとにPER下位1/3かどうかを判定
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

    for key, label, low_is_good in FACTORS:
        obs_with_key = [o for o in all_obs if key in o and (o["code"], o["fiscal_year"]) in cheap_keys]
        years = sorted(set(o["fiscal_year"] for o in obs_with_key))
        pooled_good = defaultdict(list)
        pooled_bad = defaultdict(list)
        for year in years:
            yr_obs = sorted([o for o in obs_with_key if o["fiscal_year"] == year], key=lambda o: o[key])
            n = len(yr_obs)
            tercile = n // 3
            if tercile < 5:
                continue
            low_group = yr_obs[:tercile]
            high_group = yr_obs[-tercile:]
            good, bad = (low_group, high_group) if low_is_good else (high_group, low_group)
            for m in FORWARD_MONTHS:
                pooled_good[m] += [o[f"ret{m}"] for o in good if o.get(f"ret{m}") is not None]
                pooled_bad[m] += [o[f"ret{m}"] for o in bad if o.get(f"ret{m}") is not None]
        print(f"\n--- 割安銘柄群の中で: {label} ({len(obs_with_key)}観測) ---")
        for m in FORWARD_MONTHS:
            g = [r for r in pooled_good[m] if abs(r) <= CAP]
            b = [r for r in pooled_bad[m] if abs(r) <= CAP]
            if g and b:
                diff = (pystats.mean(g) - pystats.mean(b)) * 100
                print(f"  {m}ヶ月後: 良い質群={pystats.mean(g)*100:+.1f}%(中央値{pystats.median(g)*100:+.1f}%, n={len(g)}) / "
                      f"悪い質群={pystats.mean(b)*100:+.1f}%(中央値{pystats.median(b)*100:+.1f}%, n={len(b)}) / 差={diff:+.1f}pt")
            else:
                print(f"  {m}ヶ月後: サンプル不足")

    # 参考: 割安銘柄全体の平均リターン(質フィルターなし)
    print("\n--- 参考: 割安銘柄(PER下位1/3)全体の平均リターン ---")
    for m in FORWARD_MONTHS:
        rets = [o[f"ret{m}"] for o in value_obs if (o["code"], o["fiscal_year"]) in cheap_keys and o.get(f"ret{m}") is not None]
        rets = [r for r in rets if abs(r) <= CAP]
        if rets:
            print(f"  {m}ヶ月後: 平均={pystats.mean(rets)*100:+.1f}%(中央値{pystats.median(rets)*100:+.1f}%, n={len(rets)})")


def main():
    all_obs = load_new_factors()
    value_obs = load_value()
    print(f"new_factors観測数: {len(all_obs)} / value観測数: {len(value_obs)}")
    quintile_test(all_obs)
    value_combo_test(all_obs, value_obs)
    print("\n注意: 東証プライム全銘柄・6年分のキャッシュ済みデータの再分析(新規データ取得なし)。"
          "サンプル細分化により1グループあたりのnが減るため、統計的なブレは増える点に留意。")


if __name__ == "__main__":
    main()
