#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「直近1年高値からのドローダウン」ベースのレジームフィルター 検証ラボ
=====================================================================
※本体には組み込まない。event_driven_regime_test_prompt.mdの手順に従う
イベント駆動戦略・深掘りルーティンの1件(2026-09-24、キュー#16)。

項目94(連続損切り)・項目95(単純な移動平均クロス)はいずれも不安定/直感と逆の結果で
不採用だった。今回は3つ目のアイデアとして「直近window営業日の高値からどれだけ下落しているか
(ドローダウン)」を判定材料にする。単純なMAクロス(レベルの上下)ではなく「どれだけ深く
沈んでいるか」を直接見る設計で、一般的な「-20%でベアマーケット」という実務的な定義とも
整合する。

★ルール(event_driven_regime_test_prompt.mdに従う)★
- 1回のセッションで新しいアイデアは1つだけ(今回はドローダウン基準のみ)
- systematic_decline_short_lab.py(1306、n=53、2009〜2026年)と
  nikkei_long_term_stoploss_lab.py(日経平均、n=169、1965〜2026年、本物の下落相場を含む)の
  両方で検証する
- 閾値を振る場合は隣接値も確認し、不安定(過学習)なら不採用と判定する
- 検知件数の年度分布・勝率・平均・中央値をセットで報告する

使い方: python drawdown_regime_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats
from collections import defaultdict, deque

import market_event_bear_lab as m
import systematic_decline_short_lab as s
import nikkei_long_term_stoploss_lab as n

COST_ROUNDTRIP = 0.002


def trailing_high(closes: dict[dt.date, float], window: int) -> dict[dt.date, float]:
    """各日について、その日を含む直近window営業日の最高値(先読みなし)。"""
    keys = sorted(closes)
    prices = [closes[k] for k in keys]
    dq: deque[tuple[int, float]] = deque()
    high = {}
    for i, p in enumerate(prices):
        while dq and dq[0][0] <= i - window:
            dq.popleft()
        while dq and dq[-1][1] <= p:
            dq.pop()
        dq.append((i, p))
        high[keys[i]] = dq[0][1]
    return high


def drawdown_regime_backtest(closes, shocks, high, dd_threshold, bear_action, max_days=20):
    """d0時点のドローダウン(高値からの下落率)がdd_threshold以上なら『下落相場』と判定し
    bear_action(skip/short)に切り替える。それ未満なら通常のロング(固定20日保有)。"""
    results = []
    for d0 in shocks:
        if d0 not in high:
            continue
        dd = 1 - closes[d0] / high[d0]
        regime = "bear" if dd >= dd_threshold else "bull"
        if regime == "bull":
            r = s.fixed_hold_exit(closes, d0, max_days, "long")
            action = "long"
        elif bear_action == "skip":
            r, action = 0.0, "skip"
        else:
            r = s.fixed_hold_exit(closes, d0, max_days, "short")
            action = "short"
        if r is None:
            continue
        results.append({"date": d0, "dd": dd, "regime": regime, "action": action,
                         "net": r - COST_ROUNDTRIP})
    return results


def run_for_sample(label, closes, shocks, dd_thresholds, window=252):
    print("=" * 100)
    print(f"サンプル: {label}(n={len(shocks)}、trailing_high窓={window}営業日)")
    print("=" * 100)
    high = trailing_high(closes, window)

    baseline = [r - COST_ROUNDTRIP for d0 in shocks if (r := s.fixed_hold_exit(closes, d0, 20, "long")) is not None]
    wins = sum(1 for p in baseline if p > 0)
    print(f"  ベースライン(常にロング、レジーム判定なし): n={len(baseline)} "
          f"勝率{wins}/{len(baseline)}({wins/len(baseline)*100:.0f}%) "
          f"平均{pystats.mean(baseline)*100:+.2f}% 中央値{pystats.median(baseline)*100:+.2f}% "
          f"合計{sum(baseline)*100:+.1f}%\n")

    for dd_th in dd_thresholds:
        for bear_action, lbl in [("skip", "見送り"), ("short", "ベア反転")]:
            results = drawdown_regime_backtest(closes, shocks, high, dd_th, bear_action)
            pnls = [r["net"] for r in results]
            bear_n = sum(1 for r in results if r["regime"] == "bear")
            if not pnls:
                continue
            wins = sum(1 for p in pnls if p > 0)
            print(f"  DD{dd_th*100:.0f}%以上 {lbl}: n={len(pnls)}(下落判定{bear_n}件) "
                  f"勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
                  f"平均{pystats.mean(pnls)*100:+.2f}% 中央値{pystats.median(pnls)*100:+.2f}% "
                  f"合計{sum(pnls)*100:+.1f}%")
        print()

    # 年度分布(1つの閾値、見送りルールで代表確認)
    mid = dd_thresholds[len(dd_thresholds) // 2]
    results = drawdown_regime_backtest(closes, shocks, high, mid, "skip")
    bear_dates = [r["date"] for r in results if r["regime"] == "bear"]
    by_year = defaultdict(int)
    for d in bear_dates:
        by_year[d.year] += 1
    print(f"  参考(DD{mid*100:.0f}%時点)下落判定{len(bear_dates)}件の年度分布:")
    print("    " + "  ".join(f"{y}:{c}" for y, c in sorted(by_year.items())))
    print()


def main():
    closes_1306 = m.fetch_split_safe(m.TICKER)
    shocks_1306 = s.find_shock_days(closes_1306, s.THRESHOLD, s.COOLDOWN)
    run_for_sample("1306(2009〜2026年)", closes_1306, shocks_1306, [0.10, 0.15, 0.20, 0.25], window=252)

    closes_n225 = n.fetch_closes(n.TICKER)
    shocks_n225 = s.find_shock_days(closes_n225, n.THRESHOLD, n.COOLDOWN)
    run_for_sample("日経平均(1965〜2026年)", closes_n225, shocks_n225, [0.10, 0.15, 0.20, 0.25], window=252)

    print("注意: n=十数〜百数十件、記述的検証(統計的検定ではない)。閾値の隣接値での安定性を")
    print("必ず確認すること(過去の連続損切り・移動平均の検証で不安定な結果になった教訓)。")


if __name__ == "__main__":
    main()
