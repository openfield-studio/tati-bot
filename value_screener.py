#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
割安株スクリーナー(東証プライム全銘柄ユニバース、v2)
=====================================================================
tati-botの拡張機能。東証プライム全銘柄(約1,556社)を対象に、PER・PBR・配当利回りが
魅力的で、かつ質(ROE)も高い銘柄を上位50件ランキングする。

※これはtrading_agents.py/research_agents.pyのRSI逆張り戦略とは別物で、
  「今の割安さのスナップショット」を見せるだけの参考情報。自動売買はしない
  (実際の売買は本人が手動で判断・執行する)。バックテストによる将来予測の
  検証はしていないので、「検証済みのGO戦略」と同列に扱わないこと。

スコアの考え方(2026-09-19、横断的考察を反映してv2に更新):
  - 割安さ: 低PER(実績PER)・低PBR(実績PBR)・高配当利回りを、質フィルター
    通過銘柄内でのパーセンタイル順位に変換し、単純平均する。
  - 質: ROEをパーセンタイル順位化した連続変量。従来の「ROE<3%で除外」という
    二値フィルターは、赤字(ROE<0)のみを除外する形に緩め、質はランキングの一部として
    連続的に評価する(横断的考察: B/Mで統制するとROIC・QMJ・健全性は4/4年度で
    プラス。「割安かつ高収益」が最も筋が良いという結論を反映)。
  - value_score = (割安さ3指標 + 質)を4等分の単純平均。
  - 反発スコア: 「割安なだけで下げ続けている銘柄」を避けるため、①直近60営業日
    安値からの回復率、②短期(25日)/長期(75日)移動平均のトレンド、③直近1ヶ月と
    前1ヶ月のリターンの差(下落の減速/反転)、の3つをパーセンタイル化して平均する。
    RSI(research_agents.pyと同じ計算式)も参考値として併記する。
    ★これは将来を予測するモデルではなく、単純なテクニカルルールに基づく参考シグナル。
    横断的考察で52週高値への近さ・ターンアラウンド・モメンタムはいずれも12ヶ月では
    効果なしと判明したため、比重を下げた(下記VALUE_WEIGHT参照)。
  - 総合スコア = value_score×75% + 反発スコア×25%(旧version: 50%/50%)。

データ取得元: yfinance の Ticker.info(PER/PBR/配当利回り/ROE)と
  Ticker.history(価格推移、反発スコア用)。J-Quantsより単純だが、
  値の欠損・精度はyfinance側の仕様に依存する点に注意。

使い方: python value_screener.py
出力: value_ranking.json (dashboard.htmlが読む想定、.gitignore対象にはしない
      ―― state.json同様、金額情報を含まない銘柄横断の一般的な市況データのため)

変更履歴:
  2026-09-19: 日経225→東証プライム全銘柄に拡張、質フィルターを連続スコア化、
    反発スコアの比重を50%→25%に低減(FACTOR_RESEARCH_LOG.md横断的考察6節、
    value_screener_v2_proposal.pyでの検証結果を反映、ユーザー承認済み)。
    重い処理になったため25銘柄ごとのチェックポイントを追加。
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
MAX_PAYOUT_RATIO = 1.0  # 配当性向がこれ超(利益より配当が多い)は減配リスクとして除外
MIN_EARNINGS_GROWTH = -0.20  # 前年比利益成長率がこれ未満(20%超の減益)は除外
MAX_DEBT_TO_EQUITY = 200  # 非金融業でこれ超は過大な借入として除外(金融業は対象外)
FINANCIAL_SECTOR = "Financial Services"  # yfinanceのsector表記。銀行・証券・保険は
                                          # 業態上D/Eが高いのが通常なので負債フィルター対象外
MIN_ROE_FLOOR = 0.0  # 赤字(ROE<0)のみ除外。質はここでは足切りせず連続スコア化する
RECENT_LOW_WINDOW = 60  # 直近安値からの回復率を見る営業日数
MA_SHORT, MA_LONG = 25, 75  # 短期/長期移動平均
OVERBOUGHT_RSI = 70  # これ以上は「既に反発しきった」として除外
TOP_N = 50
VALUE_WEIGHT = 0.75    # 割安さ+質の合成スコアの重み(旧version: 0.5)
TURNAROUND_WEIGHT = 0.25  # 反発スコアの重み(旧version: 0.5)


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
    except Exception as e:
        print(f"  [警告] {code} {name}: 取得失敗({e})")
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
        return None  # 赤字・データ欠損は除外
    if roe < MIN_ROE_FLOOR:
        return None  # 赤字のみ除外(質は後段でパーセンタイル化して連続的に評価)
    if payout_ratio is not None and payout_ratio > MAX_PAYOUT_RATIO:
        return None  # 減配リスク回避(配当が利益を上回っている)
    if earnings_growth is not None and earnings_growth < MIN_EARNINGS_GROWTH:
        return None  # 「安いだけ」の罠回避(利益が急減している)
    if sector != FINANCIAL_SECTOR and debt_to_equity is not None and debt_to_equity > MAX_DEBT_TO_EQUITY:
        return None  # 過大な借入回避(金融業は業態上対象外)

    return {
        "code": code, "name": name, "per": per, "pbr": pbr,
        "dividend_yield": div_yield, "roe": roe, "price": price,
        "payout_ratio": payout_ratio, "earnings_growth": earnings_growth,
        "debt_to_equity": debt_to_equity, "sector": sector,
    }


