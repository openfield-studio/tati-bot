#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日経平均(1965〜)の長期データで「本物の回復しない下落」を含めて損切りを再検証 検証ラボ
=====================================================================
※本体には組み込まない。systematic_decline_short_lab.pyの項目92で判明した限界
(1306はyfinanceで2009年以降しか取れず、2009〜2026年は結局右肩上がりの相場のため
『回復しない本物の下落』が1件もサンプルに含まれていなかった)を受けた再検証。

日経平均指数(^N225)はyfinanceで1965年から取得できる(1306と違い個別ETFの分割調整も
不要、指数そのもの)。バブル崩壊後の「失われた10年」(1990年代)、ITバブル崩壊
(2000〜2003年)、リーマンショック(2008〜2009年)等、本物の長期下落局面を含めて
ロングの損切りルールを再検証する。

★注意★ ^N225はTOPIX(1306が追跡する指数)とは別物(日経平均は225銘柄の価格平均型、
TOPIXは東証全体の時価総額加重型)だが、日本株市場全体の長期的な値動きパターンを見る
目的では妥当な代替。1306自体の長期データが取れない制約への対処。

使い方: python nikkei_long_term_stoploss_lab.py
"""
from __future__ import annotations
import datetime as dt
import statistics as pystats
from collections import defaultdict

import yfinance as yf

import systematic_decline_short_lab as s

TICKER = "^N225"
THRESHOLD = -0.025
COOLDOWN = 15
COST_ROUNDTRIP = 0.002


def fetch_closes(ticker: str) -> dict[dt.date, float]:
    df = yf.Ticker(ticker).history(period="max", auto_adjust=True).dropna(subset=["Close"])
    return {idx.date(): float(c) for idx, c in zip(df.index, df["Close"])}


def regime_backtest(closes, shocks, sl_pct, n_consecutive, bear_action, max_days=20):
    """shocksを時系列順に処理。通常は毎回ロング(損切りsl_pct%)。直近n_consecutive回
    連続でロングが損切りに引っかかったら『下落局面』と判定してbear_actionに切り替える
    (bear_action: 'skip'=見送り(現金)、'short'=ベアに反転、損切りも対称に適用)。
    ロングなら損切りに引っかからないトレードが出たら即、通常モードに復帰する。
    ★レジーム判定は常に『もしロングしていたら』の結果で行う(実際の行動とは独立)。"""
    consecutive_losses = 0
    regime = "normal"
    results = []
    for d0 in shocks:
        long_r = s.stoploss_exit_side(closes, d0, sl_pct, "long", max_days=max_days)
        if long_r is None:
            continue
        would_stop = long_r <= -sl_pct + 1e-9

        if regime == "normal":
            actual_r, action = long_r, "long"
        elif bear_action == "skip":
            actual_r, action = 0.0, "skip"
        else:
            short_r = s.stoploss_exit_side(closes, d0, sl_pct, "short", max_days=max_days)
            actual_r, action = (short_r if short_r is not None else 0.0), "short"

        results.append({"date": d0, "regime_at_entry": regime, "action": action,
                         "net": actual_r - COST_ROUNDTRIP})

        consecutive_losses = consecutive_losses + 1 if would_stop else 0
        regime = "bear" if consecutive_losses >= n_consecutive else "normal"
    return results


def moving_average(closes: dict[dt.date, float], window: int) -> dict[dt.date, float]:
    """各日について、その日を含む直近window営業日の単純移動平均(先読みなし、過去と当日のみ使用)。"""
    keys = sorted(closes)
    prices = [closes[k] for k in keys]
    ma = {}
    running_sum = sum(prices[:window])
    if window <= len(prices):
        ma[keys[window - 1]] = running_sum / window
    for i in range(window, len(prices)):
        running_sum += prices[i] - prices[i - window]
        ma[keys[i]] = running_sum / window
    return ma


def ma_regime_backtest(closes, shocks, ma, bear_action, max_days=20):
    """d0時点の終値がMAより上なら『上昇トレンド』でロング、MAより下なら『下降トレンド』と判定し
    bear_action(skip=見送り/short=ベア反転)に切り替える。"""
    results = []
    for d0 in shocks:
        if d0 not in ma:
            continue
        regime = "bull" if closes[d0] > ma[d0] else "bear"
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
        results.append({"date": d0, "regime": regime, "action": action, "net": r - COST_ROUNDTRIP})
    return results


def main():
    closes = fetch_closes(TICKER)
    shocks = s.find_shock_days(closes, THRESHOLD, COOLDOWN)
    print(f"日経平均データ範囲: {min(closes)}〜{max(closes)}")
    print(f"検出したショック日(1日{THRESHOLD*100:.1f}%以下、cooldown{COOLDOWN}営業日): {len(shocks)}件\n")

    by_year = defaultdict(int)
    for d in shocks:
        by_year[d.year] += 1
    print("年度別件数:")
    print("  " + "  ".join(f"{y}:{n}" for y, n in sorted(by_year.items())))
    print()

    # ---- 保有中の最悪ドローダウン分布(長期下落局面を含めて) ----
    worst_list = []
    for d0 in shocks:
        path = s.path_profile_side(closes, d0, "long", max_days=20)
        if len(path) < 20:
            continue
        worst = min(r for _, r in path)
        final = path[-1][1]
        worst_list.append((d0, worst, final))
    worst_list.sort(key=lambda x: x[1])

    print("=" * 100)
    print("保有中の最悪ドローダウン(深い順、上位15件)")
    print("=" * 100)
    for d0, worst, final in worst_list[:15]:
        print(f"  {d0}  最悪{worst*100:+.2f}%  →20日目{final*100:+.2f}%")

    print("\n最悪ドローダウンの分布:")
    for th in [-0.05, -0.08, -0.10, -0.15, -0.20, -0.25, -0.30]:
        n = sum(1 for _, w, _ in worst_list if w <= th)
        print(f"  {th*100:.0f}%以下まで落ちた: {n}件")

    # ---- 損切り閾値の掃引(長期データで再検証) ----
    print("\n" + "=" * 100)
    print(f"損切り閾値の掃引(固定20営業日、n={len(shocks)}、1965年以降を含む)")
    print("=" * 100)
    for sl in [None, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25]:
        pnls, triggered = [], 0
        for d0 in shocks:
            r = s.stoploss_exit_side(closes, d0, sl, "long")
            if r is None:
                continue
            pnls.append(r - COST_ROUNDTRIP)
            if sl is not None and r <= -sl + 1e-9:
                triggered += 1
        if not pnls:
            continue
        wins = sum(1 for p in pnls if p > 0)
        lbl = "なし" if sl is None else f"{sl*100:.0f}%"
        print(f"  損切り{lbl}: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
              f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 最悪{min(pnls)*100:+.2f}% "
              f"/ 合計{sum(pnls)*100:+.1f}% / 発動{triggered}件")

    # ---- バブル崩壊〜失われた10年(1990年代)だけを抜き出す ----
    print("\n" + "=" * 100)
    print("参考: 1990〜1995年(バブル崩壊直後)だけの結果")
    print("=" * 100)
    bubble_shocks = [d0 for d0 in shocks if 1990 <= d0.year <= 1995]
    print(f"該当イベント: {len(bubble_shocks)}件 " + ", ".join(str(d) for d in bubble_shocks))
    for sl in [None, 0.10, 0.15, 0.20]:
        pnls = []
        for d0 in bubble_shocks:
            r = s.stoploss_exit_side(closes, d0, sl, "long")
            if r is not None:
                pnls.append(r - COST_ROUNDTRIP)
        if not pnls:
            continue
        wins = sum(1 for p in pnls if p > 0)
        lbl = "なし" if sl is None else f"{sl*100:.0f}%"
        print(f"  損切り{lbl}: n={len(pnls)} / 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
              f"/ 平均{pystats.mean(pnls)*100:+.2f}% / 合計{sum(pnls)*100:+.1f}%")

    print("\n" + "=" * 100)
    print("追加検証: 連続損切りをレジーム判定の信号として使う(『下落局面』検知→買わない/ベアに反転)")
    print("=" * 100)
    print(f"ベースライン(常にロング、損切りなし): 合計{sum(r-COST_ROUNDTRIP for d0 in shocks if (r:=s.stoploss_exit_side(closes,d0,None,'long')) is not None)*100:+.1f}%\n")
    for sl_pct in [0.10, 0.15]:
        for n_consec in [2, 3]:
            for bear_action, action_label in [("skip", "見送り(現金)"), ("short", "ベアに反転")]:
                results = regime_backtest(closes, shocks, sl_pct, n_consec, bear_action)
                pnls = [r["net"] for r in results]
                bear_periods = sum(1 for r in results if r["regime_at_entry"] == "bear")
                wins = sum(1 for p in pnls if p > 0)
                print(f"  損切り{sl_pct*100:.0f}%・{n_consec}連続で判定・下落局面時は{action_label}: "
                      f"n={len(pnls)} 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
                      f"平均{pystats.mean(pnls)*100:+.2f}% 合計{sum(pnls)*100:+.1f}% "
                      f"(下落局面と判定された回数{bear_periods}件)")

    print("\n" + "=" * 100)
    print("追加検証: 移動平均線レジームフィルター(価格>MAなら押し目買い、価格<MAなら見送り/ベア)")
    print("=" * 100)
    for window in [100, 150, 200, 250, 300]:
        ma = moving_average(closes, window)
        for bear_action, lbl in [("skip", "見送り"), ("short", "ベア反転")]:
            results = ma_regime_backtest(closes, shocks, ma, bear_action)
            pnls = [r["net"] for r in results]
            bull_n = sum(1 for r in results if r["regime"] == "bull")
            wins = sum(1 for p in pnls if p > 0)
            print(f"  MA{window}日 {lbl}: n={len(pnls)}(上昇トレンド判定{bull_n}件) "
                  f"勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
                  f"平均{pystats.mean(pnls)*100:+.2f}% 合計{sum(pnls)*100:+.1f}%")
        print()

    print("参考: MA200日のフィルターで、上昇トレンド判定分だけ/下降トレンド判定分だけの内訳")
    ma200 = moving_average(closes, 200)
    bull_pnls, bear_pnls = [], []
    for d0 in shocks:
        if d0 not in ma200:
            continue
        r = s.fixed_hold_exit(closes, d0, 20, "long")
        if r is None:
            continue
        (bull_pnls if closes[d0] > ma200[d0] else bear_pnls).append(r - COST_ROUNDTRIP)
    for lbl, pnls in [("上昇トレンド時に買った場合", bull_pnls), ("下降トレンド時に買った場合", bear_pnls)]:
        if pnls:
            wins = sum(1 for p in pnls if p > 0)
            print(f"  {lbl}: n={len(pnls)} 勝率{wins}/{len(pnls)}({wins/len(pnls)*100:.0f}%) "
                  f"平均{pystats.mean(pnls)*100:+.2f}% 合計{sum(pnls)*100:+.1f}%")

    print("\n注意: ^N225はTOPIX(1306)とは別指数。日本株市場全体の長期傾向を見る代替として使用。")
    print("コストは往復20bps仮定。1965〜2026年の61年間、実際の市場サイクル数は限られる点に注意。")


if __name__ == "__main__":
    main()
