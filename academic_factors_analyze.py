#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
academic_factors_lab.pyが集めたデータを分析する(5つの学術ファクターの検証結果)。
使い方: python academic_factors_analyze.py
"""
from __future__ import annotations
import json
import statistics as pystats

CHECKPOINT_PATH = "academic_factors_checkpoint.json"


def tercile_compare(items: list[dict], score_key: str, fwd_key: str, reverse_low_is_first=True):
    """score_keyでソートし、下位1/3・上位1/3のfwd_key平均を比較する。"""
    items = [x for x in items if x.get(score_key) is not None and x.get(fwd_key) is not None]
    if len(items) < 30:
        return None
    items.sort(key=lambda x: x[score_key])
    n = len(items)
    t = n // 3
    low = items[:t]
    high = items[-t:]
    return {
        "n": n,
        "low_avg": pystats.mean(x[fwd_key] for x in low),
        "high_avg": pystats.mean(x[fwd_key] for x in high),
        "low_n": len(low), "high_n": len(high),
    }


def main() -> None:
    data = json.load(open(CHECKPOINT_PATH, encoding="utf-8"))
    print(f"読み込んだ銘柄数: {len(data)}\n")

    # --- 1. モメンタム ---
    momentum_items = [m for d in data for m in d["momentum"]]
    print(f"=== 1. モメンタム効果(過去12ヶ月[直近1ヶ月除く]リターン順、n観測={len(momentum_items)}) ===")
    r = tercile_compare(momentum_items, "score", "fwd60")
    if r:
        print(f"  弱モメンタム(下位1/3, n={r['low_n']}) その後60営業日平均: {r['low_avg']*100:+.2f}%")
        print(f"  強モメンタム(上位1/3, n={r['high_n']}) その後60営業日平均: {r['high_avg']*100:+.2f}%")
        print(f"  差: {(r['high_avg']-r['low_avg'])*100:+.2f}pt(プラスなら過去の勝ち組が引き続き強い)")

    # --- 2. 低ボラティリティ ---
    lowvol_items = [m for d in data for m in d["lowvol"]]
    print(f"\n=== 2. 低ボラティリティ・アノマリー(過去1年の日次リターン標準偏差、n観測={len(lowvol_items)}) ===")
    r = tercile_compare(lowvol_items, "score", "fwd60")
    if r:
        print(f"  低ボラ(下位1/3, n={r['low_n']}) その後60営業日平均: {r['low_avg']*100:+.2f}%")
        print(f"  高ボラ(上位1/3, n={r['high_n']}) その後60営業日平均: {r['high_avg']*100:+.2f}%")
        print(f"  差: {(r['low_avg']-r['high_avg'])*100:+.2f}pt(プラスなら低ボラの方が良い=アノマリー成立)")

    # --- 3. Piotroski Fスコア ---
    fscore_items = [f for d in data for f in d["fscore"]]
    print(f"\n=== 3. Piotroski Fスコア(0-9点、n観測={len(fscore_items)}) ===")
    if fscore_items:
        by_score = {}
        for f in fscore_items:
            by_score.setdefault(f["score"], []).append(f["fwd12mo"])
        for s in sorted(by_score.keys()):
            rets = [r for r in by_score[s] if abs(r) <= 3.0]
            if rets:
                print(f"  Fスコア{s}: n={len(rets)}  12ヶ月後平均{pystats.mean(rets)*100:+.1f}%")
        high = [r for f in fscore_items if f["score"] >= 7 for r in [f["fwd12mo"]] if abs(r) <= 3.0]
        low = [r for f in fscore_items if f["score"] <= 3 for r in [f["fwd12mo"]] if abs(r) <= 3.0]
        if high and low:
            print(f"  高スコア(7-9点, n={len(high)})平均: {pystats.mean(high)*100:+.1f}% / "
                  f"低スコア(0-3点, n={len(low)})平均: {pystats.mean(low)*100:+.1f}% / "
                  f"差: {(pystats.mean(high)-pystats.mean(low))*100:+.1f}pt")

    # --- 4. PEAD ---
    pead_items = [p for d in data for p in d["pead"]]
    print(f"\n=== 4. 決算後モメンタム/PEAD(n観測={len(pead_items)}) ===")
    if pead_items:
        pos = [p["fwd20d"] for p in pead_items if p["surprise"] > 5]
        neg = [p["fwd20d"] for p in pead_items if p["surprise"] < -5]
        neu = [p["fwd20d"] for p in pead_items if -5 <= p["surprise"] <= 5]
        if pos:
            print(f"  好サプライズ(予想比+5%超, n={len(pos)}): 決算後20営業日平均{pystats.mean(pos)*100:+.2f}%")
        if neu:
            print(f"  ほぼ予想通り(±5%以内, n={len(neu)}): 決算後20営業日平均{pystats.mean(neu)*100:+.2f}%")
        if neg:
            print(f"  悪サプライズ(予想比-5%超, n={len(neg)}): 決算後20営業日平均{pystats.mean(neg)*100:+.2f}%")
        if pos and neg:
            print(f"  好悪の差: {(pystats.mean(pos)-pystats.mean(neg))*100:+.2f}pt")

    # --- 5. 小型株効果 ---
    size_items = [d["size"] for d in data if d.get("size")]
    print(f"\n=== 5. 小型株効果(日経225内での時価総額比較、n={len(size_items)}) ===")
    print("  ※日経225自体が大型株中心のため、この検証には不利なユニバースである点に注意")
    r = tercile_compare(size_items, "market_cap", "total_return_3y")
    if r:
        print(f"  小型(下位1/3, n={r['low_n']}) 過去3年トータルリターン平均: {r['low_avg']*100:+.1f}%")
        print(f"  大型(上位1/3, n={r['high_n']}) 過去3年トータルリターン平均: {r['high_avg']*100:+.1f}%")
        print(f"  差: {(r['low_avg']-r['high_avg'])*100:+.1f}pt(プラスなら小型株効果が確認できた)")


if __name__ == "__main__":
    main()
