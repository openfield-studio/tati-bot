#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
権利付き最終日効果のIS/OOS検証
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

seasonal_effects_lab.py(#23、FACTOR_RESEARCH_LOG.mdリーダーボード1位)で見つかった
権利付き最終日効果(平均+0.833%、勝率68.2%、t=53.1)は、全期間データをそのまま
平均しただけでIS/OOS分割を経ていなかった(SESSION_LOG項目46で指摘済みの留保)。
research_agents.pyと同じ65%/35%の時系列分割の考え方を、複数銘柄にまたがる
イベント日ベースのデータに適用する: 全銘柄・全年の「権利付き最終日」イベントを
日付順に並べ、前65%をIS、残り35%をOOSとして、OOS側でも効果が残るか確認する。

使い方: python rights_day_isoos_lab.py --prime
"""
from __future__ import annotations
import csv
import json
import os
import sys
import statistics as pystats

import yfinance as yf
from scipy import stats

CHECKPOINT_EVERY = 25
RET_CAP = 2.0
IS_RATIO = 0.65
ROUND_TRIP_COST = 0.0016  # 片道8bps(手数料5bps+スリッページ3bps)×2、項目46と同じ前提
N_TRIALS = 69  # FACTOR_RESEARCH_LOG.md 2026-09-18時点の累積試行数


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def analyze_stock(code: str) -> list[dict] | None:
    try:
        ticker = yf.Ticker(f"{code}.T")
        df = ticker.history(period="7y", interval="1d")
        divs = ticker.dividends
    except Exception:
        return None
    df = df.dropna(subset=["Close"])
    if len(df) < 300 or divs is None or len(divs) == 0:
        return None
    closes = df["Close"].tolist()
    dates = [d.date() for d in df.index]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n = len(closes)

    events = []
    for div_date, _ in divs.items():
        d = div_date.date()
        idx = date_to_idx.get(d)
        if idx is None:
            best = None
            for i2, dt2 in enumerate(dates):
                diff = abs((dt2 - d).days)
                if diff <= 3 and (best is None or diff < best[1]):
                    best = (i2, diff)
            idx = best[0] if best else None
        if idx is None or idx < 2 or idx >= n:
            continue
        cum_day_ret = closes[idx - 1] / closes[idx - 2] - 1  # 権利付き最終日の値動き
        cum_day_date = dates[idx - 1]
        events.append({"date": cum_day_date.isoformat(), "code": code, "ret": cum_day_ret})
    return events


def main() -> None:
    universe = load_universe()
    tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"rights_day_isoos_checkpoint_{tag}.json"
    cache_path = f"rights_day_isoos_cache_{tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        state = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            state = json.load(open(checkpoint_path, encoding="utf-8"))
            print(f"チェックポイントから再開: {len(state['done_codes'])}銘柄処理済み")
        else:
            state = {"events": [], "done_codes": [], "processed": 0}

        done_codes = set(state["done_codes"])
        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{tag}、残り{len(todo)}/{len(universe)}銘柄を処理中...")
        for i, (code, name) in enumerate(todo, 1):
            events = analyze_stock(code)
            if events:
                state["events"] += events
                state["processed"] += 1
            state["done_codes"].append(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump(state, open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(有効{state['processed']}、チェックポイント保存)...")

        json.dump(state, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    events = [e for e in state["events"] if abs(e["ret"]) <= RET_CAP]
    events.sort(key=lambda e: e["date"])
    print(f"\n有効銘柄数: {state['processed']}/{len(universe)} / イベント数: {len(events)}\n")

    split = int(len(events) * IS_RATIO)
    cutoff_date = events[split]["date"]
    is_events = [e for e in events if e["date"] < cutoff_date]
    oos_events = [e for e in events if e["date"] >= cutoff_date]

    def report(label: str, evs: list[dict]) -> None:
        rets = [e["ret"] for e in evs]
        if len(rets) < 10:
            print(f"--- {label}: サンプル不足(n={len(rets)}) ---")
            return
        mean = pystats.mean(rets)
        median = pystats.median(rets)
        win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
        t_stat, p_value = stats.ttest_1samp(rets, 0.0)
        p_bonf = min(1.0, p_value * N_TRIALS)
        net = mean - ROUND_TRIP_COST
        dates = sorted(e["date"] for e in evs)
        print(f"--- {label}(n={len(rets)}, 期間{dates[0]}〜{dates[-1]}) ---")
        print(f"  グロス平均{mean*100:+.3f}%(中央値{median*100:+.3f}%, 勝率{win_rate:.1f}%)")
        print(f"  コスト控除後(往復{ROUND_TRIP_COST*100:.2f}%)ネット平均{net*100:+.3f}%")
        print(f"  t統計量={t_stat:+.2f}, 生p値={p_value:.6f}, "
              f"Bonferroni補正後(×N={N_TRIALS})p値={p_bonf:.6f}"
              f"({'有意(5%水準)' if p_bonf < 0.05 else '補正後は非有意'})")

    print("=" * 70)
    print(f"=== 権利付き最終日効果 IS/OOS検証(分割日: {cutoff_date}) ===")
    print("=" * 70)
    report("全期間", events)
    report("IS(学習期間)", is_events)
    report("OOS(検証期間)", oos_events)

    if len(oos_events) >= 10:
        oos_mean = pystats.mean([e["ret"] for e in oos_events])
        if oos_mean - ROUND_TRIP_COST > 0:
            print("\n判定: OOSでもコスト控除後プラスを維持 → GO")
        else:
            print("\n判定: OOSではコスト控除後マイナス、または反転 → NO-GO/要再検討")

    print("\n注意: IS/OOSはイベント日付の時系列分割(前65%/後35%)。パラメータ最適化は"
          "していない(この効果自体に調整可能なパラメータがないため、IS選定→OOS検証という"
          "意味での過剰最適化の余地はもともと小さい)。ここでの目的は『たまたま良い期間を"
          "見ていただけではないか』の確認。")


if __name__ == "__main__":
    main()
