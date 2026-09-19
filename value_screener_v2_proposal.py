#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
割安株スクリーナー v2(提案・未適用) — 横断的考察(2026-09-19)を反映した改善案
=====================================================================
★★★ これは提案のみで、本体には一切組み込んでいない ★★★
  - value_screener.py(本体、value_run.batから毎日自動実行・dashboard.htmlが読む)は
    一切変更していない。このスクリプトは独立して動き、別ファイルに出力する。
  - ユーザーの明示的なOKが出るまで、value_run.bat・dashboard.htmlには一切配線しない。

FACTOR_RESEARCH_LOG.md「横断的考察(2026-09-19)」6節で提案した3つの改善を実装:
  1. ユニバースを日経225(225銘柄)→東証プライム全銘柄(約1,556銘柄)に拡張
     (個別銘柄検証は常にプライムを使う方針、feedback_tati_bot_full_universe_defaultと同じ理由)
  2. 「ROE>=3%で足切り」という二値フィルターを、「割安さと同じパーセンタイル順位」に
     変えて質を連続変量として組み込む(横断的考察3節: B/Mで統制するとROIC・QMJ・
     健全性は4/4年度でプラス。「割安かつ高収益」が最も筋が良いという結論の反映)
  3. 反発スコアの重みを50%→25%に下げる(横断的考察: 52週高値への近さ・ターンアラウンド・
     モメンタムはいずれも12ヶ月では効果なしと判明。反発シグナル自体は残すが比重を下げる)

使い方: python value_screener_v2_proposal.py
出力: value_ranking_v2_proposal.json(本体のvalue_ranking.jsonとは別ファイル)
"""
from __future__ import annotations
import csv
import json
import os
import time
import datetime as dt

import yfinance as yf

from research_agents import _rsi

CHECKPOINT_EVERY = 25
MAX_PAYOUT_RATIO = 1.0
MIN_EARNINGS_GROWTH = -0.20
MAX_DEBT_TO_EQUITY = 200
FINANCIAL_SECTOR = "Financial Services"
MIN_ROE_FLOOR = 0.0  # 赤字(ROE<0)のみ除外。3%足切りは廃止し、質は連続スコア化する
RECENT_LOW_WINDOW = 60
MA_SHORT, MA_LONG = 25, 75
OVERBOUGHT_RSI = 70
TOP_N = 50
VALUE_WEIGHT = 0.75   # 旧version: 0.5。反発スコアの比重を下げる(横断的考察6節)
TURNAROUND_WEIGHT = 0.25


def load_universe() -> list[tuple[str, str]]:
    with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
        return [(row["code"], row["name"]) for row in csv.DictReader(f)]


def _num(v):
    """yfinanceのinfoは稀に数値項目が文字列や非数値で返ることがあるため、安全にfloat化する。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN除外


def fetch_metrics(code: str, name: str) -> dict | None:
    try:
        info = yf.Ticker(f"{code}.T").info
    except Exception:
        return None

    per = _num(info.get("trailingPE"))
    pbr = _num(info.get("priceToBook"))
    div_yield = _num(info.get("dividendYield")) or 0.0
    roe = _num(info.get("returnOnEquity"))
    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    payout_ratio = _num(info.get("payoutRatio"))
    earnings_growth = _num(info.get("earningsGrowth"))
    debt_to_equity = _num(info.get("debtToEquity"))
    sector = info.get("sector")

    if per is None or per <= 0 or pbr is None or pbr <= 0 or roe is None:
        return None
    if roe < MIN_ROE_FLOOR:
        return None  # 赤字のみ除外(質は後段でパーセンタイル化して連続的に評価)
    if payout_ratio is not None and payout_ratio > MAX_PAYOUT_RATIO:
        return None
    if earnings_growth is not None and earnings_growth < MIN_EARNINGS_GROWTH:
        return None
    if sector != FINANCIAL_SECTOR and debt_to_equity is not None and debt_to_equity > MAX_DEBT_TO_EQUITY:
        return None

    return {
        "code": code, "name": name, "per": per, "pbr": pbr,
        "dividend_yield": div_yield, "roe": roe, "price": price,
        "payout_ratio": payout_ratio, "earnings_growth": earnings_growth,
        "debt_to_equity": debt_to_equity, "sector": sector,
    }


