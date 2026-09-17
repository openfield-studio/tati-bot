#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ファクター研究ログ(累積18試行)への多重検定補正の代替手段
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

project_wide_dsr_lab.pyのDeflated Sharpe Ratio(DSR)は「実際にバックテストした
売買戦略の日次Sharpe比率」を前提にしている。しかしFACTOR_RESEARCH_LOG.mdの
18試行の大半は「群間のクロスセクショナルなリターン差(pt)」というDSRとは異なる
形式のため、そのままは適用できない(FACTOR_RESEARCH_LOG.md「統合DSRチェックの
実施履歴」参照)。

代わりに、生の観測データ(good群 vs bad群のリターン)が残っている5トライアル
(#2/#14 個別銘柄割安さ、#15 粗利益収益性、#16 アクルーアル、#17 資産成長率)に
ついて、Welchのt検定でp値を求め、**Bonferroni補正**(このプロジェクトでの累積
試行数N=18を掛ける、標準的な多重検定補正の1つ)をかけた場合にも有意性が
残るかを確認する。DSRと同じものではないが、「これだけ試したことを踏まえても
偶然とは考えにくいか」という同じ問いに答える、統計的に妥当な代替手段。

使い方: python multi_testing_correction_lab.py
"""
from __future__ import annotations
import json
import statistics as pystats

from scipy import stats

N_TRIALS = 18  # FACTOR_RESEARCH_LOG.md 2026-09-17時点の累積試行数
CAP = 2.0


def load_new_factors():
    return json.load(open("new_factors_cache_prime.json", encoding="utf-8"))


def load_value():
    return json.load(open("individual_value_backtest_cache_prime.json", encoding="utf-8"))


def tercile_groups(obs_with_key: list[dict], key: str, low_is_good: bool, ret_key: str):
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


def report(label: str, good: list[float], bad: list[float]):
    if len(good) < 10 or len(bad) < 10:
        print(f"\n--- {label}: サンプル不足 ---")
        return
    t_stat, p_value = stats.ttest_ind(good, bad, equal_var=False)  # Welchのt検定
    p_bonferroni = min(1.0, p_value * N_TRIALS)
    diff_pt = (pystats.mean(good) - pystats.mean(bad)) * 100
    print(f"\n--- {label} ---")
    print(f"  n(良い群)={len(good)}, n(悪い群)={len(bad)}, 差={diff_pt:+.1f}pt")
    print(f"  t統計量={t_stat:+.2f}, 生のp値={p_value:.4f}"
          f"({'有意(5%水準)' if p_value < 0.05 else '非有意'})")
    print(f"  Bonferroni補正後p値(×N={N_TRIALS})={p_bonferroni:.4f}"
          f"({'それでも有意(5%水準)' if p_bonferroni < 0.05 else '補正後は非有意'})")


def main() -> None:
    value_obs = load_value()
    new_obs = load_new_factors()

    print(f"個別銘柄割安さ観測数: {len(value_obs)} / 新規3ファクター観測数: {len(new_obs)}")
    print(f"Bonferroni補正の掛け目 N={N_TRIALS}(FACTOR_RESEARCH_LOG.md累積試行数)")

    # #2/#14: 個別銘柄割安さ(PER)。lowが良い(低PERが割安=良い)
    for m, ret_key in [(6, "ret6"), (12, "ret12")]:
        good, bad = tercile_groups(value_obs, "per", True, ret_key)
        report(f"個別銘柄の割安さ(PER、#14) {m}ヶ月後", good, bad)

    factors = [
        ("gross_profitability", "粗利益収益性(#15、高い方が良いはず)", False),
        ("accruals", "アクルーアル(#16、低い方が良いはず)", True),
        ("asset_growth", "資産成長率(#17、低い方が良いはず)", True),
    ]
    for key, label, low_is_good in factors:
        obs_with_key = [o for o in new_obs if key in o]
        for m, ret_key in [(6, "ret6"), (12, "ret12")]:
            good, bad = tercile_groups(obs_with_key, key, low_is_good, ret_key)
            report(f"{label} {m}ヶ月後", good, bad)

    print("\n注意: これはDeflated Sharpe Ratioそのものではなく、Bonferroni補正付き"
          "t検定という別の(ただし標準的な)多重検定補正手法。DSRは実際の売買戦略の"
          "Sharpe比率分布が必要なため、クロスセクショナルな群間比較には直接適用できない"
          "(FACTOR_RESEARCH_LOG.md参照)。それでも「これだけ試したことを踏まえても"
          "偶然とは考えにくいか」という同じ問いに答える目的では使える。")


if __name__ == "__main__":
    main()
