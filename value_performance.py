#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
割安株ランキングの追跡成績(仮想ポートフォリオ)
=====================================================================
value_screener.pyが積み上げているvalue_history.jsonl(毎回のTOP50記録)を読み、
「初めて推薦された時点で買って、今まで持っていたら」というシンプルな仮定で
各銘柄の含み損益を計算する。日経225平均(ベンチマーク)とも比較する。

※実際に売買した記録ではない。あくまで「もし買っていたら」の仮想追跡。
  この割安スコア自体がまだ検証されていない(バックテストしていない)ため、
  この追跡結果の蓄積こそが「本当に効果があるのか」の一次データになる。

使い方: python value_performance.py
出力: value_performance.json
"""
from __future__ import annotations
import json
import datetime as dt
import statistics as pystats

import yfinance as yf

BENCHMARK = "^N225"


def load_history() -> list[dict]:
    rows = []
    try:
        with open("value_history.jsonl", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        pass
    return rows


def first_appearances(rows: list[dict]) -> dict[str, dict]:
    """銘柄コードごとに、最初にランクインした回の記録だけを残す。"""
    out: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: x["run_date"]):
        if r["code"] not in out:
            out[r["code"]] = r
    return out


def fetch_current_price(code: str) -> float | None:
    try:
        info = yf.Ticker(f"{code}.T").info
        return info.get("currentPrice") or info.get("regularMarketPrice")
    except Exception:
        return None


def fetch_benchmark_series() -> dict[str, float]:
    """日経225のOHLC(Close)を日付→終値の辞書で返す(直近2年分あれば十分)。"""
    df = yf.Ticker(BENCHMARK).history(period="2y")
    out = {}
    for idx, row in df.iterrows():
        out[idx.strftime("%Y-%m-%d")] = float(row["Close"])
    return out


def nearest_price(series: dict[str, float], target_date: str) -> float | None:
    """target_date以降で最初に見つかる終値(休場日対策、最大7日先まで探す)。"""
    d = dt.date.fromisoformat(target_date)
    for offset in range(8):
        key = (d + dt.timedelta(days=offset)).isoformat()
        if key in series:
            return series[key]
    return None


def main() -> None:
    rows = load_history()
    if not rows:
        print("value_history.jsonl が空です。先に value_screener.py を複数回実行してください。")
        return

    firsts = first_appearances(rows)
    print(f"追跡対象: 延べ{len(rows)}件の記録 / ユニーク銘柄{len(firsts)}件")

    bench_series = fetch_benchmark_series()
    bench_latest = bench_series[max(bench_series)]

    entries = []
    for code, r in firsts.items():
        cur = fetch_current_price(code)
        if cur is None or r.get("price") is None:
            continue
        stock_ret = cur / r["price"] - 1

        bench_entry = nearest_price(bench_series, r["run_date"])
        bench_ret = (bench_latest / bench_entry - 1) if bench_entry else None

        entries.append({
            "code": code, "name": r["name"], "first_run_date": r["run_date"],
            "first_rank": r["rank"], "entry_price": r["price"], "current_price": cur,
            "return_pct": round(stock_ret * 100, 2),
            "benchmark_return_pct": round(bench_ret * 100, 2) if bench_ret is not None else None,
            "excess_return_pct": round((stock_ret - bench_ret) * 100, 2) if bench_ret is not None else None,
            "days_held": (dt.date.today() - dt.date.fromisoformat(r["run_date"])).days,
        })

    if not entries:
        print("価格取得に失敗し、集計できる銘柄がありませんでした。")
        return

    entries.sort(key=lambda e: e["return_pct"], reverse=True)
    rets = [e["return_pct"] for e in entries]
    excess = [e["excess_return_pct"] for e in entries if e["excess_return_pct"] is not None]
    win_rate = sum(1 for r in rets if r > 0) / len(rets)

    summary = {
        "updated": dt.datetime.now().isoformat(timespec="seconds"),
        "tracked_stocks": len(entries),
        "history_runs": len(set(r["run_date"] for r in rows)),
        "oldest_run_date": min(r["run_date"] for r in rows),
        "avg_return_pct": round(pystats.mean(rets), 2),
        "median_return_pct": round(pystats.median(rets), 2),
        "win_rate_pct": round(win_rate * 100, 1),
        "avg_excess_vs_nikkei225_pct": round(pystats.mean(excess), 2) if excess else None,
        "note": "「初めてTOP50に入った時点で買い、今まで持ち続けていたら」という仮想追跡。"
                "実際の売買記録ではなく、割安スコアの有効性を後から検証するための一次データ。",
        "entries": entries,
    }

    with open("value_performance.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n=== 仮想追跡サマリー(蓄積{summary['history_runs']}回分、銘柄{len(entries)}件) ===")
    print(f"平均リターン: {summary['avg_return_pct']:+.2f}% / 中央値: {summary['median_return_pct']:+.2f}% "
          f"/ 勝率: {summary['win_rate_pct']:.1f}%")
    if summary["avg_excess_vs_nikkei225_pct"] is not None:
        print(f"日経225平均に対する超過リターン: {summary['avg_excess_vs_nikkei225_pct']:+.2f}%")
    print("\nvalue_performance.json に出力しました。")


if __name__ == "__main__":
    main()
