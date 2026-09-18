#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「特定の日の値動き」候補調査シリーズ#3,6,7,8,9,10の一括検証(1306/TOPIX基準)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

10候補リストのうち、外部の個別銘柄データを必要とせず、tati-bot保有の1306
(TOPIX連動ETF)の価格履歴だけで検証できる6つをまとめて検証する:
  #3 祝日前・連休明け効果(通常の週末より長い休場ギャップ前後の値動き)
  #6 米国雇用統計(NFP)発表日効果(月初第1金曜、翌営業日の日本株反応)
  #7 サンタクロースラリー/掉尾の一振(年末最終5営業日+年始2営業日)
  #8 メジャーSQ日(3・6・9・12月第2金曜)前後の値動き
  #9 曜日効果(月曜安・金曜高)
  #10 株主総会集中日(6月最終週)の値動き

使い方: python calendar_effects_batch_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats
from collections import defaultdict

import yfinance as yf
from scipy import stats

RET_CAP = 0.3  # 1306の分割調整漏れ異常値対策(topix_ff_review_lab.pyと同じ教訓)


def load_1306():
    df = yf.Ticker("1306.T").history(period="max")
    df = df[df["Close"].notna()]
    dates = sorted(idx.date() for idx in df.index)
    closes = {idx.date(): float(row["Close"]) for idx, row in df.iterrows()}
    return dates, closes


def daily_returns(dates, closes):
    out = []
    for i in range(1, len(dates)):
        r = closes[dates[i]] / closes[dates[i - 1]] - 1
        if abs(r) <= RET_CAP:
            out.append((dates[i - 1], dates[i], r))
    return out


def report(label, data):
    if not data:
        print(f"  {label}: サンプル不足")
        return
    print(f"  {label}: 平均={pystats.mean(data)*100:+.3f}%(中央値{pystats.median(data)*100:+.3f}%, "
          f"標準偏差{pystats.pstdev(data)*100:.2f}%, n={len(data)})")


def test_day_of_week(rets):
    print(f"\n{'='*70}\n=== #9 曜日効果(月曜安・金曜高) ===\n{'='*70}")
    by_weekday = defaultdict(list)
    for d0, d1, r in rets:
        by_weekday[d1.weekday()].append(r)  # 0=月, 4=金
    names = ["月", "火", "水", "木", "金"]
    for wd in range(5):
        report(names[wd] + "曜", by_weekday[wd])
    if by_weekday[0] and by_weekday[4]:
        t, p = stats.ttest_ind(by_weekday[0], by_weekday[4], equal_var=False)
        print(f"  月曜 vs 金曜 t検定: t={t:.2f}, p={p:.3f}")


def test_holiday(dates, closes, all_rets):
    print(f"\n{'='*70}\n=== #3 祝日前・連休明け効果 ===\n{'='*70}")
    normal_gap_rets = [r for _, _, r in all_rets]
    pre_holiday, reopen = [], []
    for i in range(1, len(dates)):
        gap_days = (dates[i] - dates[i - 1]).days
        is_normal_weekend = gap_days == 3 and dates[i - 1].weekday() == 4 and dates[i].weekday() == 0
        if gap_days > 1 and not is_normal_weekend:
            # dates[i-1]が祝日前営業日、dates[i]が休場明け営業日
            r = closes[dates[i]] / closes[dates[i - 1]] - 1
            if abs(r) <= RET_CAP:
                reopen.append(r)
            j = dates.index(dates[i - 1]) if False else None  # placeholder unused
    # 休場明けの値動き(通常の1日リターンより大きいか)
    report("休場明けの値動き(祝日・連休をまたぐ営業日)", reopen)
    report("参考: 通常の1営業日リターン全体", normal_gap_rets)
    if reopen and normal_gap_rets:
        reopen_abs = [abs(r) for r in reopen]
        normal_abs = [abs(r) for r in normal_gap_rets]
        print(f"  値幅(絶対値)の比較: 休場明け平均{pystats.mean(reopen_abs)*100:.2f}% vs "
              f"通常平均{pystats.mean(normal_abs)*100:.2f}%(倍率{pystats.mean(reopen_abs)/pystats.mean(normal_abs):.2f}倍)")
        t, p = stats.ttest_ind(reopen_abs, normal_abs, equal_var=False)
        print(f"  値幅の差のt検定: t={t:.2f}, p={p:.3f}")
        t2, p2 = stats.ttest_ind(reopen, normal_gap_rets, equal_var=False)
        print(f"  方向性(生のリターン)の差のt検定: t={t2:.2f}, p={p2:.3f}")


def test_santa_rally(dates, closes):
    print(f"\n{'='*70}\n=== #7 サンタクロースラリー/掉尾の一振(年末5営業日+年始2営業日) ===\n{'='*70}")
    years = sorted(set(d.year for d in dates))
    window_rets = []
    for y in years:
        dec_days = sorted(d for d in dates if d.year == y and d.month == 12)
        jan_days = sorted(d for d in dates if d.year == y + 1 and d.month == 1)
        if len(dec_days) < 5 or len(jan_days) < 2:
            continue
        start = dec_days[-5]
        end = jan_days[1]
        r = closes[end] / closes[start] - 1
        if abs(r) <= RET_CAP:
            window_rets.append(r)
    report("年末年始ウィンドウ(7営業日)", window_rets)
    if window_rets:
        wins = sum(1 for r in window_rets if r > 0)
        print(f"  勝率: {wins}/{len(window_rets)}回")
        t, p = stats.ttest_1samp(window_rets, 0)
        print(f"  0との比較(一標本t検定): t={t:.2f}, p={p:.3f}")


