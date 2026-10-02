#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
銘柄間平均相関(相関スパイク/低相関グラインド判定)によるregime_shift追加トリガーの検証
=====================================================================================
調査アイデア: リーマン・コロナのような「イベント型」急落では個別銘柄の値動きの違いが
消えて全面安(銘柄間相関が急上昇)になるが、2000-2003年のITバブル崩壊のような「じわじわ型」
下落では銘柄ごとの強弱(勝ち組/負け組)が残ったまま全体が沈むため、相関はそこまで上がらない
可能性がある。regime_shift_agent.pyの既存ショック検知(1日-2.5%以下の急落)は「イベント型」
には強いが「じわじわ型」の検知が弱いことが判明しているため、「低相関のまま日経平均が
下落を続けている」状態を補完的な追加ベア切替トリガーとして使えるか検証する。

手法:
  1. market_breadth_cache.json(東証プライム全銘柄の日次終値、再取得せずそのまま使用)から
     各銘柄の日次リターンを計算。
  2. 「個別銘柄リターンと市場平均(全銘柄の等加重平均)リターンとの直近window日ローリング
     相関」を全銘柄で計算し、日ごとに平均する(フルペアワイズ相関のO(N^2)サンプリングより
     軽量な近似。pandasのrolling演算で全銘柄を一括ベクトル化計算)。
  3. IS期間(最初の65%、cusum_regime_lab.py等と同じ比率)の平均相関分布からパーセンタイルで
     閾値を固定で決める(バックテスト結果を見てから閾値を探索することはしない)。
  4. デッドクロス下落レジーム中、「平均相関が閾値未満」かつ「日経平均の直近20日リターンが
     マイナス」の両方を満たしたら、既存ショック検知に加えた追加トリガーとしてベア(1571)へ
     一時切替(cooldown・最大保有20日・利確5%/損切り18%は既存設計のまま)。

