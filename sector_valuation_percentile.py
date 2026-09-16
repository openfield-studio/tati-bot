#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
業種別PER/PBRの現在位置(歴史的パーセンタイル)チェック
=====================================================================
※本体には組み込まない。sector_valuation_lab.pyが作ったjpx_sector_per_pbr_history.csv
(2013-01〜、東証33業種の月次PER/PBR)を使い、各業種の「今のPERが過去13年強の
分布の中でどのくらい割安な位置にあるか」をパーセンタイルで表示する。

パーセンタイルが低い(=0%に近い)ほど、その業種のPERは自分自身の過去と比べて
歴史的に低い(割安)水準にあることを意味する。逆に100%に近いほど歴史的に高い
(割高)水準。

★注意★ これはまだ「業種が割安なら本当にその後儲かるか」を検証したわけではない
(それには業種別の株価指数データが別途必要で未着手)。あくまで「今の位置づけ」の
一覧であり、次のステップとして検証(バックテスト)が必要な段階。

使い方: python sector_valuation_percentile.py
"""
from __future__ import annotations
import csv
import statistics as pystats
from collections import defaultdict

INDUSTRY_NAMES = {
    "1": "水産・農林業", "2": "鉱業", "3": "建設業", "4": "食料品",
    "5": "繊維製品", "6": "パルプ・紙", "7": "化学", "8": "医薬品",
    "9": "石油・石炭製品", "10": "ゴム製品", "11": "ガラス・土石製品",
    "12": "鉄鋼", "13": "非鉄金属", "14": "金属製品", "15": "機械",
    "16": "電気機器", "17": "輸送用機器", "18": "精密機器", "19": "その他製品",
    "20": "電気・ガス業", "21": "陸運業", "22": "海運業", "23": "空運業",
    "24": "倉庫・運輸関連業", "25": "情報・通信業", "26": "卸売業",
    "27": "小売業", "28": "銀行業", "29": "証券、商品先物取引業",
    "30": "保険業", "31": "その他金融業", "32": "不動産業", "33": "サービス業",
    "総合": "総合(全業種平均)",
}


def percentile_of_latest(series: list[tuple[str, float]]) -> tuple[float, float, int]:
    """(yearmonth, value)のリスト(時系列順)から、最新値が過去分布の中で
    何パーセンタイルかを返す。(パーセンタイル, 最新値, サンプル数)"""
    series = sorted(series, key=lambda x: x[0])
    values = [v for _, v in series]
    latest = values[-1]
    n = len(values)
    rank = sum(1 for v in values if v <= latest)
    return rank / n * 100, latest, n


def main() -> None:
    rows = list(csv.DictReader(open("jpx_sector_per_pbr_history.csv", encoding="utf-8-sig")))
    by_industry: dict[str, list[tuple[str, float]]] = defaultdict(list)
    by_industry_pbr: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        try:
            by_industry[r["industry_key"]].append((r["yearmonth"], float(r["per"])))
            by_industry_pbr[r["industry_key"]].append((r["yearmonth"], float(r["pbr"])))
        except (ValueError, KeyError):
            continue

    results = []
    for key, series in by_industry.items():
        if len(series) < 24:  # 2年未満のデータしかない場合はスキップ
            continue
        per_pct, per_latest, n = percentile_of_latest(series)
        pbr_pct, pbr_latest, _ = percentile_of_latest(by_industry_pbr[key])
        results.append({
            "key": key, "name": INDUSTRY_NAMES.get(key, key),
            "per_percentile": per_pct, "per_latest": per_latest,
            "pbr_percentile": pbr_pct, "pbr_latest": pbr_latest,
            "n_months": n,
        })

    # PERパーセンタイルが低い(歴史的に割安)順にソート、総合は末尾に固定表示
    industries = [r for r in results if r["key"] != "総合"]
    composite = [r for r in results if r["key"] == "総合"]
    industries.sort(key=lambda r: r["per_percentile"])

    print("=== 業種別PER・PBRの歴史的位置(2013-01〜、東証プライム/一部) ===")
    print("(パーセンタイルが低いほど、その業種は自分自身の過去と比べて今が割安)\n")
    print(f"{'業種':16s} {'PER':>7s} {'位置':>6s}   {'PBR':>6s} {'位置':>6s}  サンプル数")
    for r in industries:
        print(f"{r['name']:16s} {r['per_latest']:7.1f} {r['per_percentile']:5.1f}%   "
              f"{r['pbr_latest']:6.2f} {r['pbr_percentile']:5.1f}%   {r['n_months']}ヶ月")
    print()
    for r in composite:
        print(f"[参考]{r['name']:12s} {r['per_latest']:7.1f} {r['per_percentile']:5.1f}%   "
              f"{r['pbr_latest']:6.2f} {r['pbr_percentile']:5.1f}%   {r['n_months']}ヶ月")

    print("\n--- 歴史的に最も割安(PERパーセンタイル低い)TOP5 ---")
    for r in industries[:5]:
        print(f"  {r['name']}: PER{r['per_latest']:.1f}(過去比{r['per_percentile']:.0f}%位置)")
    print("--- 歴史的に最も割高(PERパーセンタイル高い)TOP5 ---")
    for r in industries[-5:][::-1]:
        print(f"  {r['name']}: PER{r['per_latest']:.1f}(過去比{r['per_percentile']:.0f}%位置)")


if __name__ == "__main__":
    main()
