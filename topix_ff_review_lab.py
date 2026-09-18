#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOPIX浮動株比率定期見直し(実施日=10月最終営業日)の指数レベル効果の検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

日経225定期入れ替え効果(SESSION_LOG項目51)に続く「特定の日に値動きが起きる」
候補としてTOPIX浮動株比率の定期見直しを調査したが、個別銘柄ごとのウエイト
増減の過去データは(日経225の入れ替えと違って)クリーンな二次情報源が見当たらず、
個別銘柄レベルでのイベントスタディは断念した。

代わりに、tati-botが実際に保有する1306(TOPIX連動ETF)そのものが、東証発表の
公表日(10月第5営業日)〜実施日(10月最終営業日)にかけて指数レベルで特徴的な
値動きを示すかを、2009年以降の過去の10月末で検証する。

★重要な限界★
2026年10月からTOPIX改革の「第2段階見直し」が四半期ごとの新方式で初回実施される
予定であり、これは過去の「年1回・10月」という枠組みとは異なる制度変更である。
つまり過去の10月効果が観測できたとしても、今年以降にそのまま当てはまる保証はない
(制度自体が変わるため)。

使い方: python topix_ff_review_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats

import yfinance as yf

WINDOW = 10  # 営業日


def main() -> None:
    df = yf.Ticker("1306.T").history(period="max")
    df = df[df["Close"].notna()]
    dates = sorted(idx.date() for idx in df.index)
    closes = {idx.date(): float(row["Close"]) for idx, row in df.iterrows()}
    idx_of = {d: i for i, d in enumerate(dates)}

    # 各年の「10月最終営業日」を特定
    years = sorted(set(d.year for d in dates))
    oct_month_ends = []
    for y in years:
        oct_days = [d for d in dates if d.year == y and d.month == 10]
        if oct_days:
            oct_month_ends.append(max(oct_days))

    print(f"データ範囲: {dates[0]} 〜 {dates[-1]}({len(dates)}日)")
    print(f"対象年数: {len(oct_month_ends)}年({oct_month_ends[0].year}〜{oct_month_ends[-1].year})")

    runup_rets, reversal_rets = [], []
    for eff in oct_month_ends:
        i = idx_of[eff]
        if i - WINDOW < 0 or i + WINDOW >= len(dates):
            continue
        runup_rets.append(closes[dates[i]] / closes[dates[i - WINDOW]] - 1)
        reversal_rets.append(closes[dates[i + WINDOW]] / closes[dates[i]] - 1)

    # 比較対象: 全期間における「任意のWINDOW営業日リターン」の分布(ベースライン)
    # 1306の価格データに分割調整漏れと思われる異常値(2014年末〜2015年始で-90%、
    # 2026年春で+900%超)が混入していたため、10営業日リターンとして非現実的な
    # |r|>30%は異常値として除外する(TOPIX ETFが10営業日で30%動くのはコロナ
    # ショック級でも稀)。
    BASELINE_CAP = 0.3
    all_window_rets_raw = [closes[dates[i]] / closes[dates[i - WINDOW]] - 1
                            for i in range(WINDOW, len(dates))]
    all_window_rets = [r for r in all_window_rets_raw if abs(r) <= BASELINE_CAP]
    n_excluded = len(all_window_rets_raw) - len(all_window_rets)

    def report(label, data):
        print(f"  {label}: 平均={pystats.mean(data)*100:+.2f}%(中央値{pystats.median(data)*100:+.2f}%, "
              f"標準偏差{pystats.pstdev(data)*100:.2f}%, n={len(data)})")

    print(f"\n=== 10月末(公表〜実施日の近似、直前{WINDOW}営業日) ===")
    report("10月末までのrun-up", runup_rets)
    print(f"\n=== 実施日後{WINDOW}営業日 ===")
    report("10月末からの事後", reversal_rets)
    print(f"\n=== 参考: 全期間における任意の{WINDOW}営業日リターンの分布(ベースライン、"
          f"異常値{n_excluded}件除外) ===")
    report("ベースライン", all_window_rets)

    print("\n注意: 1306(TOPIX連動ETF)自体の指数レベル効果であり、個別銘柄の裁定機会では"
          "ない(ウエイト増減銘柄ごとの売買機会は未検証、クリーンな二次データ源なし)。"
          "2026年10月からは制度自体が年1回→四半期ごとに変わるため、過去の10月効果が"
          "そのまま今後も続く保証はない点に留意。")


if __name__ == "__main__":
    main()
