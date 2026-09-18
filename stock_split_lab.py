#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
株式分割の権利落ち日効果の実証検証(東証プライム全銘柄)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

「特定の日に値動きが起きる」候補調査シリーズ(10個)の#1。株式分割は
最低投資額の引き下げによる新規投資家の参入・流動性向上を通じて、権利落ち後に
株価が上昇するアノマリーとして日本株でも報告されている(ライブドア2003年の
15日連続ストップ高、旧ヤフーの13回の分割等)。yfinanceの`ticker.splits`
(分割実施日そのもの)を使い、東証プライム全銘柄・全期間で検証する。

★先読みバイアスについて★
分割の「発表日」は事前に公表されるため理論上は発表日から売買できるが、
発表日は銘柄ごとに個別取得が必要で本検証では扱わない。ここでは「分割実施日
(権利落ち日)以降に上昇する」という事後ドリフト仮説のみを検証する
(実施日そのものは公表済みの既知の未来日なので、実施日直前に買うことは
理論上可能)。

使い方: python stock_split_lab.py --prime
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import os
import sys
import statistics as pystats

import yfinance as yf

CHECKPOINT_EVERY = 25
WINDOW = 20  # 営業日
RET_CAP = 1.0


def load_universe() -> list[tuple[str, str]]:
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def collect(code: str) -> list[dict]:
    try:
        t = yf.Ticker(f"{code}.T")
        splits = t.splits
        hist = t.history(period="max", interval="1d")
    except Exception:
        return []
    if splits is None or len(splits) == 0 or hist.empty:
        return []
    hist = hist.dropna(subset=["Close"])
    dates = [d.date() for d in hist.index]
    closes = hist["Close"].tolist()
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n = len(dates)

    out = []
    for split_date, ratio in splits.items():
        d = split_date.date()
        idx = date_to_idx.get(d)
        if idx is None:
            for offset in range(1, 4):
                if (d + dt.timedelta(days=offset)) in date_to_idx:
                    idx = date_to_idx[d + dt.timedelta(days=offset)]
                    break
        if idx is None or idx < WINDOW or idx + WINDOW >= n:
            continue
        pre_ret = closes[idx] / closes[idx - WINDOW] - 1
        post_ret = closes[idx + WINDOW] / closes[idx] - 1
        out.append({"code": code, "date": d.isoformat(), "ratio": float(ratio),
                     "pre_ret": pre_ret, "post_ret": post_ret})
    return out


def main() -> None:
    universe = load_universe()
    tag = "prime" if "--prime" in sys.argv else "nikkei225"
    checkpoint_path = f"stock_split_checkpoint_{tag}.json"
    cache_path = f"stock_split_cache_{tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        all_events = json.load(open(cache_path, encoding="utf-8"))
    else:
        if os.path.exists(checkpoint_path):
            saved = json.load(open(checkpoint_path, encoding="utf-8"))
            all_events = saved["events"]
            done_codes = set(saved["done_codes"])
            print(f"チェックポイントから再開: {len(done_codes)}銘柄処理済み")
        else:
            all_events = []
            done_codes = set()

        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{tag}、残り{len(todo)}/{len(universe)}銘柄を処理中...")
        for i, (code, name) in enumerate(todo, 1):
            all_events += collect(code)
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"events": all_events, "done_codes": list(done_codes)},
                          open(checkpoint_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(分割イベント 累計{len(all_events)})...")

        json.dump(all_events, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    print(f"\n合計分割イベント数: {len(all_events)}")

    pre = [e["pre_ret"] for e in all_events if abs(e["pre_ret"]) <= RET_CAP]
    post = [e["post_ret"] for e in all_events if abs(e["post_ret"]) <= RET_CAP]

    def report(label, data):
        if not data:
            print(f"  {label}: サンプル不足")
            return
        win = sum(1 for r in data if r > 0) / len(data) * 100
        print(f"  {label}: 平均={pystats.mean(data)*100:+.2f}%(中央値{pystats.median(data)*100:+.2f}%, "
              f"勝率{win:.1f}%, n={len(data)})")

    print(f"\n=== 分割実施日(権利落ち日)前後{WINDOW}営業日のリターン ===")
    report("実施日までの{}営業日".format(WINDOW), pre)
    report("実施日からの{}営業日".format(WINDOW), post)

    print("\n注意: 東証プライム全銘柄・全期間(yfinance取得可能な範囲)。市場全体の"
          "上昇トレンドとの分離(対^N225超過リターン)は未実施、生の株価リターンのみ。"
          "分割発表日(事前の織り込み)は考慮していない。")


if __name__ == "__main__":
    main()
