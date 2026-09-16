#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学術研究で報告されている代表的な株式ファクターの検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

日経225ユニバース・yfinanceで取得可能な範囲で、以下5つの学術的に有名な
アノマリー(市場の効率性への例外)を検証する:

  1. モメンタム効果(Jegadeesh & Titman 1993): 過去12ヶ月(直近1ヶ月除く)の
     リターンが高い銘柄は、その後も相対的に強い。
  2. 低ボラティリティ・アノマリー(Ang et al. 2006, Frazzini & Pedersen
     "Betting Against Beta"): 低ボラ銘柄は好況・不況通してもリスクの割に
     リターンが高い(時には絶対リターンでも高ボラに勝る)。
  3. Piotroski Fスコア(Piotroski 2000): 財務健全性9項目のチェックリスト。
     スコアが高いほどその後のリターンが良いとされる。
  4. 決算後モメンタム/PEAD(Bernard & Thomas 1989): 決算サプライズ(予想比)が
     プラス/マイナスだった銘柄は、発表後もその方向に動き続ける傾向。
  5. 小型株効果(Banz 1981): 時価総額の小さい銘柄が長期的に大型株を上回る。
     ※日経225自体が大型株中心のインデックスのため、この検証には不利な
       ユニバールである点に注意(効果が出にくくて当然)。

途中経過は逐次JSONに保存する(前回、東証プライム全銘柄検証でメモリ不足により
全データを失った反省を踏まえた対策)。

