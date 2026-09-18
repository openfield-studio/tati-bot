#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPOロックアップ解除効果(上場90日後の株価下落アノマリー)の実証検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

日経225定期入れ替え効果に続く「特定の日に値動きが起きる」候補
(2026-09-18、ユーザー依頼)。創業者・VC等の売却制限(ロックアップ)は上場から
90日または180日で解除されるのが日本株では標準的で、解除に伴う売り圧力で
株価が下落するアノマリーとして一般に認識されている(エニーカラー5032の実例等)。

★このファクターの特殊な性質★
権利付き最終日/日経225定期入れ替え効果とは逆に、**下落方向**のアノマリーである
ため、現物ロング戦略のtati-botでは直接の買いシグナルにはならない
(「IPO直後の銘柄はロックアップ解除まで持たない/避ける」という回避シグナルとしてのみ
使える)。

★データソースと限界★
2025年のIPO銘柄一覧(kabukiso.com、2026-09-18取得)から33銘柄の上場日を収集。
ロックアップ期間は90日と180日の両方があり、さらに「公開価格の1.5倍以上で
取引されている場合は解除条件が緩和される」条項が付くことも多く、正確な解除日は
銘柄ごとに異なりうる。本検証では最も一般的な**90日後**を一律の近似値として使う。

使い方: python ipo_lockup_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats

import yfinance as yf

LOCKUP_DAYS = 90
WINDOW = 10  # 営業日
RET_CAP = 1.0

# (証券コード, 銘柄名, 上場日) — 出典: kabukiso.com「2025年のIPO銘柄一覧」(2026-09-18取得)
IPOS = [
    ("7790", "バルコス", "2025-02-03"),
    ("319A", "技術承継機構", "2025-02-05"),
    ("323A", "フライヤー", "2025-02-20"),
    ("324A", "ブッキングリゾート", "2025-02-21"),
    ("325A", "TENTIAL", "2025-02-28"),
    ("330A", "TalentX", "2025-03-18"),
    ("5016", "JX金属", "2025-03-19"),
    ("331A", "メディックス", "2025-03-19"),
    ("332A", "ミーク", "2025-03-21"),
    ("9388", "パパネッツ", "2025-03-21"),
    ("335A", "ミライロ", "2025-03-24"),
    ("334A", "ビジュアル・プロセッシング・ジャパン", "2025-03-25"),
    ("338A", "ZenmuTech", "2025-03-27"),
    ("336A", "ダイナミックマッププラットフォーム", "2025-03-27"),
    ("339A", "プログレス・テクノロジーズグループ", "2025-03-28"),
    ("341A", "トヨコー", "2025-03-28"),
    ("340A", "ジグザグ", "2025-03-31"),
    ("343A", "IACEトラベル", "2025-04-07"),
    ("350A", "デジタルグリッド", "2025-04-22"),
    ("352A", "LIFE CREATE", "2025-04-24"),
    ("353A", "エレベーターコミュニケーションズ", "2025-04-25"),
    ("365A", "伊澤タオル", "2025-06-20"),
    ("366A", "ウェルネス・コミュニケーションズ", "2025-06-23"),
    ("367A", "プリモグローバルHD", "2025-06-24"),
    ("368A", "北里コーポレーション", "2025-06-25"),
    ("369A", "エータイ", "2025-06-26"),
    ("372A", "レント", "2025-06-30"),
    ("373A", "リップス", "2025-06-30"),
    ("378A", "ヒット", "2025-07-04"),
    ("386A", "みのや", "2025-07-18"),
    ("387A", "フラー", "2025-07-24"),
    ("391A", "山忠", "2025-07-29"),
    ("402A", "アクセルスペースHD", "2025-08-13"),
]


def window_return(symbol: str, start: str, end: str) -> float | None:
    try:
        df = yf.Ticker(symbol).history(start=start, end=end, interval="1d")
    except Exception:
        return None
    if df.empty or len(df) < 2:
        return None
    return float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1


def main() -> None:
    pre_rets, post_rets = [], []
    for code, name, listing_str in IPOS:
        listing = dt.date.fromisoformat(listing_str)
        lockup = listing + dt.timedelta(days=LOCKUP_DAYS)
        pre_start = (lockup - dt.timedelta(days=int(WINDOW * 1.5))).isoformat()
        pre_end = lockup.isoformat()
        post_end = (lockup + dt.timedelta(days=int(WINDOW * 1.5))).isoformat()

        mkt_pre = window_return("^N225", pre_start, pre_end)
        mkt_post = window_return("^N225", lockup.isoformat(), post_end)
        stock_pre = window_return(f"{code}.T", pre_start, pre_end)
        stock_post = window_return(f"{code}.T", lockup.isoformat(), post_end)

        if stock_pre is not None and mkt_pre is not None:
            pre_rets.append(stock_pre - mkt_pre)
        if stock_post is not None and mkt_post is not None:
            post_rets.append(stock_post - mkt_post)

    print(f"対象IPO数: {len(IPOS)}")
    print(f"ロックアップ解除前(近似90日後): n={len(pre_rets)}")
    print(f"ロックアップ解除後: n={len(post_rets)}")

    def report(label, data):
        if not data:
            print(f"  {label}: サンプル不足")
            return
        capped = [r for r in data if abs(r) <= RET_CAP]
        print(f"  {label}: 平均={pystats.mean(capped)*100:+.1f}%(中央値{pystats.median(capped)*100:+.1f}%, "
              f"最小{min(capped)*100:+.1f}%, 最大{max(capped)*100:+.1f}%, n={len(capped)})")

    print(f"\n{'='*70}\n=== ロックアップ解除(上場{LOCKUP_DAYS}日後)前後の対市場超過リターン ===\n{'='*70}")
    report("解除前(約15日前〜解除日)", pre_rets)
    report("解除後(解除日〜約15日後)", post_rets)

    print(f"\n注意: 2025年IPO{len(IPOS)}銘柄(kabukiso.comより収集)、ロックアップ期間は"
          "一律90日と仮定した近似(実際は90日/180日/1.5倍条項ありで銘柄ごとに異なりうる)。"
          "解除方向は「下落」なので現物ロング戦略では回避シグナルとしてのみ使える。")


if __name__ == "__main__":
    main()
