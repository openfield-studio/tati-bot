#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MSCI Japan指数の定期見直し効果の実証検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

「特定の日の値動き」候補調査シリーズ#2。日経225定期入れ替え効果(SESSION_LOG
項目51)と同じ構造(指数連動ファンドの機械的売買による需要ショック)をMSCI Japan
(四半期ごとの定期見直し、2・5・8・11月末発効)で検証する。

★データソースと限界★
過去の入れ替え履歴を集めたサイト(msci-db.vercel.app)が2026年分の3回
(2月・5月・8月)しか収録しておらず、日経225の時のような複数年分の履歴は
入手できなかった。そのため**サンプル数が非常に少ない**(採用6銘柄・除外20銘柄)。
参考値程度の位置づけとする。

使い方: python msci_japan_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats

import yfinance as yf

RUNUP_DAYS_BEFORE = 15  # MSCIは実施日の約2週間前に構成銘柄案を公表するとされる
REVERSAL_DAYS_AFTER = 15

# (発効日, 採用銘柄コードのリスト, 除外銘柄コードのリスト)
# 出典: msci-db.vercel.app(2026-09-18取得)
EVENTS = [
    ("2026-02-27", ["1803", "4062"], ["3038", "4704", "9023", "9143"]),
    ("2026-05-29", ["4004", "5706", "5801"],
     ["2413", "6064", "3088", "3092", "3391", "3626", "4204", "4716", "6201", "6869", "7701", "8729", "9005", "9201"]),
    ("2026-08-31", ["6525"], ["5411", "9024"]),
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
        runup_end = eff.isoformat()
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
    print(f"採用銘柄: 事前n={len(runup_added)} / 事後n={len(reversal_added)}")
    print(f"除外銘柄: 事前n={len(runup_removed)} / 事後n={len(reversal_removed)}")

    def report(label, data):
        if not data:
            print(f"  {label}: サンプル不足")
            return
        print(f"  {label}: 平均={pystats.mean(data)*100:+.1f}%(中央値{pystats.median(data)*100:+.1f}%, n={len(data)})")

    print(f"\n=== 発効前(約{RUNUP_DAYS_BEFORE}日前〜前日)の対^N225超過リターン ===")
    report("採用銘柄", runup_added)
    report("除外銘柄", runup_removed)
    print(f"\n=== 発効後({REVERSAL_DAYS_AFTER}日後まで)の対^N225超過リターン ===")
    report("採用銘柄", reversal_added)
    report("除外銘柄", reversal_removed)

    print("\n注意: サンプル数が極端に少ない(2026年の3イベントのみ、採用6銘柄・除外20銘柄)。"
          "参考値程度に留め、日経225定期入れ替え効果(n=35/28)ほどの信頼度はない。")


if __name__ == "__main__":
    main()
