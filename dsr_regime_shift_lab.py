#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regime_shift_agent.py(1321/1571デッドクロス戦略)一族のDeflated Sharpe Ratio(DSR)棚卸し
=====================================================================================
※本体には組み込まない。project_wide_dsr_lab.py(1306/RSI逆張り一族)と同じ発想を、
regime_shift(1321/1571)の探索過程に適用する。ユーザーの「1321側のDSRも計算してみて」
(2026-09-28)を受けて新規作成。

この戦略が確定するまでに実際に試した(そして大半は不採用になった)アイデア・パラメータを
可能な限り再現し、その全体を「試行プール」としてσ_SR(試行Sharpeの散らばり)を計算、
最終的に採用した設定(デッドクロス120日/350日、ショック-2.5%、cooldown15、
ロング損切り30%、ベア利確5%/損切り18%)がこの試行数を踏まえてもなお「運では
説明しにくい」と言えるかを評価する。

対象とする試行(SESSION_LOG項目94・95・98・99・114):
  (a) 連続損切りレジーム(項目94、nikkei_long_term_stoploss_lab.regime_backtest):
      sl_pct∈{10%,15%} × n_consecutive∈{2,3} × bear_action∈{skip,short} = 8試行
  (b) 単純MAレジーム(項目95、nikkei_long_term_stoploss_lab.ma_regime_backtest):
      window∈{100,150,200,250,300} × bear_action∈{skip,short} = 10試行
  (c) ドローダウン基準レジーム(項目98・99、drawdown_regime_lab.py そのまま再利用):
      dd_threshold∈{10%,15%,20%,25%} × bear_action∈{skip,short} × 対象{1306,日経平均} = 16試行
  (d) デッドクロス基準レジーム(項目114、今回新規実装。1306向けdead_cross_1306_lab.pyと
      同じグリッドを日経平均(1321の長期代理)に適用):
      fast∈{90,120,150} × slow∈{280,350,400} = 9試行

合計 N=43試行。(a)(b)はSESSION_LOG本文の記述からグリッドを再構成したもので、
当時の実際の一回きりの試行(inlineで実行・ファイル未保存)を完全に再現したものではない
近似である点に注意(ルール9: 断定しない)。(c)(d)は実際のコード・パラメータをそのまま
再利用した厳密な再現。

各試行は「ショック検知→固定ルールで手仕舞い」という共通構造のイベント駆動トレードなので、
1306/RSI一族(日次リターンのSharpe)とは基準が異なる。ここでは自己整合的に
「トレード単位のSharpe(平均÷標準偏差、トレード数を観測数T)」で統一し、この
プール内だけで比較する(1306一族のσ_SRとは混在させない)。