def test_major_sq(dates, closes):
    print(f"\n{'='*70}\n=== #8 メジャーSQ日(3・6・9・12月第2金曜)前後の値動き ===\n{'='*70}")
    date_set = set(dates)
    years = sorted(set(d.year for d in dates))
    pre_rets, post_rets = [], []
    for y in years:
        for month in (3, 6, 9, 12):
            fridays = sorted(d for d in dates if d.year == y and d.month == month and d.weekday() == 4)
            if len(fridays) < 2:
                continue
            sq_day = fridays[1]  # 第2金曜
            i = dates.index(sq_day)
            if i - 5 < 0 or i + 5 >= len(dates):
                continue
            pre = closes[dates[i]] / closes[dates[i - 5]] - 1
            post = closes[dates[i + 5]] / closes[dates[i]] - 1
            if abs(pre) <= RET_CAP:
                pre_rets.append(pre)
            if abs(post) <= RET_CAP:
                post_rets.append(post)
    report("SQ日までの5営業日", pre_rets)
    report("SQ日からの5営業日", post_rets)
    if pre_rets:
        t, p = stats.ttest_1samp(pre_rets, 0)
        print(f"  SQ日までの5営業日、0との比較: t={t:.2f}, p={p:.3f}")
    if post_rets:
        t, p = stats.ttest_1samp(post_rets, 0)
        print(f"  SQ日からの5営業日、0との比較: t={t:.2f}, p={p:.3f}")


def test_nfp(dates, closes):
    print(f"\n{'='*70}\n=== #6 米国雇用統計(NFP、月初第1金曜)翌営業日の日本株反応 ===\n{'='*70}")
    date_idx = {d: i for i, d in enumerate(dates)}
    years = sorted(set(d.year for d in dates))
    next_day_rets = []
    for y in years:
        for month in range(1, 13):
            fridays = sorted(d for d in dates if d.year == y and d.month == month and d.weekday() == 4)
            month_days = sorted(d for d in dates if d.year == y and d.month == month)
            if not month_days:
                continue
            # 月初第1金曜(米国基準、日本の休場日はズレるので月初7日以内の金曜で近似)
            candidates_fri = [d for d in fridays if d.day <= 7]
            if not candidates_fri:
                continue
            nfp_day = candidates_fri[0]
            i = date_idx.get(nfp_day)
            if i is None or i + 1 >= len(dates):
                continue
            r = closes[dates[i + 1]] / closes[dates[i]] - 1
            if abs(r) <= RET_CAP:
                next_day_rets.append(r)
    report("NFP日の翌営業日(月曜)リターン", next_day_rets)
    if next_day_rets:
        t, p = stats.ttest_1samp(next_day_rets, 0)
        print(f"  0との比較: t={t:.2f}, p={p:.3f}")


def test_earnings_season(dates, closes, all_rets):
    print(f"\n{'='*70}\n=== #4 決算発表ピーク日周辺のボラティリティ(5月中旬・11月中旬) ===\n{'='*70}")
    peak_rets, other_rets = [], []
    for d0, d1, r in all_rets:
        is_peak = (d1.month == 5 and 8 <= d1.day <= 16) or (d1.month == 11 and 8 <= d1.day <= 16)
        (peak_rets if is_peak else other_rets).append(r)
    peak_abs = [abs(r) for r in peak_rets]
    other_abs = [abs(r) for r in other_rets]
    print(f"  決算ピーク期間(5/8-16, 11/8-16)の1日値幅平均: {pystats.mean(peak_abs)*100:.2f}%(n={len(peak_abs)})")
    print(f"  それ以外の期間の1日値幅平均: {pystats.mean(other_abs)*100:.2f}%(n={len(other_abs)})")
    t, p = stats.ttest_ind(peak_abs, other_abs, equal_var=False)
    print(f"  t検定: t={t:.2f}, p={p:.3f}")


def test_agm_week(dates, closes):
    print(f"\n{'='*70}\n=== #10 株主総会集中日(6月最終週)の値動き ===\n{'='*70}")
    years = sorted(set(d.year for d in dates))
    window_rets = []
    for y in years:
        june_days = sorted(d for d in dates if d.year == y and d.month == 6)
        if len(june_days) < 5:
            continue
        start, end = june_days[-5], june_days[-1]
        i0, i1 = dates.index(start), dates.index(end)
        r = closes[dates[i1]] / closes[dates[i0]] - 1
        if abs(r) <= RET_CAP:
            window_rets.append(r)
    report("6月最終週(5営業日)", window_rets)
    if window_rets:
        wins = sum(1 for r in window_rets if r > 0)
        print(f"  勝率: {wins}/{len(window_rets)}回")
        t, p = stats.ttest_1samp(window_rets, 0)
        print(f"  0との比較: t={t:.2f}, p={p:.3f}")


def main():
    dates, closes = load_1306()
    all_rets = daily_returns(dates, closes)
    print(f"データ範囲: {dates[0]} 〜 {dates[-1]}({len(dates)}日)")

    test_day_of_week(all_rets)
    test_holiday(dates, closes, all_rets)
    test_santa_rally(dates, closes)
    test_major_sq(dates, closes)
    test_nfp(dates, closes)
    test_earnings_season(dates, closes, all_rets)
    test_agm_week(dates, closes)

    print("\n注意: 全て1306(TOPIX連動ETF)単体での指数レベル検証。個別銘柄への"
          "波及効果は別途未検証。10営業日超の窓では過去に判明した分割調整漏れの"
          "異常値混入に注意し|日次リターン|>30%を除外(topix_ff_review_lab.pyと同じ)。")


if __name__ == "__main__":
    main()