def fetch_turnaround_signals(code: str) -> dict | None:
    try:
        hist = yf.Ticker(f"{code}.T").history(period="1y")
        closes = [float(x) for x in hist["Close"].dropna().tolist()]
    except Exception:
        return None
    need = max(RECENT_LOW_WINDOW, MA_LONG) + 21
    if len(closes) < need:
        return None

    current = closes[-1]
    recent_low = min(closes[-RECENT_LOW_WINDOW:])
    off_low_pct = (current / recent_low - 1) * 100 if recent_low > 0 else 0.0

    ma_short = sum(closes[-MA_SHORT:]) / MA_SHORT
    ma_long = sum(closes[-MA_LONG:]) / MA_LONG
    trend_pct = (ma_short / ma_long - 1) * 100 if ma_long > 0 else 0.0

    ret_recent = closes[-1] / closes[-21] - 1
    ret_prior = closes[-21] / closes[-41] - 1
    decel_pct = (ret_recent - ret_prior) * 100

    rsi14 = _rsi(closes, len(closes) - 1, 14)

    return {"code": code, "off_low_pct": off_low_pct, "trend_pct": trend_pct,
            "decel_pct": decel_pct, "rsi14": rsi14}


def percentile_rank(values: list[float], reverse: bool = False) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=reverse)
    ranks = [0.0] * len(values)
    n = len(values)
    for rank, idx in enumerate(order):
        ranks[idx] = 1.0 - rank / max(1, n - 1)
    return ranks


