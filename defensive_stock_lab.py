#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下げ相場に強い銘柄の選定方法チェック(ベータによる防御力の検証)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

「下げ相場になった時に個別に上がる/下がりにくい銘柄を選ぶ方法はあるか」を受け、
市場感応度(β)が低い/マイナスの銘柄は、下げ相場でも下がりにくい(または上がる)
という仮説を検証する。

★先読みバイアス対策★
βは「下落局面が始まる前」の期間だけで計算する(下落局面のデータを含めて計算すると、
それはただの結果論になってしまうため)。

対象の下落局面(日経225、直近の主な急落):
  2024年8月急落: 2024-08-05〜2024-08-09(-25.5%、俗にいう「令和のブラックマンデー」)
  2025年4月急落: 2025-03-31〜2025-04-28(-26.3%、底2025-04-07)

各局面について、その直前2年間の月次リターンから日経225銘柄のβを計算し、
実際の下落局面での騰落率との相関を見る。

使い方: python defensive_stock_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats

import yfinance as yf

from value_screener import NIKKEI225

CRASHES = [
    # peak/troughは日経225の実際の直近高値日・底値日を事前に特定した正確な日付
    # (単純な閾値通過日だと高値を過小評価するため、実測して補正済み)
    {"name": "2024年8月急落", "peak": "2024-07-11", "trough": "2024-08-05",
     "beta_window_end": "2024-07-11"},
    {"name": "2025年4月急落(2024年末からの続落)", "peak": "2024-12-27", "trough": "2025-04-07",
     "beta_window_end": "2024-12-27"},
]
BETA_WINDOW_YEARS = 2


def monthly_returns(closes: dict[str, float]) -> list[float]:
    keys = sorted(closes.keys())
    return [closes[keys[i]] / closes[keys[i - 1]] - 1 for i in range(1, len(keys))]


def fetch_monthly_close_map(code: str, start: str, end: str) -> dict[str, float]:
    df = yf.Ticker(f"{code}.T" if code != "^N225" else code).history(
        start=start, end=end, interval="1mo")
    return {idx.strftime("%Y-%m"): float(row["Close"]) for idx, row in df.iterrows()}


def beta_vs_market(stock_rets: list[float], mkt_rets: list[float]) -> float | None:
    n = min(len(stock_rets), len(mkt_rets))
    if n < 12:
        return None
    s, m = stock_rets[-n:], mkt_rets[-n:]
    mean_s, mean_m = pystats.mean(s), pystats.mean(m)
    cov = sum((s[i] - mean_s) * (m[i] - mean_m) for i in range(n)) / n
    var_m = sum((x - mean_m) ** 2 for x in m) / n
    return cov / var_m if var_m > 0 else None


def crash_return(code: str, peak: str, trough: str) -> float | None:
    ticker = f"{code}.T" if code != "^N225" else code
    end = (dt.date.fromisoformat(trough) + dt.timedelta(days=3)).isoformat()
    df = yf.Ticker(ticker).history(start=peak, end=end, interval="1d")
    if df.empty or len(df) < 2:
        return None
    trough_date = dt.date.fromisoformat(trough)
    df_up_to_trough = df[df.index.date <= trough_date]
    if df_up_to_trough.empty:
        return None
    return float(df_up_to_trough["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1


def main() -> None:
    for crash in CRASHES:
        print(f"\n=== {crash['name']}({crash['peak']}〜{crash['trough']}) ===")
        beta_end = dt.date.fromisoformat(crash["beta_window_end"])
        beta_start = (beta_end.replace(year=beta_end.year - BETA_WINDOW_YEARS)).isoformat()

        mkt_closes = fetch_monthly_close_map("^N225", beta_start, crash["beta_window_end"])
        mkt_rets = monthly_returns(mkt_closes)
        mkt_crash_ret = crash_return("^N225", crash["peak"], crash["trough"])
        print(f"日経225自体の下落率: {mkt_crash_ret*100:+.1f}%")

        results = []
        for i, (code, name) in enumerate(NIKKEI225, 1):
            try:
                closes = fetch_monthly_close_map(code, beta_start, crash["beta_window_end"])
                rets = monthly_returns(closes)
                beta = beta_vs_market(rets, mkt_rets)
                creturn = crash_return(code, crash["peak"], crash["trough"])
                if beta is not None and creturn is not None:
                    results.append({"code": code, "name": name, "beta": beta, "crash_return": creturn})
            except Exception:
                pass
            if i % 50 == 0:
                print(f"  {i}/{len(NIKKEI225)}件処理済み...")

        if len(results) < 20:
            print("  データ不足")
            continue

        results.sort(key=lambda r: r["beta"])
        n = len(results)
        tercile = n // 3
        low_beta = results[:tercile]
        high_beta = results[-tercile:]

        low_avg = pystats.mean([r["crash_return"] for r in low_beta])
        high_avg = pystats.mean([r["crash_return"] for r in high_beta])
        print(f"\n低β群(下位1/3、n={len(low_beta)})の下落局面リターン平均: {low_avg*100:+.1f}%")
        print(f"高β群(上位1/3、n={len(high_beta)})の下落局面リターン平均: {high_avg*100:+.1f}%")
        print(f"差: {(low_avg-high_avg)*100:+.1f}pt(プラスなら低βの方が下げに強かった)")

        # 相関係数
        betas = [r["beta"] for r in results]
        crets = [r["crash_return"] for r in results]
        mean_b, mean_c = pystats.mean(betas), pystats.mean(crets)
        cov = sum((betas[i]-mean_b)*(crets[i]-mean_c) for i in range(n)) / n
        std_b, std_c = pystats.pstdev(betas), pystats.pstdev(crets)
        corr = cov / (std_b*std_c) if std_b>0 and std_c>0 else None
        print(f"β と 下落局面リターンの相関係数: {corr:+.2f}" if corr is not None else "")

        print(f"\n--- 低β群 TOP10(最も下げに強かった予備軍) ---")
        for r in low_beta[:10]:
            print(f"  {r['code']} {r['name']:12s} β={r['beta']:+.2f}  下落局面{r['crash_return']*100:+.1f}%")


if __name__ == "__main__":
    main()
