#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
権利付き最終日イベントの日中値動き観測(1分足、無料枠での初回トライ)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。n=1イベントなので
統計的な結論は出せない、あくまで最初の観測・今後の蓄積の足がかり。

背景: 「一日に複数銘柄を回転売買できるか」という質問を受け、分足データでの
検証を試みたが、yfinanceは1分足=過去8日分・5分足以上でも過去60日分までしか
遡れず、過去の権利付き最終日を遡ってバックテストすることはできない
(SESSION_LOG項目58参照)。J-Quantsの分足アドオンは有料(年間約8.6万円)で
費用対効果が見合わないため見送り。

そこで、2026年9月の権利付き最終日(9/28・月)が近いことを利用し、無料の
yfinance 1分足で「イベント発生直後」に取得すれば8日以内の制約に収まる。
これを使って、日中いつ上昇するか(寄り付き集中か、引けにかけてか)を
記述的に確認する。**実行タイミングは9/28〜10/5頃まで(8日ルール)**。

使い方: python rights_day_intraday_lab.py
(候補銘柄は rights_selector_cache_month9.json があればそれを使う。
 なければ rights_day_selector.py --prime --month 9 --budget 500000 --n 5 を先に実行)
"""
from __future__ import annotations
import datetime as dt
import json
import os

import yfinance as yf

CACHE_PATH = "rights_selector_cache_month9.json"
FALLBACK_CANDIDATES = [  # 項目47のテスト実行結果(2026年9月分、流動性上位5件)
    {"code": "9432", "name": "NTT"},
    {"code": "9434", "name": "ソフトバンク"},
    {"code": "5401", "name": "日本製鉄"},
    {"code": "4005", "name": "住友化学"},
    {"code": "7211", "name": "三菱自動車"},
]
RIGHTS_DAY = dt.date(2026, 9, 28)  # 権利付き最終日(月)。権利落ち日は9/29(火)


def load_candidates() -> list[dict]:
    if os.path.exists(CACHE_PATH):
        candidates = json.load(open(CACHE_PATH, encoding="utf-8"))
        candidates.sort(key=lambda c: c["avg_volume"], reverse=True)
        return candidates[:5]
    print(f"{CACHE_PATH}が無いため、項目47のテスト実行結果を仮の候補として使用します。")
    return FALLBACK_CANDIDATES


def analyze_intraday(code: str, name: str) -> None:
    ticker = yf.Ticker(f"{code}.T")
    try:
        df = ticker.history(period="7d", interval="1m")
    except Exception as e:
        print(f"  {code} {name}: 取得失敗({e})")
        return
    if df is None or df.empty:
        print(f"  {code} {name}: データなし(8日の窓を過ぎている可能性)")
        return
    day_df = df[df.index.date == RIGHTS_DAY]
    if day_df.empty:
        print(f"  {code} {name}: {RIGHTS_DAY}のデータなし(休日 or 窓外)")
        return

    open_px = float(day_df["Close"].iloc[0])
    close_px = float(day_df["Close"].iloc[-1])
    day_ret = close_px / open_px - 1

    # 30分刻みでの累積リターン推移
    checkpoints = ["09:30", "10:30", "11:30", "13:00", "14:00", "15:00"]
    print(f"\n  {code} {name}: 始値近辺{open_px:.1f}円 → 終値近辺{close_px:.1f}円"
          f"(当日{day_ret*100:+.2f}%)")
    for cp in checkpoints:
        h, m = map(int, cp.split(":"))
        target = day_df.index[0].replace(hour=h, minute=m)
        sub = day_df[day_df.index <= target]
        if sub.empty:
            continue
        px = float(sub["Close"].iloc[-1])
        print(f"    {cp}時点: {px:.1f}円({(px/open_px-1)*100:+.2f}% 対始値)")


def main() -> None:
    today = dt.date.today()
    days_since = (today - RIGHTS_DAY).days
    if days_since < 0:
        print(f"まだ権利付き最終日({RIGHTS_DAY})前です。当日以降(〜10/5頃まで)に再実行してください。")
        return
    if days_since > 7:
        print(f"権利付き最終日({RIGHTS_DAY})から{days_since}日経過、"
              "yfinance 1分足の8日ルールを超えている可能性が高いです(取得できないかもしれません)。")

    candidates = load_candidates()
    print(f"対象: {RIGHTS_DAY}(権利付き最終日)、候補{len(candidates)}銘柄の1分足を確認")
    for c in candidates:
        analyze_intraday(c["code"], c["name"])

    print("\n注意: n=1イベントの記述的観測に過ぎない。日中タイミングの優位性を主張できる"
          "根拠ではなく、今後複数回分を蓄積して初めて検証可能になる性質のデータ。")


if __name__ == "__main__":
    main()