def run_checkpointed(universe, fetch_fn, checkpoint_path, cache_path, label):
    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        return json.load(open(cache_path, encoding="utf-8"))

    if os.path.exists(checkpoint_path):
        state = json.load(open(checkpoint_path, encoding="utf-8"))
        print(f"チェックポイントから再開: {len(state['done_codes'])}銘柄処理済み")
    else:
        state = {"rows": [], "done_codes": []}

    done = set(state["done_codes"])
    todo = [x for x in universe if x[0] not in done]
    print(f"{label}: 残り{len(todo)}/{len(universe)}銘柄を取得中...")
    for i, (code, name) in enumerate(todo, 1):
        r = fetch_fn(code, name)
        if r:
            state["rows"].append(r)
        state["done_codes"].append(code)
        if i % CHECKPOINT_EVERY == 0:
            json.dump(state, open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  {i}/{len(todo)}件処理済み(有効{len(state['rows'])})...")
        time.sleep(0.1)

    json.dump(state["rows"], open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
    return state["rows"]


def main() -> None:
    universe = load_universe()
    print(f"東証プライム、{len(universe)}銘柄のデータを取得中(yfinance)...")

    rows = run_checkpointed(
        universe, fetch_metrics,
        "v2_metrics_checkpoint.json", "v2_metrics_cache.json", "指標取得",
    )
    print(f"\n質フィルター後(赤字のみ除外): {len(rows)}/{len(universe)}銘柄が対象")

    per_scores = percentile_rank([r["per"] for r in rows])
    pbr_scores = percentile_rank([r["pbr"] for r in rows])
    div_scores = percentile_rank([r["dividend_yield"] for r in rows], reverse=True)
    roe_scores = percentile_rank([r["roe"] for r in rows], reverse=True)  # 質を連続変量化

    for r, ps, bs, ds, qs in zip(rows, per_scores, pbr_scores, div_scores, roe_scores):
        r["cheapness_score"] = round((ps + bs + ds) / 3, 4)  # 従来の「割安スコア」相当
        r["quality_score"] = round(qs, 4)
        r["value_score"] = round((ps + bs + ds + qs) / 4, 4)  # 割安さ+質を等ウェイトで統合

    print(f"反発シグナル(価格推移)を取得中... ({len(rows)}銘柄)")
    ta_rows_raw = run_checkpointed(
        [(r["code"], r["code"]) for r in rows], lambda c, _n: fetch_turnaround_signals(c),
        "v2_turnaround_checkpoint.json", "v2_turnaround_cache.json", "反発シグナル取得",
    )
    ta_by_code = {ta["code"]: ta for ta in ta_rows_raw}

    ta_rows = []
    for r in rows:
        ta = ta_by_code.get(r["code"])
        if ta:
            r.update(ta)
            ta_rows.append(r)

    is_overbought = lambda r: r["rsi14"] is not None and r["rsi14"] >= OVERBOUGHT_RSI
    overbought = [r for r in ta_rows if is_overbought(r)]
    eligible = [r for r in ta_rows if not is_overbought(r)]
    print(f"除外(RSI{OVERBOUGHT_RSI}以上): {len(overbought)}銘柄")

    off_low_scores = percentile_rank([r["off_low_pct"] for r in eligible], reverse=True)
    trend_scores = percentile_rank([r["trend_pct"] for r in eligible], reverse=True)
    decel_scores = percentile_rank([r["decel_pct"] for r in eligible], reverse=True)
    for r, o, t, d in zip(eligible, off_low_scores, trend_scores, decel_scores):
        r["turnaround_score"] = round((o + t + d) / 3, 4)
        r["combined_score"] = round(VALUE_WEIGHT * r["value_score"] + TURNAROUND_WEIGHT * r["turnaround_score"], 4)

    eligible.sort(key=lambda r: r["combined_score"], reverse=True)
    top = eligible[:TOP_N]

    output = {
        "updated": dt.datetime.now().isoformat(timespec="seconds"),
        "universe": "tse_prime(proposal)",
        "universe_size": len(universe),
        "screened": len(eligible),
        "method_v2": f"割安さ(PER・PBR・配当利回り)+質(ROE、連続パーセンタイル化)を等ウェイトで"
                     f"統合したvalue_score({VALUE_WEIGHT:.0%})と、反発スコア({TURNAROUND_WEIGHT:.0%})"
                     f"を組み合わせた総合スコア。本体(value_screener.py、50:50・日経225・ROE3%足切り)"
                     f"からの変更点はFACTOR_RESEARCH_LOG.md横断的考察6節参照。",
        "disclaimer": "提案・検証中のスコアリングです。本体(dashboard.html/value_ranking.json)には"
                      "組み込まれていません。売買シグナルではありません。",
        "ranking": [
            {
                "rank": i + 1, "code": r["code"], "name": r["name"], "price": r["price"],
                "per": round(r["per"], 2), "pbr": round(r["pbr"], 2),
                "dividend_yield_pct": round(r["dividend_yield"], 2), "roe_pct": round(r["roe"] * 100, 1),
                "cheapness_score": r["cheapness_score"], "quality_score": r["quality_score"],
                "value_score": r["value_score"], "turnaround_score": r["turnaround_score"],
                "combined_score": r["combined_score"],
                "rsi14": round(r["rsi14"], 1) if r["rsi14"] is not None else None,
                "sector": r["sector"],
            }
            for i, r in enumerate(top)
        ],
    }

    with open("value_ranking_v2_proposal.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n=== v2提案ランキング TOP10(全{TOP_N}件はvalue_ranking_v2_proposal.json参照) ===")
    for r in top[:10]:
        print(f"  {r['code']} {r['name']:12s} PER{r['per']:.1f} PBR{r['pbr']:.2f} "
              f"配当{r['dividend_yield']:.1f}% ROE{r['roe']*100:.1f}% "
              f"割安{r['cheapness_score']:.2f} 質{r['quality_score']:.2f} "
              f"value{r['value_score']:.2f} 反発{r['turnaround_score']:.2f} 総合{r['combined_score']:.3f}")


if __name__ == "__main__":
    main()