使い方: python correlation_spike_regime_lab.py
"""
from __future__ import annotations

import datetime as dt
import json
import time
from collections import defaultdict

import numpy as np
import pandas as pd
import yfinance as yf

TAX_RATE = 0.20315
COST = 0.002
PRINCIPAL = 9_181_229
MA_FAST, MA_SLOW = 120, 350
SHOCK_TH, COOLDOWN = -0.025, 15
BEAR_TP, BEAR_SL, MAX_HOLD = 0.05, 0.18, 20
IS_RATIO = 0.65
MIN_STOCKS = 200          # この数未満しか集計対象がない日は信頼できないので除外
NIKKEI_DECLINE_WINDOW = 20  # 「日経平均が下落を続けている」の判定窓


# ======================================================================
# 1. market_breadth_cache.jsonから価格パネルを構築
# ======================================================================
def load_price_panel() -> pd.DataFrame:
    t0 = time.time()
    with open("market_breadth_cache.json", encoding="utf-8") as f:
        cache = json.load(f)
    series = {}
    for code, v in cache.items():
        if len(v["closes"]) < 50:
            continue
        idx = pd.to_datetime(v["dates"])
        s = pd.Series(v["closes"], index=idx, dtype="float64")
        s = s[~s.index.duplicated(keep="last")]
        series[code] = s
    prices = pd.DataFrame(series).sort_index()
    print(f"[price panel] {time.time()-t0:.1f}s, shape={prices.shape}, "
          f"{prices.index.min().date()}~{prices.index.max().date()}")
    return prices


def compute_avg_corr(rets: pd.DataFrame, mkt_ret: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    """各銘柄リターンと市場平均リターンとのローリング相関を全銘柄一括(ベクトル化)で計算し、
    日ごとに平均する(=平均ペアワイズ相関の近似)。フルペアワイズ(O(N^2))サンプリングより
    軽量。戻り値: (日次の平均相関Series, 日次の集計対象銘柄数Series)。"""
    roll_mx = rets.rolling(window).mean()
    roll_mx2 = (rets ** 2).rolling(window).mean()
    var_x = (roll_mx2 - roll_mx ** 2).clip(lower=0)

    roll_mm = mkt_ret.rolling(window).mean()
    roll_mm2 = (mkt_ret ** 2).rolling(window).mean()
    var_m = (roll_mm2 - roll_mm ** 2).clip(lower=0)

    cross = rets.multiply(mkt_ret, axis=0)
    roll_mxm = cross.rolling(window).mean()
    cov_xm = roll_mxm.sub(roll_mx.mul(roll_mm, axis=0), axis=0)

    std_x = var_x ** 0.5
    std_m = var_m ** 0.5
    corr_df = cov_xm.div(std_x, axis=0).div(std_m, axis=0)

    avg_corr = corr_df.mean(axis=1, skipna=True)
    n_valid = corr_df.count(axis=1)
    return avg_corr, n_valid


def build_avg_corr_series(prices: pd.DataFrame, rets: pd.DataFrame, mkt_ret: pd.Series,
                           window: int) -> pd.Series:
    avg_corr, n_valid = compute_avg_corr(rets, mkt_ret, window)
    avg_corr = avg_corr[n_valid >= MIN_STOCKS]
    return avg_corr


# ======================================================================
# 2. 記述統計: IT/リーマン/コロナ期の平均相関を比較
# ======================================================================
def describe_periods(avg_corr: pd.Series, window: int) -> None:
    def stat(label, start, end):
        sub = avg_corr.loc[start:end]
        if len(sub) == 0:
            print(f"  {label:<32}: データなし")
            return
        print(f"  {label:<32}: n={len(sub):>5}日  平均={sub.mean():.4f}  中央値={sub.median():.4f}")

    print(f"\n=== 記述統計(window={window}日ローリング相関、全銘柄平均、"
          f"有効銘柄数>={MIN_STOCKS}日のみ) ===")
    stat("2000-2003年(ITバブル崩壊)", "2000-01-01", "2003-12-31")
    stat("2001-2003年(データ充足期間)", "2001-01-01", "2003-12-31")
    stat("2008-2009上(リーマン)", "2008-01-01", "2009-06-30")
    stat("2020年(コロナ)", "2020-01-01", "2020-12-31")
    stat("2020-02~04(コロナ急落局面)", "2020-02-15", "2020-04-30")
    stat("全期間", avg_corr.index.min().date().isoformat(), avg_corr.index.max().date().isoformat())


# ======================================================================
# 3. IS期間パーセンタイルで閾値を固定で決める(探索しない)
# ======================================================================
def is_threshold(avg_corr: pd.Series, percentile: int) -> float:
    cut = avg_corr.index[int(len(avg_corr) * IS_RATIO)]
    is_part = avg_corr.loc[:cut]
    th = float(is_part.quantile(percentile / 100))
    print(f"  IS期間 {is_part.index.min().date()}~{is_part.index.max().date()}"
          f"({len(is_part)}日) のp{percentile} = {th:.4f}")
    return th


# ======================================================================
# 4. 日経平均とレジーム判定(既存ラボと同じ枠組み)
# ======================================================================
def sma(arr, w):
    out = [None] * len(arr)
    s = 0.0
    for i, v in enumerate(arr):
        s += v
        if i >= w:
            s -= arr[i - w]
        if i >= w - 1:
            out[i] = s / w
    return out


def gen_switches(px, dates, dc_regime, corr_for_day, nikkei_ret_decline, use_corr: bool, corr_th: float):
    n = len(px)
    events = [(0, "long")]
    holding = "long"
    entry_i = 0
    last_shock = -10 ** 9
    for i in range(MA_SLOW, n):
        if holding == "bear":
            r = -(px[i] / px[entry_i] - 1)
            held = i - entry_i
            if r >= BEAR_TP or r <= -BEAR_SL or held >= MAX_HOLD:
                events.append((i, "long"))
                holding = "long"
                entry_i = i
        else:
            day_ret = px[i] / px[i - 1] - 1
            is_shock = day_ret <= SHOCK_TH
            corr_trigger = False
            if use_corr and corr_for_day[i] is not None and nikkei_ret_decline[i] is not None:
                corr_trigger = corr_for_day[i] < corr_th and nikkei_ret_decline[i] < 0
            triggered = is_shock or corr_trigger
            cd_ok = (i - last_shock) >= COOLDOWN
            if triggered and cd_ok and dc_regime[i] == "bear":
                events.append((i, "bear"))
                holding = "bear"
                entry_i = i
                last_shock = i
            elif triggered:
                last_shock = i
    return events


def evaluate(px, dates, events, start_year):
    n = len(px)
    start_date = dt.date(start_year, 1, 1)
    start_i = next((i for i, d in enumerate(dates) if d >= start_date), None)
    if start_i is None:
        return None
    leg = "long"
    for i, tgt in events:
        if i > start_i:
            break
        leg = tgt
    ev_in = [(i, tgt) for i, tgt in events if i > start_i]
    equity = PRINCIPAL
    last_switch_eq = PRINCIPAL
    yearly = defaultdict(float)
    prev = px[start_i]
    ev_iter = iter(ev_in)
    next_ev = next(ev_iter, None)
    for i in range(start_i + 1, n):
        ratio = px[i] / prev if leg == "long" else 1 + -(px[i] / prev - 1)
        equity *= ratio
        prev = px[i]
        while next_ev is not None and next_ev[0] == i:
            equity *= (1 - COST)
            yearly[dates[i].year] += equity - last_switch_eq
            last_switch_eq = equity
            leg = next_ev[1]
            next_ev = next(ev_iter, None)
        if i == n - 1 or dates[i + 1].year != dates[i].year:
            g = yearly.get(dates[i].year, 0.0)
            if g > 0:
                tax = g * TAX_RATE
                equity -= tax
                last_switch_eq = equity
    bh = PRINCIPAL * (px[-1] / px[start_i])
    return equity, bh, len(ev_in)


def run_backtest(px, dates, dc_regime, avg_corr: pd.Series, corr_th: float, label: str,
                  start_years=(2000, 2006, 1965)):
    n = len(px)
    # 日経の取引日に合わせて、avg_corrを前方補完(breadth系ラボと同じ方式)
    corr_map = {d.date(): v for d, v in avg_corr.items()}
    corr_for_day = [None] * n
    last_c = None
    for i, d in enumerate(dates):
        if d in corr_map:
            last_c = corr_map[d]
        corr_for_day[i] = last_c

    nikkei_ret_decline = [None] * n
    for i in range(NIKKEI_DECLINE_WINDOW, n):
        nikkei_ret_decline[i] = px[i] / px[i - NIKKEI_DECLINE_WINDOW] - 1

    base = gen_switches(px, dates, dc_regime, corr_for_day, nikkei_ret_decline, False, corr_th)
    new = gen_switches(px, dates, dc_regime, corr_for_day, nikkei_ret_decline, True, corr_th)

    print(f"\n--- {label} ---")
    print(f"{'開始年':<8}{'買い持ち':>14}{'現行':>16}{'相関追加':>16}")
    for y in start_years:
        rb = evaluate(px, dates, base, y)
        rn = evaluate(px, dates, new, y)
        if rb is None or rn is None:
            print(f"{y}年〜 データ不足")
            continue
        eb, bh, nb = rb
        en, _, nn = rn
        chg = (en / eb - 1) * 100 if eb else 0.0
        print(f"{y}年〜 {bh:>12,.0f}円 {eb:>14,.0f}円({nb}回) {en:>14,.0f}円({nn}回)  変化{chg:+.1f}%")

    base_i = set(i for i, _ in base)
    new_i = set(i for i, _ in new)
    new_ev = sorted(new_i - base_i)
    print(f"新規発生イベント総数(全期間): {len(new_ev)}件")
    it_bubble_ev = [i for i in new_ev if dt.date(2001, 1, 1) <= dates[i] <= dt.date(2003, 12, 31)]
    print(f"  うち2001-2003年(ITバブル期間)の新規イベント: {len(it_bubble_ev)}件")
    for i in it_bubble_ev[:20]:
        print(f"    {dates[i]}  avg_corr={corr_for_day[i]:.4f}  nikkei20d={nikkei_ret_decline[i]*100:+.1f}%")
    return base, new


def main():
    prices = load_price_panel()
    rets = prices.pct_change()
    mkt_ret = rets.mean(axis=1, skipna=True)

    print("\n=== 日経平均(^N225)取得 ===")
    df = yf.Ticker("^N225").history(period="max", auto_adjust=True).dropna(subset=["Close"])
    closes = list(zip([d.date() for d in df.index], [float(c) for c in df["Close"]]))
    dates = [d for d, _ in closes]
    px = [p for _, p in closes]
    n = len(px)
    print(f"日経平均: {dates[0]} ~ {dates[-1]} ({n}本)")

    ma_fast = sma(px, MA_FAST)
    ma_slow = sma(px, MA_SLOW)
    dc_regime = ["bull" if (ma_fast[i] is None or ma_slow[i] is None or ma_fast[i] >= ma_slow[i])
                 else "bear" for i in range(n)]

    # ------------------------------------------------------------------
    # 主要結果: window=20日、閾値=IS期間p25
    # ------------------------------------------------------------------
    PRIMARY_WINDOW = 20
    PRIMARY_PCTL = 25

    print(f"\n=== window={PRIMARY_WINDOW}日の平均相関系列を計算 ===")
    avg_corr_20 = build_avg_corr_series(prices, rets, mkt_ret, PRIMARY_WINDOW)
    describe_periods(avg_corr_20, PRIMARY_WINDOW)

    print(f"\n=== 閾値決定(IS期間p{PRIMARY_PCTL}、バックテスト結果を見ずに固定) ===")
    th_primary = is_threshold(avg_corr_20, PRIMARY_PCTL)

    run_backtest(px, dates, dc_regime, avg_corr_20, th_primary,
                 label=f"主要結果: window={PRIMARY_WINDOW}, 閾値=p{PRIMARY_PCTL}({th_primary:.4f})")

    # ------------------------------------------------------------------
    # 頑健性チェック1: 閾値パーセンタイルを振る(window固定=20)
    # ------------------------------------------------------------------
    print("\n\n######## 頑健性チェック1: 閾値パーセンタイルを20/25/30で振る(window=20固定) ########")
    for pctl in (20, 25, 30):
        th = is_threshold(avg_corr_20, pctl)
        run_backtest(px, dates, dc_regime, avg_corr_20, th,
                     label=f"閾値ロバスト: window=20, 閾値=p{pctl}({th:.4f})")

    # ------------------------------------------------------------------
    # 頑健性チェック2: windowを振る(閾値パーセンタイル固定=25)
    # ------------------------------------------------------------------
    print("\n\n######## 頑健性チェック2: windowを15/20/25で振る(閾値=IS期間p25固定) ########")
    for w in (15, 20, 25):
        avg_corr_w = build_avg_corr_series(prices, rets, mkt_ret, w)
        th = is_threshold(avg_corr_w, PRIMARY_PCTL)
        run_backtest(px, dates, dc_regime, avg_corr_w, th,
                     label=f"windowロバスト: window={w}, 閾値=p{PRIMARY_PCTL}({th:.4f})")

    print("\n完了")


if __name__ == "__main__":
    main()
