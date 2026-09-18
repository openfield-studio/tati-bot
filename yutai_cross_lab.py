#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人気株主優待銘柄限定での権利付き最終日効果(優待クロス)の検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

権利付き最終日/権利落ち日効果(FACTOR_RESEARCH_LOG.md #23、東証プライム全銘柄
平均+0.833%・勝率68.2%)は配当を含む全銘柄で検証済み。今回は「人気優待銘柄は
権利付き最終日に向けてより強く上昇する」という追加の言説(優待クロス取引の
思惑買いが集中するため)を、みんかぶ人気優待ランキング上位20銘柄限定で検証し、
一般母集団(全銘柄平均)より効果が強いかを比較する。

出典: みんかぶ 株主優待人気ランキング(2026-09-18取得、上位20銘柄)

使い方: python yutai_cross_lab.py
"""
from __future__ import annotations
import statistics as pystats

import yfinance as yf

RET_CAP = 2.0

# みんかぶ株主優待人気ランキング上位20(2026-09-18取得)
POPULAR_YUTAI = [
    ("7241", "フタバ産業"), ("8783", "ａｂｃ"), ("4376", "くふうカンパニーHD"),
    ("9432", "NTT"), ("9973", "KOZOホールディングス"), ("545A", "トランヴィア"),
    ("8766", "東京海上HD"), ("3726", "フォーシーズHD"), ("4997", "日本農薬"),
    ("2264", "森永乳業"), ("4290", "プレステージ・インターナショナル"),
    ("3205", "ダイドーリミテッド"), ("4755", "楽天グループ"), ("7278", "エクセディ"),
    ("8316", "三井住友FG"), ("2201", "森永製菓"), ("2695", "くら寿司"),
    ("9434", "ソフトバンク"), ("7856", "萩原工業"), ("6186", "一蔵"),
]

# 一般母集団(東証プライム全銘柄、seasonal_effects_lab.pyの既存結果、SESSION_LOG項目45)
BASELINE_MEAN = 0.00833
BASELINE_WIN_RATE = 68.2
BASELINE_N = 17890


def analyze_stock(code: str) -> list[float]:
    try:
        ticker = yf.Ticker(f"{code}.T")
        df = ticker.history(period="7y", interval="1d")
        divs = ticker.dividends
    except Exception:
        return []
    df = df.dropna(subset=["Close"])
    if len(df) < 300 or divs is None or len(divs) == 0:
        return []
    closes = df["Close"].tolist()
    dates = [d.date() for d in df.index]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n = len(closes)

    out = []
    for div_date, _ in divs.items():
        d = div_date.date()
        idx = date_to_idx.get(d)
        if idx is None:
            best = None
            for i2, dt2 in enumerate(dates):
                diff = abs((dt2 - d).days)
                if diff <= 3 and (best is None or diff < best[1]):
                    best = (i2, diff)
            idx = best[0] if best else None
        if idx is None or idx < 2 or idx >= n:
            continue
        out.append(closes[idx - 1] / closes[idx - 2] - 1)  # 権利付き最終日の値動き
    return out


def main() -> None:
    all_rets = []
    for code, name in POPULAR_YUTAI:
        rets = analyze_stock(code)
        all_rets += rets
        if rets:
            print(f"  {code} {name}: n={len(rets)}, 平均{pystats.mean(rets)*100:+.2f}%")

    capped = [r for r in all_rets if abs(r) <= RET_CAP]
    print(f"\n合計観測数: {len(capped)}(人気優待銘柄{len(POPULAR_YUTAI)}銘柄)")
    if capped:
        win_rate = sum(1 for r in capped if r > 0) / len(capped) * 100
        print(f"人気優待銘柄の権利付き最終日: 平均{pystats.mean(capped)*100:+.3f}%"
              f"(中央値{pystats.median(capped)*100:+.3f}%, 勝率{win_rate:.1f}%, n={len(capped)})")
        print(f"一般母集団(全銘柄、既存結果): 平均{BASELINE_MEAN*100:+.3f}%"
              f"(勝率{BASELINE_WIN_RATE:.1f}%, n={BASELINE_N})")
        print(f"差: {(pystats.mean(capped)-BASELINE_MEAN)*100:+.3f}pt")

    print("\n注意: 人気優待ランキング上位20銘柄限定(みんかぶ、生存バイアスあり=現在の人気銘柄で"
          "過去に遡って検証しているため、過去時点でも人気だったとは限らない)。"
          "逆日歩(品貸料)等のクロス取引コストは未考慮。")


if __name__ == "__main__":
    main()
