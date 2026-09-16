#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
個別銘柄の割安度(PER/PBR)の予測力チェック(日経225ユニバース)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

value_screener.pyは「今の」PER/PBRしか使えず、個別銘柄の過去のPER/PBRは
遡れないとしてきた(yfinance .infoは現在値のみ)。しかしyfinanceの決算データ
(income_stmt/balance_sheet)にはBasic EPS・自己資本・発行済株式数の
**過去5期分(年次)**が入っている。株価の過去データ(yfinanceで長期間取得可能)と
組み合わせれば、各決算期末時点の擬似PER/PBRを再構築できる。

sector_valuation_backtest.py(業種単位、13年×5業種)とは対照的に、
こちらは「5年×最大225銘柄」の**クロスセクショナル(断面)検証**になる。
期間は短いが、1年ごとに多数の銘柄を比較できるのが強み。

★先読みバイアス対策★
決算期末(3月末等)のPERをそのまま使わず、決算発表までのタイムラグを考慮して
「決算期末+60日後」の株価で擬似PER/PBRを計算する(実際に投資家がその数値を
知り得るタイミングに近づけるため)。

★年ごとの市場全体の値動きの影響を除くため★
各決算年度の中で、PER下位1/3(割安)と上位1/3(割高)にクロスセクショナルに
分け、その後の6ヶ月・12ヶ月リターンを年度ごとに比較してからプールする
(単純に全部プールすると、たまたま良かった年に割安株が多かっただけ、という
交絡が起きるため)。

