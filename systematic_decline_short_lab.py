#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1306の「全下落日」を機械的に検出してロング/ベア両方を検証 検証ラボ
=====================================================================
※本体には組み込まない。market_event_bear_lab.py/company_event_study_lab.pyの
「有名な事件だけを手で選んだ年表」には選択バイアスがある(後から有名になった日だけ
選んでいる=事前には分からない後知恵)という指摘を受けて、選択バイアスを排除した検証。
さらに「ベアだけじゃなく両方の姿勢で検証して」を受けて、同じショック日に対して
ロング(押し目買い、既存の本体戦略と同じ発想)とベア(空売り)の両方を比較する。

方法: market_events.json等の手動キュレーションを使わず、1306の日次終値から
「1日でthreshold%以上下落した日」を機械的に全て検出する。連続する下落日は同じ
下落局面としてまとめる(cooldown営業日以内の再検出は除外)ことで、擬似的な独立イベント数を
確保する(feedback_tati_bot_multi_angle_testing.mdの『年度・日付単位で数える』原則と同じ考え方)。

エントリー: ショック当日(d0)の終値(その日の下落は既に確定しているため先読みではない、
market_event_bear_lab.pyの「同日(SAME-DAY)」と同じ考え方)。
出口: 固定20営業日保有/固定%利確/ボラ基準トレーリングストップを、ロング・ベアそれぞれで比較。

使い方: python systematic_decline_short_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats
from collections import defaultdict

import market_event_bear_lab as m

THRESHOLD = -0.025   # 1日-2.5%以下を「ショック日」とする(全期間標準偏差の約2倍)
COOLDOWN = 15         # 同じ下落局面とみなして再検出しない営業日数
COST_ROUNDTRIP = m.COST_ROUNDTRIP


def find_shock_days(closes: dict[dt.date, float], threshold: float, cooldown: int) -> list[dt.date]:
    keys = sorted(closes)
    events, last_idx = [], -10**9
    for i in range(1, len(keys)):
        r = closes[keys[i]] / closes[keys[i - 1]] - 1
        if r <= threshold and i - last_idx >= cooldown:
            events.append(keys[i])
        if r <= threshold:
            last_idx = i
    return events


def fixed_hold_exit(closes, d0, n_days, side):
    offs = m.trading_day_offset(closes, d0, n_days)
    if offs is None:
        return None
    r = offs[1] / closes[d0] - 1
    return r if side == "long" else -r


def fixed_takeprofit_exit(closes, d0, tp_pct, side, max_days=20):
    entry_price = closes[d0]
    keys = sorted(x for x in closes if x >= d0)
    last_idx = min(max_days, len(keys) - 1)
    if last_idx < 1:
        return None
    for i in range(1, last_idx + 1):
        r = closes[keys[i]] / entry_price - 1
        signed = r if side == "long" else -r
        if signed >= tp_pct:
            return signed
    r = closes[keys[last_idx]] / entry_price - 1
    return r if side == "long" else -r


def vol_trailing_stop_exit(closes, d0, k, side, max_days=20):
    """ロング: 保有中の最高値からk*sigma下落したら利確。ベア: 最安値からk*sigma上昇したら利確。"""
    sigma = m.recent_volatility(closes, d0, window=20)
    if sigma is None or sigma <= 0:
        return None
    entry_price = closes[d0]
    keys = sorted(x for x in closes if x >= d0)
    last_idx = min(max_days, len(keys) - 1)
    if last_idx < 1:
        return None
    extreme_price = entry_price  # long: 最高値 / short: 最安値
    for i in range(1, last_idx + 1):
        price = closes[keys[i]]
        if side == "long":
            extreme_price = max(extreme_price, price)
            if price <= extreme_price * (1 - k * sigma):
                return price / entry_price - 1
        else:
            extreme_price = min(extreme_price, price)
            if price >= extreme_price * (1 + k * sigma):
                return -(price / entry_price - 1)
    price = closes[keys[last_idx]]
    r = price / entry_price - 1
    return r if side == "long" else -r


def summarize(label, pnls):
    if not pnls:
        print(f"  {label}: データなし")
        return
    wins = sum(1 for p in pnls if p > 0)
    print(f"  {label}: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
          f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 中央値{pystats.median(pnls)*100:+.2f}% "
          f"/ 合計{sum(pnls)*100:+.1f}%")


def main():
    closes = m.fetch_split_safe(m.TICKER)
    shocks = find_shock_days(closes, THRESHOLD, COOLDOWN)
    print(f"1306データ範囲: {min(closes)}〜{max(closes)}")
    print(f"検出したショック日(1日{THRESHOLD*100:.1f}%以下、cooldown{COOLDOWN}営業日): {len(shocks)}件\n")

    by_year = defaultdict(int)
    for d in shocks:
        by_year[d.year] += 1
    print("年度別件数(特定の年に偏っていないかの確認):")
    print("  " + "  ".join(f"{y}:{n}" for y, n in sorted(by_year.items())))
    print()

    print("=" * 100)
    print(f"集計(コスト後、往復{COST_ROUNDTRIP*10000:.0f}bps仮定、エントリー=ショック当日終値)")
    print("=" * 100)
    for side, side_label in [("long", "ロング(押し目買い)"), ("short", "ベア(空売り)")]:
        print(f"\n--- {side_label} ---")
        fixed20 = [p - COST_ROUNDTRIP for d0 in shocks if (p := fixed_hold_exit(closes, d0, 20, side)) is not None]
        tp3 = [p - COST_ROUNDTRIP for d0 in shocks if (p := fixed_takeprofit_exit(closes, d0, 0.03, side)) is not None]
        voltrail = [p - COST_ROUNDTRIP for d0 in shocks if (p := vol_trailing_stop_exit(closes, d0, 2.0, side)) is not None]
        summarize("固定20営業日保有", fixed20)
        summarize("固定3%利確", tp3)
        summarize("ボラ基準トレーリングストップ(k=2.0)", voltrail)

    # ---- エントリー側フィルター: 下落幅の大きさで結果が変わるか(固定20日保有、両姿勢) ----
    print("\n" + "=" * 100)
    print("追加検証: ショック当日の下落幅の大きさ別(固定20営業日保有)")
    print("=" * 100)
    buckets = [(-0.025, -0.035, "-2.5%〜-3.5%"), (-0.035, -0.05, "-3.5%〜-5.0%"), (-0.05, -1.0, "-5.0%以下")]
    keys_sorted = sorted(closes)
    day_ret = {keys_sorted[i]: closes[keys_sorted[i]] / closes[keys_sorted[i - 1]] - 1
               for i in range(1, len(keys_sorted))}
    for side, side_label in [("long", "ロング"), ("short", "ベア")]:
        print(f"\n  [{side_label}]")
        for lo, hi, label in buckets:
            bucket_shocks = [d0 for d0 in shocks if hi < day_ret.get(d0, 0) <= lo]
            pnls = [p - COST_ROUNDTRIP for d0 in bucket_shocks
                    if (p := fixed_hold_exit(closes, d0, 20, side)) is not None]
            if pnls:
                wins = sum(1 for p in pnls if p > 0)
                print(f"    {label}(n={len(pnls)}): 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
                      f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 合計{sum(pnls)*100:+.1f}%")

    print("\n注意: cooldownで擬似的に独立化しているが、同じ市場サイクル・同じ金融緩和相場という")
    print("意味では完全に独立ではない。それでも『有名な事件だけ』の選択バイアスは排除できている。")
    print("コストは往復20bps仮定(1306想定)。ロング側は既存の本体戦略(RSI押し目買い)に近い発想。")


if __name__ == "__main__":
    main()