使い方: python dsr_regime_shift_lab.py
"""
from __future__ import annotations
import math
import statistics as pystats

import market_event_bear_lab as m
import systematic_decline_short_lab as s
import nikkei_long_term_stoploss_lab as n
import drawdown_regime_lab as d

NORM = pystats.NormalDist()
EULER_GAMMA = 0.5772156649
COST_ROUNDTRIP = 0.002


def trade_sharpe(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.0
    mean = pystats.mean(rets)
    std = pystats.stdev(rets)
    return mean / std if std > 0 else 0.0


def skew_kurt(rets: list[float]) -> tuple[float, float]:
    n_ = len(rets)
    mean = sum(rets) / n_
    var = sum((r - mean) ** 2 for r in rets) / n_
    std = var ** 0.5
    if std == 0:
        return 0.0, 3.0
    skew = (sum((r - mean) ** 3 for r in rets) / n_) / std ** 3
    kurt = (sum((r - mean) ** 4 for r in rets) / n_) / std ** 4
    return skew, kurt


def expected_max_sharpe(sigma_sr: float, n_trials: float) -> float:
    if n_trials <= 1:
        return 0.0
    z1 = NORM.inv_cdf(1 - 1 / n_trials)
    z2 = NORM.inv_cdf(1 - 1 / (n_trials * math.e))
    return sigma_sr * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(sr_hat: float, t: int, skew: float, kurt: float, sr0: float) -> float:
    denom = math.sqrt(max(1e-9, 1 - skew * sr_hat + ((kurt - 1) / 4) * sr_hat ** 2))
    z = (sr_hat - sr0) * math.sqrt(t - 1) / denom
    return NORM.cdf(z)


def verdict_label(dsr: float) -> str:
    if dsr > 0.95:
        return "skillの可能性が高い"
    if dsr < 0.5:
        return "ノイズと区別できない"
    return "判断つかない領域"


def moving_average_dict(closes, window):
    return n.moving_average(closes, window)


def dead_cross_regime_backtest(closes, shocks, ma_fast, ma_slow,
                                long_stop=0.30, bear_tp=0.05, bear_sl=0.18, max_days=20):
    """regime_shift_agent.pyと同じロジック: デッドクロス(fast<slow)なら下落相場と判定。
    通常相場→ロング(損切りlong_stop、利確なし)。下落相場→ベア反転
    (利確bear_tp/損切りbear_sl、m.takeprofit_stoploss_exitのshort規約を利用)。"""
    results = []
    for d0 in shocks:
        if d0 not in ma_fast or d0 not in ma_slow:
            continue
        regime = "bear" if ma_fast[d0] < ma_slow[d0] else "bull"
        if regime == "bull":
            r = s.stoploss_exit_side(closes, d0, long_stop, "long", max_days=max_days)
            action = "long"
        else:
            out = m.takeprofit_stoploss_exit(closes, d0, bear_tp, bear_sl, max_days=max_days)
            r = None if out is None else -out[1]  # takeprofit_stoploss_exitはr(long基準の生の変化率)を返す→ベアの損益は符号反転
            action = "bear"
        if r is None:
            continue
        results.append({"date": d0, "regime": regime, "action": action, "net": r - COST_ROUNDTRIP})
    return results


def net_list(results):
    return [r["net"] for r in results]


def main():
    print("=== 試行プールを構築中(regime_shift一族) ===")
    trial_sharpes: list[float] = []
    trial_labels: list[str] = []

    closes_n225 = n.fetch_closes(n.TICKER)
    shocks_n225 = s.find_shock_days(closes_n225, n.THRESHOLD, n.COOLDOWN)
    closes_1306 = m.fetch_split_safe(m.TICKER)
    shocks_1306 = s.find_shock_days(closes_1306, s.THRESHOLD, s.COOLDOWN)

    print(f"日経平均: {min(closes_n225)}〜{max(closes_n225)}, ショック{len(shocks_n225)}件")
    print(f"1306: {min(closes_1306)}〜{max(closes_1306)}, ショック{len(shocks_1306)}件\n")

    print("[a] 連続損切りレジーム(項目94) 8試行 ...")
    for sl_pct in (0.10, 0.15):
        for n_consec in (2, 3):
            for bear_action in ("skip", "short"):
                res = n.regime_backtest(closes_n225, shocks_n225, sl_pct, n_consec, bear_action)
                rets = net_list(res)
                if len(rets) < 2:
                    continue
                trial_sharpes.append(trade_sharpe(rets))
                trial_labels.append(f"consec sl{sl_pct} n{n_consec} {bear_action}(n={len(rets)})")

    print("[b] 単純MAレジーム(項目95) 10試行 ...")
    for window in (100, 150, 200, 250, 300):
        ma = moving_average_dict(closes_n225, window)
        for bear_action in ("skip", "short"):
            res = n.ma_regime_backtest(closes_n225, shocks_n225, ma, bear_action)
            rets = net_list(res)
            if len(rets) < 2:
                continue
            trial_sharpes.append(trade_sharpe(rets))
            trial_labels.append(f"MA{window} {bear_action}(n={len(rets)})")

    print("[c] ドローダウン基準レジーム(項目98・99) 16試行 ...")
    high_n225 = d.trailing_high(closes_n225, 252)
    high_1306 = d.trailing_high(closes_1306, 252)
    for dd_th in (0.10, 0.15, 0.20, 0.25):
        for bear_action in ("skip", "short"):
            res = d.drawdown_regime_backtest(closes_n225, shocks_n225, high_n225, dd_th, bear_action)
            rets = net_list(res)
            if len(rets) >= 2:
                trial_sharpes.append(trade_sharpe(rets))
                trial_labels.append(f"DD{dd_th} {bear_action} N225(n={len(rets)})")
            res2 = d.drawdown_regime_backtest(closes_1306, shocks_1306, high_1306, dd_th, bear_action)
            rets2 = net_list(res2)
            if len(rets2) >= 2:
                trial_sharpes.append(trade_sharpe(rets2))
                trial_labels.append(f"DD{dd_th} {bear_action} 1306(n={len(rets2)})")

    print("[d] デッドクロス基準レジーム(項目114) 9試行 ...")
    dc_results_by_config = {}
    for fast_n in (90, 120, 150):
        for slow_n in (280, 350, 400):
            ma_fast = moving_average_dict(closes_n225, fast_n)
            ma_slow = moving_average_dict(closes_n225, slow_n)
            res = dead_cross_regime_backtest(closes_n225, shocks_n225, ma_fast, ma_slow)
            rets = net_list(res)
            dc_results_by_config[(fast_n, slow_n)] = res
            if len(rets) < 2:
                continue
            trial_sharpes.append(trade_sharpe(rets))
            trial_labels.append(f"deadcross {fast_n}/{slow_n}(n={len(rets)})")

    n_trials = len(trial_sharpes)
    sigma_sr = pystats.pstdev(trial_sharpes)
    print(f"\n合計試行数 N={n_trials}")
    print(f"試行Sharpe(トレード単位)の標準偏差 σ_SR={sigma_sr:.3f}(平均{pystats.mean(trial_sharpes):+.3f})")
    print("\n内訳(試行Sharpe降順、上位10件):")
    for lbl, sh in sorted(zip(trial_labels, trial_sharpes), key=lambda x: -x[1])[:10]:
        print(f"  {sh:+.3f}  {lbl}")

    sr0 = expected_max_sharpe(sigma_sr, n_trials)
    print(f"\n運だけで出る期待最大Sharpe(トレード単位) SR0={sr0:.3f}(N={n_trials}ベース)")

    print("\n=== 採用設定(デッドクロス120/350、ショック-2.5%・cooldown15・長期損切り30%・"
          "ベア利確5%/損切り18%)の評価 ===")
    final_res = dc_results_by_config[(120, 350)]
    final_rets = net_list(final_res)
    sr_hat = trade_sharpe(final_rets)
    skew, kurt = skew_kurt(final_rets)
    t = len(final_rets)
    print(f"日経平均61年(1965〜2026)でのトレード数T={t}、トレードSharpe={sr_hat:+.3f}")
    dsr = deflated_sharpe(sr_hat, t, skew, kurt, sr0)
    print(f"DSR(N={n_trials}ベース) = {dsr*100:.1f}%  ({verdict_label(dsr)})")

    print("\n注意:")
    print("- (a)(b)は当時inlineで実行された一回きりの試行をSESSION_LOG本文の記述から")
    print("  再構成した近似(元のコードは保存されていない)。(c)(d)は実コードの厳密な再現。")
    print("- ここでのSharpeは『トレード単位』(1306/RSI一族の日次Sharpeとは基準が違う)ため、")
    print("  project_wide_dsr_lab.py(N=272)のσ_SRとは直接merge・比較しない方が良い"
          "(サンプリング頻度が異なる異種プールになるため)。")
    print("- DSRはあくまで参考値。>95%で『運では説明しにくい』の目安、<50%で『試行数を")
    print("  考えるとノイズと区別できない』の目安(絶対的な合格基準ではない)。")


if __name__ == "__main__":
    main()