使い方: python individual_value_backtest.py
"""
from __future__ import annotations
import csv
import json
import os
import sys
import statistics as pystats
from collections import defaultdict

import yfinance as yf

FORWARD_MONTHS = [6, 12]
REPORT_LAG_DAYS = 60  # 決算期末から、市場に情報が織り込まれるまでの猶予


def load_universe() -> list[tuple[str, str]]:
    """デフォルトは日経225。 `python individual_value_backtest.py --prime` で
    東証プライム全銘柄(tse_prime_universe.csv、fetch_tse_universe.pyで生成)を使う。"""
    if "--prime" in sys.argv:
        with open("tse_prime_universe.csv", encoding="utf-8-sig") as f:
            return [(row["code"], row["name"]) for row in csv.DictReader(f)]
    from value_screener import NIKKEI225
    return NIKKEI225


def to_price_map(hist) -> dict:
    return {idx.date(): float(row["Close"]) for idx, row in hist.iterrows()}


def nearest_price(price_map: dict, target_date):
    """target_date以降で最初に見つかる終値(最大10日先まで探索)。"""
    import datetime as dt
    for offset in range(10):
        d = (target_date + dt.timedelta(days=offset)).date()
        if d in price_map:
            return price_map[d]
    return None


def collect_observations(code: str) -> list[dict]:
    import datetime as dt
    try:
        t = yf.Ticker(f"{code}.T")
        inc = t.income_stmt
        bs = t.balance_sheet
        hist = t.history(period="7y")
    except Exception:
        return []
    if inc is None or bs is None or hist.empty:
        return []
    if "Basic EPS" not in inc.index or "Stockholders Equity" not in bs.index \
            or "Ordinary Shares Number" not in bs.index:
        return []
    price_map = to_price_map(hist)

    out = []
    for fye in inc.columns:
        try:
            eps = inc.loc["Basic EPS", fye]
            equity = bs.loc["Stockholders Equity", fye] if fye in bs.columns else None
            shares = bs.loc["Ordinary Shares Number", fye] if fye in bs.columns else None
        except KeyError:
            continue
        if eps is None or equity is None or shares is None or shares == 0:
            continue
        if not (eps == eps) or eps <= 0:  # NaN/赤字は除外
            continue
        bps = equity / shares
        if bps <= 0:
            continue

        reveal_date = fye.to_pydatetime() + dt.timedelta(days=REPORT_LAG_DAYS)
        price0 = nearest_price(price_map, reveal_date)
        if price0 is None:
            continue
        per = price0 / eps
        pbr = price0 / bps
        if per <= 0 or per > 200:  # 異常値除外
            continue

        rets = {}
        for m in FORWARD_MONTHS:
            target = reveal_date + dt.timedelta(days=int(m * 30.4))
            p1 = nearest_price(price_map, target)
            rets[m] = (p1 / price0 - 1) if p1 else None

        out.append({
            "code": code, "fiscal_year": fye.year, "per": per, "pbr": pbr,
            "reveal_date": reveal_date.date().isoformat(), **{f"ret{m}": rets[m] for m in FORWARD_MONTHS},
        })
    return out


CHECKPOINT_EVERY = 25  # 前回の東証プライム全銘柄検証がメモリ不足で全損した反省から、
                        # 一定件数ごとに逐次保存する(academic_factors_lab.pyと同じ方式)


def main() -> None:
    universe = load_universe()
    universe_tag = "prime" if "--prime" in sys.argv else "nikkei225"
    cache_path = f"individual_value_backtest_cache_{universe_tag}.json"
    progress_path = f"individual_value_backtest_progress_{universe_tag}.json"

    if os.path.exists(cache_path):
        print(f"完成済みキャッシュ({cache_path})から読み込み中...")
        all_obs = json.load(open(cache_path, encoding="utf-8"))
    else:
        done_codes = set()
        all_obs = []
        if os.path.exists(progress_path):
            saved = json.load(open(progress_path, encoding="utf-8"))
            all_obs = saved["observations"]
            done_codes = set(saved["done_codes"])
            print(f"途中経過({progress_path})から再開: {len(done_codes)}銘柄処理済み、"
                  f"観測数 累計{len(all_obs)}")

        todo = [(code, name) for code, name in universe if code not in done_codes]
        print(f"{universe_tag}、残り{len(todo)}/{len(universe)}銘柄の決算データ+株価を取得中"
              f"(数が多いので時間がかかります)...")
        for i, (code, name) in enumerate(todo, 1):
            obs = collect_observations(code)
            all_obs += obs
            done_codes.add(code)
            if i % CHECKPOINT_EVERY == 0:
                json.dump({"observations": all_obs, "done_codes": list(done_codes)},
                          open(progress_path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  {i}/{len(todo)}件処理済み(観測数 累計{len(all_obs)}、"
                      f"チェックポイント保存)...")
        json.dump(all_obs, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
        if os.path.exists(progress_path):
            os.remove(progress_path)  # 完成したので途中経過ファイルは不要

    print(f"\n合計観測数(銘柄×決算年度): {len(all_obs)}")
    years = sorted(set(o["fiscal_year"] for o in all_obs))
    print(f"対象年度: {years}\n")

    print("=== 年度ごとのクロスセクショナル検証(PER下位1/3 vs 上位1/3) ===")
    pooled_low = defaultdict(list)
    pooled_high = defaultdict(list)
    for year in years:
        yr_obs = [o for o in all_obs if o["fiscal_year"] == year]
        yr_obs_sorted = sorted(yr_obs, key=lambda o: o["per"])
        n = len(yr_obs_sorted)
        tercile = n // 3
        if tercile < 5:
            continue
        low = yr_obs_sorted[:tercile]
        high = yr_obs_sorted[-tercile:]
        print(f"\n[{year}年度] 対象{n}銘柄(割安側{len(low)} / 割高側{len(high)})")
        for m in FORWARD_MONTHS:
            low_r = [o[f"ret{m}"] for o in low if o[f"ret{m}"] is not None]
            high_r = [o[f"ret{m}"] for o in high if o[f"ret{m}"] is not None]
            if low_r:
                pooled_low[m] += low_r
            if high_r:
                pooled_high[m] += high_r
            if low_r and high_r:
                print(f"  {m}ヶ月後: 割安平均={pystats.mean(low_r)*100:+.1f}%(n={len(low_r)}) / "
                      f"割高平均={pystats.mean(high_r)*100:+.1f}%(n={len(high_r)})")

    print("\n=== 全年度プール(年度内で相対比較した後にまとめた場合) ===")
    for m in FORWARD_MONTHS:
        lo, hi = pooled_low[m], pooled_high[m]
        if lo and hi:
            diff = (pystats.mean(lo) - pystats.mean(hi)) * 100
            print(f"{m}ヶ月後: 割安平均={pystats.mean(lo)*100:+.1f}%(中央値{pystats.median(lo)*100:+.1f}%, n={len(lo)}) / "
                  f"割高平均={pystats.mean(hi)*100:+.1f}%(中央値{pystats.median(hi)*100:+.1f}%, n={len(hi)}) / "
                  f"平均の差={diff:+.1f}pt")

    print("\n=== 外れ値チェック: 割安側でPERが極端に低い(<5)観測 ===")
    extreme = sorted([o for o in all_obs if o["per"] < 5], key=lambda o: o["per"])
    for o in extreme[:15]:
        print(f"  {o['code']} FY{o['fiscal_year']} PER={o['per']:.2f} "
              f"6mo={o.get('ret6')} 12mo={o.get('ret12')}")
    print(f"  該当件数: {len(extreme)}")

    print("\n=== 極端なリターン(|r|>200%)を除外した再集計 ===")
    CAP = 2.0
    for m in FORWARD_MONTHS:
        lo = [r for r in pooled_low[m] if abs(r) <= CAP]
        hi = [r for r in pooled_high[m] if abs(r) <= CAP]
        n_removed_lo = len(pooled_low[m]) - len(lo)
        n_removed_hi = len(pooled_high[m]) - len(hi)
        if lo and hi:
            diff = (pystats.mean(lo) - pystats.mean(hi)) * 100
            print(f"{m}ヶ月後: 割安平均={pystats.mean(lo)*100:+.1f}%(n={len(lo)}, 除外{n_removed_lo}件) / "
                  f"割高平均={pystats.mean(hi)*100:+.1f}%(n={len(hi)}, 除外{n_removed_hi}件) / "
                  f"平均の差={diff:+.1f}pt")

    print("\n注意: 決算発表タイミングの近似(+60日)・生存バイアス(現在の日経225構成銘柄のみ、"
          "当時225から外れていた/上場していなかった銘柄は含まれない)に留意。")


if __name__ == "__main__":
    main()
