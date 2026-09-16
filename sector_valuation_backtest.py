#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
業種PERパーセンタイルの予測力チェック(sector_valuation_lab.pyの続き)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

sector_valuation_percentile.pyは「今のPERが過去と比べてどの位置か」を示すだけで、
「そこで買うと実際にその後儲かるか」は未検証だった。ここではJPXの業種別PER履歴
(2013-01〜)と、TOPIX-17業種別ETF(実際の株価)を組み合わせ、
「PERパーセンタイルが低い(割安)時に買うと、その後の株価は良いか」を検証する。

★対象を5業種に限定した理由★
JPXは東証33業種、TOPIX-17業種別ETFは17業種で、粒度が違う。33業種のうち
以下の5つは17業種と1対1で綺麗に対応するため、この5つだけを対象にした
(それ以外は複数のJPX業種がETF1本に合算されており、単純に比較できない):
  28 銀行業      ↔ 1631 (NEXT FUNDS 銀行)
  8  医薬品      ↔ 1621 (NEXT FUNDS 医薬品)
  20 電気・ガス業  ↔ 1627 (NEXT FUNDS 電力・ガス)
  32 不動産業    ↔ 1633 (NEXT FUNDS 不動産)
  4  食料品      ↔ 1617 (NEXT FUNDS 食品)

★先読みバイアス対策★
ある月のPERパーセンタイルは、その月「まで」のデータだけを使う拡大窓
(expanding window)で計算する(sector_valuation_percentile.pyは全期間を使って
いたが、それだと未来のデータで「今が安い」と判定してしまう先読みバイアスになる
ため、ここでは修正する)。

使い方: python sector_valuation_backtest.py
"""
from __future__ import annotations
import csv
import datetime as dt
import statistics as pystats
from collections import defaultdict

import yfinance as yf

SECTOR_ETF_MAP = {
    "28": ("1631", "銀行業"),
    "8": ("1621", "医薬品"),
    "20": ("1627", "電気・ガス業"),
    "32": ("1633", "不動産業"),
    "4": ("1617", "食料品"),
}
MIN_HISTORY_MONTHS = 24  # パーセンタイル計算に必要な最低過去月数
FORWARD_MONTHS = [6, 12]  # 何ヶ月後のリターンを見るか


def load_per_series() -> dict[str, list[tuple[str, float]]]:
    rows = list(csv.DictReader(open("jpx_sector_per_pbr_history.csv", encoding="utf-8-sig")))
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        if r["industry_key"] in SECTOR_ETF_MAP and r["per"]:
            out[r["industry_key"]].append((r["yearmonth"], float(r["per"])))
    for k in out:
        out[k].sort(key=lambda x: x[0])
    return out


def expanding_percentile(series: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """各月について、その月「まで」のデータだけを使ったパーセンタイルを返す
    (先読みなし)。最初のMIN_HISTORY_MONTHSヶ月はサンプル不足のためスキップ。"""
    out = []
    for i in range(MIN_HISTORY_MONTHS, len(series)):
        past = [v for _, v in series[:i + 1]]  # 当月を含む「これまで」のデータ
        latest = past[-1]
        pct = sum(1 for v in past if v <= latest) / len(past) * 100
        out.append((series[i][0], pct))
    return out


def fetch_monthly_prices(code: str) -> dict[str, float]:
    """ETFの月末終値を {yyyy-mm: 終値} で返す。"""
    df = yf.Ticker(f"{code}.T").history(period="max", interval="1mo")
    out = {}
    for idx, row in df.iterrows():
        out[idx.strftime("%Y-%m")] = float(row["Close"])
    return out


def forward_return(prices: dict[str, float], ym: str, months: int) -> float | None:
    y, m = map(int, ym.split("-"))
    total = y * 12 + (m - 1) + months
    ty, tm = divmod(total, 12)
    target_ym = f"{ty}-{tm + 1:02d}"
    if ym not in prices or target_ym not in prices:
        return None
    return prices[target_ym] / prices[ym] - 1


def main() -> None:
    per_series = load_per_series()
    print("=== 業種PERパーセンタイル(先読みなし・拡大窓) × その後の株価騰落率 ===\n")

    overall_low_rets = defaultdict(list)   # 月ごとの分位別リターンをまとめて集計
    overall_high_rets = defaultdict(list)

    for key, (etf_code, name) in SECTOR_ETF_MAP.items():
        series = per_series.get(key)
        if not series or len(series) < MIN_HISTORY_MONTHS + 12:
            print(f"[{name}] データ不足のためスキップ")
            continue

        pct_series = expanding_percentile(series)
        print(f"取得中: {name}(ETF {etf_code}) 価格データ...")
        prices = fetch_monthly_prices(etf_code)

        # パーセンタイルの低い(割安)側30%と高い(割高)側30%それぞれで、
        # その後6ヶ月・12ヶ月のリターン平均を比較する
        low = [(ym, p) for ym, p in pct_series if p <= 30]
        high = [(ym, p) for ym, p in pct_series if p >= 70]

        print(f"\n[{name}] 割安ゾーン(パーセンタイル<=30%){len(low)}ヶ月 / "
              f"割高ゾーン(>=70%){len(high)}ヶ月")
        for months in FORWARD_MONTHS:
            low_rets = [r for ym, _ in low if (r := forward_return(prices, ym, months)) is not None]
            high_rets = [r for ym, _ in high if (r := forward_return(prices, ym, months)) is not None]
            if low_rets:
                overall_low_rets[months] += low_rets
            if high_rets:
                overall_high_rets[months] += high_rets
            low_avg = pystats.mean(low_rets) * 100 if low_rets else None
            high_avg = pystats.mean(high_rets) * 100 if high_rets else None
            print(f"  {months}ヶ月後リターン: 割安ゾーン平均={low_avg:+.1f}%(n={len(low_rets)})"
                  if low_avg is not None else f"  {months}ヶ月後: 割安ゾーンのサンプル不足",
                  end="")
            if high_avg is not None:
                print(f" / 割高ゾーン平均={high_avg:+.1f}%(n={len(high_rets)})")
            else:
                print()

    print("\n=== 5業種まとめ(全業種のデータをプールした場合) ===")
    for months in FORWARD_MONTHS:
        lo = overall_low_rets.get(months, [])
        hi = overall_high_rets.get(months, [])
        if lo and hi:
            print(f"{months}ヶ月後: 割安ゾーン平均={pystats.mean(lo)*100:+.1f}%(n={len(lo)}) / "
                  f"割高ゾーン平均={pystats.mean(hi)*100:+.1f}%(n={len(hi)}) / "
                  f"差={((pystats.mean(lo)-pystats.mean(hi))*100):+.1f}pt")

    print("\n注意: これは5業種・限られたサンプル数での簡易チェックであり、")
    print("      多重検定補正(DSR等)や取引コストは考慮していない参考値。")


if __name__ == "__main__":
    main()