def fetch_turnaround_signals(code: str) -> dict | None:
    """直近の値動きから「下げ止まり/反発の兆し」を単純なルールで数値化する。
    将来を予測するモデルではなく、あくまで参考のテクニカルシグナル。"""
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
    decel_pct = (ret_recent - ret_prior) * 100  # プラス=下落が減速/反転している

    rsi14 = _rsi(closes, len(closes) - 1, 14)

    return {
        "code": code, "off_low_pct": off_low_pct, "trend_pct": trend_pct,
        "decel_pct": decel_pct, "rsi14": rsi14,
    }


def percentile_rank(values: list[float], reverse: bool = False) -> list[float]:
    """小さいほど良い指標はreverse=False(順位が高いほど良い)、
    大きいほど良い指標はreverse=Trueで、0〜1のパーセンタイル順位に変換する。"""
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=reverse)
    ranks = [0.0] * len(values)
    n = len(values)
    for rank, idx in enumerate(order):
        ranks[idx] = 1.0 - rank / max(1, n - 1)  # 1.0=最良、0.0=最悪
    return ranks


def run_checkpointed(items, fetch_fn, checkpoint_path, label):
    """1回の実行内でのみ有効なチェックポイント(クラッシュ時の途中結果保全用)。
    成功時は必ず削除するため、翌日の実行に古いキャッシュを持ち越さない。"""
    if os.path.exists(checkpoint_path):
        state = json.load(open(checkpoint_path, encoding="utf-8"))
        print(f"  チェックポイントから再開: {len(state['done_codes'])}銘柄処理済み")
    else:
        state = {"rows": [], "done_codes": []}

    done = set(state["done_codes"])
    todo = [x for x in items if x[0] not in done]
    print(f"{label}: 残り{len(todo)}/{len(items)}銘柄を取得中...")
    for i, (code, name) in enumerate(todo, 1):
        r = fetch_fn(code, name)
        if r:
            state["rows"].append(r)
        state["done_codes"].append(code)
        if i % CHECKPOINT_EVERY == 0:
            json.dump(state, open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  {i}/{len(todo)}件処理済み(有効{len(state['rows'])})...")
        time.sleep(0.1)  # yfinance側への配慮

    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
    return state["rows"]


def main() -> None:
    universe = load_universe()
    print(f"東証プライム、{len(universe)}銘柄のデータを取得中(yfinance)...")
    rows = run_checkpointed(universe, fetch_metrics, "value_metrics_checkpoint.json", "指標取得")

    print(f"\n質フィルター後(赤字のみ除外): {len(rows)}/{len(universe)}銘柄が対象")

    per_scores = percentile_rank([r["per"] for r in rows])       # 低PERほど高得点
    pbr_scores = percentile_rank([r["pbr"] for r in rows])       # 低PBRほど高得点
    div_scores = percentile_rank([r["dividend_yield"] for r in rows], reverse=True)  # 高配当ほど高得点
    roe_scores = percentile_rank([r["roe"] for r in rows], reverse=True)             # 高ROEほど高得点

    for r, ps, bs, ds, qs in zip(rows, per_scores, pbr_scores, div_scores, roe_scores):
        r["cheapness_score"] = round((ps + bs + ds) / 3, 4)
        r["quality_score"] = round(qs, 4)
        r["value_score"] = round((ps + bs + ds + qs) / 4, 4)

    print(f"反発シグナル(価格推移)を取得中... ({len(rows)}銘柄)")
    ta_rows_raw = run_checkpointed(
        [(r["code"], r["code"]) for r in rows], lambda c, _n: fetch_turnaround_signals(c),
        "value_turnaround_checkpoint.json", "反発シグナル取得",
    )
    ta_by_code = {ta["code"]: ta for ta in ta_rows_raw}

    ta_rows = []
    for r in rows:
        ta = ta_by_code.get(r["code"])
        if ta:
            r.update(ta)
            ta_rows.append(r)

    # 既に反発しきった(過熱)銘柄は、ここで完全に対象から除外する
    # (パーセンタイル計算のプールにも入れない。含めると分母が歪むため)
    is_overbought = lambda r: r["rsi14"] is not None and r["rsi14"] >= OVERBOUGHT_RSI
    overbought = [r for r in ta_rows if is_overbought(r)]
    eligible = [r for r in ta_rows if not is_overbought(r)]
    print(f"除外(RSI{OVERBOUGHT_RSI}以上、既に反発しきった可能性): {len(overbought)}銘柄")

    off_low_scores = percentile_rank([r["off_low_pct"] for r in eligible], reverse=True)
    trend_scores = percentile_rank([r["trend_pct"] for r in eligible], reverse=True)
    decel_scores = percentile_rank([r["decel_pct"] for r in eligible], reverse=True)
    for r, o, t, d in zip(eligible, off_low_scores, trend_scores, decel_scores):
        r["turnaround_score"] = round((o + t + d) / 3, 4)
        r["combined_score"] = round(VALUE_WEIGHT * r["value_score"] + TURNAROUND_WEIGHT * r["turnaround_score"], 4)
    print(f"反発シグナル取得できた銘柄: {len(ta_rows)}/{len(rows)}(うちランキング対象{len(eligible)})")

    eligible.sort(key=lambda r: r["combined_score"], reverse=True)
    top50 = eligible[:TOP_N]

    output = {
        "updated": dt.datetime.now().isoformat(timespec="seconds"),
        "universe": "tse_prime",
        "universe_size": len(universe),
        "screened": len(eligible),
        "quality_filter": "PER>0 かつ ROE>=0%(赤字のみ除外、質は連続スコアとしてランキングに反映)、"
                          f"配当性向<={MAX_PAYOUT_RATIO*100:.0f}%(減配リスク回避)、"
                          f"利益成長率>={MIN_EARNINGS_GROWTH*100:.0f}%(急減益は除外)、"
                          f"非金融業は負債比率<={MAX_DEBT_TO_EQUITY}%(過大な借入を除外)、"
                          f"RSI{OVERBOUGHT_RSI}以上は既に反発しきった可能性として除外"
                          f"(今回{len(overbought)}銘柄除外)",
        "method": "割安さ(PER・PBR・配当利回り)と質(ROE)のパーセンタイル平均をvalue_score"
                  f"({VALUE_WEIGHT:.0%})、反発スコア(直近安値からの回復率・短期/長期移動平均"
                  f"トレンド・下落の減速のパーセンタイル平均)を{TURNAROUND_WEIGHT:.0%}で組み合わせた"
                  "総合スコア(0〜1)でランキング。2026-09-19: 日経225→東証プライム全銘柄に拡張、"
                  "質を二値フィルターから連続スコアに変更、反発スコアの比重を50%→25%に低減。",
        "disclaimer": "検証済みの売買シグナルではなく、現時点の割安さ・値動きのスナップショット。"
                      "反発シグナルは将来を予測するものではなく単純なテクニカルルールに基づく参考値。"
                      "売買は自己判断で。",
        "ranking": [
            {
                "rank": i + 1, "code": r["code"], "name": r["name"],
                "price": r["price"], "per": round(r["per"], 2),
                "pbr": round(r["pbr"], 2),
                "dividend_yield_pct": round(r["dividend_yield"], 2),
                "roe_pct": round(r["roe"] * 100, 1),
                "cheapness_score": r["cheapness_score"],
                "quality_score": r["quality_score"],
                "value_score": r["value_score"],
                "turnaround_score": r["turnaround_score"],
                "combined_score": r["combined_score"],
                "rsi14": round(r["rsi14"], 1) if r["rsi14"] is not None else None,
                "off_low_pct": round(r["off_low_pct"], 1),
                "trend_pct": round(r["trend_pct"], 2),
                "payout_ratio_pct": round(r["payout_ratio"] * 100, 1) if r["payout_ratio"] is not None else None,
                "earnings_growth_pct": round(r["earnings_growth"] * 100, 1) if r["earnings_growth"] is not None else None,
                "debt_to_equity": round(r["debt_to_equity"], 1) if r["debt_to_equity"] is not None else None,
                "sector": r["sector"],
            }
            for i, r in enumerate(top50)
        ],
    }

    with open("value_ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 追跡用の履歴に今回のTOP50を追記(1行=1銘柄、run_dateで回を識別)
    run_date = dt.date.today().isoformat()
    with open("value_history.jsonl", "a", encoding="utf-8") as f:
        for item in output["ranking"]:
            f.write(json.dumps({"run_date": run_date, **item}, ensure_ascii=False) + "\n")

    print(f"\n=== 割安株ランキング TOP10(全50件はvalue_ranking.json参照) ===")
    for r in top50[:10]:
        rsi_s = f"{r['rsi14']:.0f}" if r["rsi14"] is not None else "-"
        print(f"  {r['code']} {r['name']:12s} PER{r['per']:.1f} PBR{r['pbr']:.2f} "
              f"配当{r['dividend_yield']:.1f}% ROE{r['roe']*100:.1f}% RSI{rsi_s} "
              f"底値比+{r['off_low_pct']:.1f}% 割安{r['cheapness_score']:.2f} 質{r['quality_score']:.2f} "
              f"反発{r['turnaround_score']:.2f} 総合{r['combined_score']:.3f}")

    print(f"\nvalue_ranking.json に上位50件を出力、value_history.jsonlに追記しました。")


if __name__ == "__main__":
    main()
