#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日経225定期入れ替え効果(採用銘柄の実施日前上昇・除外銘柄の下落)の実証検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

権利付き最終日効果に続く「特定の日に値動きが起きる」候補として発見
(2026-09-18、ユーザー依頼)。学術研究(ScienceDirect等の査読済み論文複数)では、
日経225に新規採用される銘柄は発表日から実施日前日にかけて平均+5.7%程度の
累積異常リターンを示し(指数連動ファンドの機械的買いによる需要ショック)、
実施日以降に反落する、除外銘柄はその逆、というパターンが報告されている。

★データソースと限界★
過去の入れ替え履歴は日経平均プロフィル公式PDF(history_of_nikkei_stock_average_
component_changes_jp.pdf)の表組みが崩れて読み取れなかったため、二次情報サイト
(nikkeiyosoku.com)から取得した。銘柄コードの対応関係に若干の誤りが含まれる
可能性がある点に留意(特にNTTドコモ・ファミリーマート・ソニーフィナンシャル等の
除外は完全子会社化・非公開化に伴うもので、指数委員会の裁量による純粋な入れ替え
とは性質が異なる)。2026-10-01の入れ替えは既に発表済みだが実施前(進行中の
イベント)のため、反落側のデータはまだ存在しない。

★先読みバイアス対策★
実施日そのものより前のデータのみを「事前上昇」の測定に使う。発表日の正確な
日付までは追わず、実施日の35日前を発表後の期間の近似的な開始点とする
(半期定期見直しの発表は実施日の3〜4週間前が通例)。

使い方: python nikkei225_reconstitution_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats

import yfinance as yf

RUNUP_DAYS_BEFORE = 35   # 発表〜実施日前日の近似(実施日のX日前を起点とする)
REVERSAL_DAYS_AFTER = 15  # 実施日〜反落測定の終点(カレンダー日数)

# (実施日, 採用銘柄コードのリスト, 除外銘柄コードのリスト)
# 出典: nikkeiyosoku.com「日経平均株価の銘柄入れ替え履歴」(2026-09-18取得)
EVENTS = [
    ("2026-10-01", ["6525", "9697", "5016"], ["7004", "4902", "543A"]),
    ("2026-04-01", ["7532", "543A", "285A"], ["7205", "6952", "6674"]),
    ("2025-11-05", ["4062"], ["6594"]),
    ("2025-10-01", ["3697"], ["7762"]),
    ("2025-09-29", ["8729"], []),
    ("2025-07-04", ["6963"], ["9613"]),
    ("2025-04-01", ["6532"], ["9301"]),
    ("2024-10-01", ["4307", "7453"], ["3863", "4631"]),
    ("2024-04-01", ["6146", "6526", "3092"], ["2531", "5232", "5541"]),
    ("2023-10-02", ["9843", "6920", "4385"], ["5202", "7003", "8628"]),
    ("2023-04-03", ["4661", "6723", "9201"], ["5703", "3101", "5707"]),
    ("2022-10-04", ["5831"], ["1333"]),
    ("2022-10-03", ["7741", "6273"], ["3103", "6703"]),
    ("2022-09-29", ["6594"], ["8355"]),
    ("2022-04-04", ["8591"], ["8303"]),
    ("2022-01-05", ["9147"], ["9062"]),
    ("2021-10-01", ["6981", "6861", "7974"], ["5901", "9412", "3105"]),
    ("2020-12-02", ["6753"], ["9437"]),
    ("2020-10-29", ["3659"], ["8028"]),
    ("2020-10-01", ["9434"], ["4272"]),
    ("2020-07-29", ["8697"], ["8729"]),
    ("2019-10-01", ["2413"], ["9681"]),
    ("2019-08-01", ["7832"], ["6366"]),
    ("2019-03-27", ["5019"], ["5002"]),
]


def window_return(code: str, start: str, end: str) -> float | None:
    symbol = code if code.startswith("^") else f"{code}.T"
    try:
        df = yf.Ticker(symbol).history(start=start, end=end, interval="1d")
    except Exception:
        return None
    if df.empty or len(df) < 2:
        return None
    return float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1


def main() -> None:
    runup_added, runup_removed = [], []
    reversal_added, reversal_removed = [], []

    for eff_str, added, removed in EVENTS:
        eff = dt.date.fromisoformat(eff_str)
        runup_start = (eff - dt.timedelta(days=RUNUP_DAYS_BEFORE)).isoformat()
        runup_end = eff.isoformat()  # yfinanceのendは含まない → 実施日前日までを取得
        reversal_end = (eff + dt.timedelta(days=REVERSAL_DAYS_AFTER)).isoformat()

        mkt_runup = window_return("^N225", runup_start, runup_end)
        mkt_reversal = window_return("^N225", eff.isoformat(), reversal_end)

        for code in added:
            r = window_return(code, runup_start, runup_end)
            if r is not None and mkt_runup is not None:
                runup_added.append(r - mkt_runup)
            r2 = window_return(code, eff.isoformat(), reversal_end)
            if r2 is not None and mkt_reversal is not None:
                reversal_added.append(r2 - mkt_reversal)

        for code in removed:
            r = window_return(code, runup_start, runup_end)
            if r is not None and mkt_runup is not None:
                runup_removed.append(r - mkt_runup)
            r2 = window_return(code, eff.isoformat(), reversal_end)
            if r2 is not None and mkt_reversal is not None:
                reversal_removed.append(r2 - mkt_reversal)

    print(f"対象イベント数: {len(EVENTS)}")
    print(f"採用銘柄: 事前上昇n={len(runup_added)} / 反落n={len(reversal_added)}")
    print(f"除外銘柄: 事前上昇n={len(runup_removed)} / 反落n={len(reversal_removed)}")

    CAP = 1.0  # 超過リターンが|100%|を超えるのは異常値(データ不具合・極端な個別事情)とみなし除外

    def report(label, data):
        if not data:
            print(f"  {label}: サンプル不足")
            return
        print(f"  {label}: 平均={pystats.mean(data)*100:+.1f}%(中央値{pystats.median(data)*100:+.1f}%, "
              f"最小{min(data)*100:+.1f}%, 最大{max(data)*100:+.1f}%, n={len(data)})")
        capped = [x for x in data if abs(x) <= CAP]
        if len(capped) != len(data):
            print(f"    --- |超過リターン|>100%を除外(n={len(capped)}) --- "
                  f"平均={pystats.mean(capped)*100:+.1f}%(中央値{pystats.median(capped)*100:+.1f}%)")

    print(f"\n{'='*70}\n=== 実施日前(発表後、実施日の約{RUNUP_DAYS_BEFORE}日前〜前日)の対市場超過リターン ===\n{'='*70}")
    report("採用銘柄", runup_added)
    report("除外銘柄", runup_removed)

    print(f"\n{'='*70}\n=== 実施日後(実施日〜{REVERSAL_DAYS_AFTER}日後)の対市場超過リターン ===\n{'='*70}")
    report("採用銘柄", reversal_added)
    report("除外銘柄", reversal_removed)

    print("\n注意: n数が少ない実イベントの積み上げ(過去2019〜2026年、24イベント)。"
          "銘柄コードの対応関係は二次情報サイトから取得しており、公式PDFでの"
          "裏取りはできていない。一部の除外は完全子会社化・非公開化によるもので"
          "純粋な指数入れ替え裁量とは性質が異なる。2026-10-01イベントは進行中で"
          "反落側のデータはまだ存在しない。")


if __name__ == "__main__":
    main()