使い方: python academic_factors_lab.py
"""
from __future__ import annotations
import datetime as dt
import json
import os
import statistics as pystats
from collections import defaultdict

import yfinance as yf

from value_screener import NIKKEI225

CHECKPOINT_PATH = "academic_factors_checkpoint.json"
CHECKPOINT_EVERY = 25


def to_price_map(hist) -> dict:
    return {idx.date(): float(row["Close"]) for idx, row in hist.iterrows()}


def nearest_price(price_map: dict, target_date, max_days=10):
    for offset in range(max_days):
        d = (target_date + dt.timedelta(days=offset))
        if d in price_map:
            return price_map[d]
    return None


def piotroski_fscore(inc, bs, cf) -> dict[int, int] | None:
    """年度(西暦)ごとのFスコア(0-9)を返す。前年度との比較が必要なため、
    最も古い年度はスコア計算不可(Noneではなくディクショナリから除外)。"""
    cols = sorted(inc.columns, key=lambda c: c)
    scores = {}
    for i in range(1, len(cols)):
        cur, prev = cols[i], cols[i - 1]
        try:
            def g(df, key, col):
                return df.loc[key, col] if key in df.index and col in df.columns else None

            ni_cur = g(inc, "Net Income", cur)
            ta_cur = g(bs, "Total Assets", cur)
            ta_prev = g(bs, "Total Assets", prev)
            ni_prev = g(inc, "Net Income", prev)
            ocf_cur = g(cf, "Operating Cash Flow", cur)
            ltd_cur = g(bs, "Long Term Debt", cur) or 0
            ltd_prev = g(bs, "Long Term Debt", prev) or 0
            ca_cur = g(bs, "Current Assets", cur)
            cl_cur = g(bs, "Current Liabilities", cur) or 1
            ca_prev = g(bs, "Current Assets", prev)
            cl_prev = g(bs, "Current Liabilities", prev) or 1
            shares_cur = g(bs, "Ordinary Shares Number", cur)
            shares_prev = g(bs, "Ordinary Shares Number", prev)
            gp_cur = g(inc, "Gross Profit", cur)
            rev_cur = g(inc, "Total Revenue", cur) or 1
            gp_prev = g(inc, "Gross Profit", prev)
            rev_prev = g(inc, "Total Revenue", prev) or 1

            if None in (ni_cur, ta_cur, ta_prev, ni_prev, ocf_cur, ca_cur, ca_prev, shares_cur, shares_prev):
                continue

            roa_cur = ni_cur / ta_cur
            roa_prev = ni_prev / ta_prev
            score = 0
            score += 1 if ni_cur > 0 else 0                          # 1. 黒字
            score += 1 if ocf_cur > 0 else 0                         # 2. 営業CFプラス
            score += 1 if roa_cur > roa_prev else 0                  # 3. ROA改善
            score += 1 if ocf_cur > ni_cur else 0                    # 4. CF>利益(利益の質)
            score += 1 if (ltd_cur / ta_cur) < (ltd_prev / ta_prev) else 0  # 5. 負債比率低下
            score += 1 if (ca_cur / cl_cur) > (ca_prev / cl_prev) else 0    # 6. 流動比率改善
            score += 1 if shares_cur <= shares_prev * 1.01 else 0     # 7. 希薄化なし
            if gp_cur is not None and gp_prev is not None:
                score += 1 if (gp_cur / rev_cur) > (gp_prev / rev_prev) else 0  # 8. 粗利率改善
            score += 1 if (rev_cur / ta_cur) > (ni_prev and rev_prev / ta_prev or 0) else 0  # 9. 資産回転率改善
            scores[cur.year] = score
        except (KeyError, ZeroDivisionError, TypeError):
            continue
    return scores if scores else None


def analyze_stock(code: str) -> dict:
    out = {"code": code, "momentum": [], "lowvol": [], "fscore": [], "pead": [], "size": None}
    ticker = yf.Ticker(f"{code}.T")
    try:
        hist = ticker.history(period="3y", interval="1d")
    except Exception:
        hist = None

    # --- 1. モメンタム & 2. 低ボラ(価格データのみで計算) ---
    if hist is not None and len(hist) > 300:
        closes = hist["Close"].tolist()
        n = len(closes)
        step = 21  # 月次スナップショット
        for i in range(273, n - 60, step):
            past12 = closes[i - 252:i - 21]
            if len(past12) < 200:
                continue
            momentum = closes[i - 21] / closes[i - 252] - 1
            rets = [closes[j] / closes[j - 1] - 1 for j in range(i - 252, i)]
            vol = pystats.pstdev(rets) if len(rets) > 30 else None
            fwd60 = closes[i + 60] / closes[i] - 1 if i + 60 < n else None
            if fwd60 is not None:
                out["momentum"].append({"date": hist.index[i].date().isoformat(),
                                         "score": momentum, "fwd60": fwd60})
                if vol is not None:
                    out["lowvol"].append({"date": hist.index[i].date().isoformat(),
                                           "score": vol, "fwd60": fwd60})

    # --- 3. Piotroski Fスコア ---
    try:
        inc, bs, cf = ticker.income_stmt, ticker.balance_sheet, ticker.cashflow
        fscores = piotroski_fscore(inc, bs, cf)
        if fscores and hist is not None:
            price_map = to_price_map(hist)
            for year, score in fscores.items():
                reveal = dt.date(year, 6, 1)  # 決算発表タイムラグの簡易近似
                p0 = nearest_price(price_map, reveal)
                p1 = nearest_price(price_map, reveal + dt.timedelta(days=365))
                if p0 and p1:
                    out["fscore"].append({"year": year, "score": score, "fwd12mo": p1 / p0 - 1})
    except Exception:
        pass

    # --- 4. PEAD(決算サプライズ後のドリフト) ---
    try:
        ed = ticker.earnings_dates
        if ed is not None and hist is not None and "Surprise(%)" in ed.columns:
            price_map = to_price_map(hist)
            for edate, row in ed.iterrows():
                surprise = row.get("Surprise(%)")
                if surprise is None or surprise != surprise:  # NaN
                    continue
                edate_naive = edate.tz_localize(None) if edate.tzinfo else edate
                p0 = nearest_price(price_map, edate_naive.date())
                p1 = nearest_price(price_map, edate_naive.date() + dt.timedelta(days=28))
                if p0 and p1:
                    out["pead"].append({"date": edate_naive.date().isoformat(),
                                         "surprise": float(surprise), "fwd20d": p1 / p0 - 1})
    except Exception:
        pass

    # --- 5. 時価総額(サイズ) ---
    try:
        info = ticker.info
        mcap = info.get("marketCap")
        if mcap and hist is not None and len(hist) > 2:
            total_ret = hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1
            out["size"] = {"market_cap": mcap, "total_return_3y": total_ret}
    except Exception:
        pass

    return out


def main() -> None:
    if os.path.exists(CHECKPOINT_PATH):
        print(f"チェックポイント({CHECKPOINT_PATH})から再開...")
        all_data = json.load(open(CHECKPOINT_PATH, encoding="utf-8"))
        done_codes = {d["code"] for d in all_data}
    else:
        all_data = []
        done_codes = set()

    todo = [(c, n) for c, n in NIKKEI225 if c not in done_codes]
    print(f"日経225、残り{len(todo)}/{len(NIKKEI225)}銘柄を処理します...")

    for i, (code, name) in enumerate(todo, 1):
        result = analyze_stock(code)
        all_data.append(result)
        if i % CHECKPOINT_EVERY == 0:
            json.dump(all_data, open(CHECKPOINT_PATH, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  {i}/{len(todo)}件処理済み(チェックポイント保存)...")

    json.dump(all_data, open(CHECKPOINT_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n全{len(all_data)}銘柄のデータ取得完了。academic_factors_analyze.py で分析してください。")


if __name__ == "__main__":
    main()
