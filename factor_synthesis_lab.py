#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ファクター研究の横断的考察(77試行の俯瞰)
=====================================================================
※本体には組み込まない。既存キャッシュの再分析のみ(新規データ取得なし)。

個別に検証してきた財務ファクターを銘柄×年度で結合し、次の問いに答える:
  A. 年度ごとの再現性: プールしたt値ではなく「1年度=1観測」として数えた
     Fama-MacBeth型のt値で見ると、各ファクターはどれだけ頑健か
  B. バリュー系・質系ファクター同士の相関(年度内スピアマン相関の平均)
  C. 質・安全性系ファクターの逆転は「割安さ(B/M)の裏返し」に過ぎないのか
     (B/Mで層別したダブルソート、B/Mを同時投入した年度別回帰)
  D. バリュー系ファクターの競争(同時投入回帰で独立した予測力が残るのはどれか)
  E. 東証の「PBR1倍割れ改善要請」(2023年3月)との関係
  F. 権利付き最終日効果のイベント日クラスタリング(同じ日に大量の銘柄が
     集中するため、イベント数ではなく日付数で数え直す)

使い方: python factor_synthesis_lab.py
"""
from __future__ import annotations
import json
import math
import statistics as pystats
from collections import defaultdict

import numpy as np
from scipy import stats

RET_CAP = 2.0
MIN_COHORT = 100


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["observations"] if isinstance(d, dict) else d


def build_panel() -> list[dict]:
    master = {(o["code"], o["fiscal_year"]): dict(o) for o in load("fund5_cache_prime.json")}
    extra = [
        ("fund2_cache_prime.json", ["cf_yield", "ev_ebitda", "div_yield", "qmj", "distress_score", "sales_growth"],
         {"roic": "roic_op"}),
        ("fund3_cache_prime.json", ["size", "ncav", "noa", "margin_change", "div_change", "fscore"], {}),
        ("fund4_cache_prime.json", ["roa", "interest_coverage", "fcf_debt", "buyback_amount", "eff_tax_rate",
                                    "ppe_intensity", "wc_efficiency", "pension_underfunding"], {}),
        ("new_factors_cache_prime.json", ["gross_profitability", "accruals", "asset_growth"], {}),
        ("nsi_cache_prime.json", ["net_share_issuance"], {}),
    ]
    for path, keys, renames in extra:
        for o in load(path):
            m = master.get((o["code"], o["fiscal_year"]))
            if m is None:
                continue
            for k in keys:
                if k in o:
                    m[k] = o[k]
            for src, dst in renames.items():
                if src in o:
                    m[dst] = o[src]

    panel = []
    for o in master.values():
        r = o.get("ret12")
        if r is None or abs(r) > RET_CAP:
            continue
        s = {"code": o["code"], "cohort": o["fiscal_year"], "ret12": r}
        # 符号を揃える: すべて「値が大きいほど仮説上は良い」向きにする
        def put(name, val):
            if val is not None and isinstance(val, (int, float)) and math.isfinite(val):
                s[name] = val
        put("B/M", o.get("book_to_market"))
        put("EBIT/EV", o.get("earnings_yield"))
        put("配当利回り", o.get("div_yield"))
        ev_ebitda = o.get("ev_ebitda")
        put("EBITDA/EV", 1 / ev_ebitda if ev_ebitda else None)
        put("CF/P", o.get("cf_yield"))
        put("ネットネット", o.get("ncav"))
        put("粗利益収益性", o.get("gross_profitability"))
        put("営業CF/総資産", o.get("cfo_ta"))
        put("ROIC", o.get("roic_op"))
        put("ROA", o.get("roa"))
        put("Fスコア", o.get("fscore"))
        put("QMJ", o.get("qmj"))
        put("-アクルーアル", -o["accruals"] if o.get("accruals") is not None else None)
        put("-資産成長", -o["asset_growth"] if o.get("asset_growth") is not None else None)
        put("-Oスコア", -o["distress_score"] if o.get("distress_score") is not None else None)
        put("ICR", o.get("interest_coverage"))
        put("FCF/負債", o.get("fcf_debt"))
        put("-小型(=-時価総額)", -o["size"] if o.get("size") is not None else None)
        put("-のれん", -o["goodwill_intensity"] if o.get("goodwill_intensity") is not None else None)
        put("自社株買い", o.get("buyback_amount"))
        put("-純株式発行", -o["net_share_issuance"] if o.get("net_share_issuance") is not None else None)
        put("増配", o.get("div_change"))
        put("粗利益率改善", o.get("margin_change"))
        panel.append(s)
    return panel


def pct_rank(values: list[float]) -> list[float]:
    ranks = stats.rankdata(values)
    n = len(values)
    return [(r - 0.5) / n for r in ranks]


def cohorts(panel):
    by = defaultdict(list)
    for s in panel:
        by[s["cohort"]].append(s)
    return {c: rows for c, rows in sorted(by.items()) if len(rows) >= MIN_COHORT}


def tercile_spread(rows, key):
    rs = [s for s in rows if key in s]
    if len(rs) < 30:
        return None, 0
    rs.sort(key=lambda s: s[key])
    t = len(rs) // 3
    lo = [s["ret12"] for s in rs[:t]]
    hi = [s["ret12"] for s in rs[-t:]]
    return (pystats.mean(hi) - pystats.mean(lo)) * 100, len(rs)


def fm_summary(per_cohort: dict) -> str:
    vals = [v for v in per_cohort.values() if v is not None]
    if len(vals) < 2:
        return "年度数不足"
    mean = pystats.mean(vals)
    sd = pystats.stdev(vals)
    t = mean / (sd / math.sqrt(len(vals))) if sd > 0 else float("inf")
    pos = sum(1 for v in vals if v > 0)
    return f"平均{mean:+6.1f}pt  年度間t={t:+5.2f}  プラス{pos}/{len(vals)}年度"


def section_a(panel, factor_names):
    print("=" * 78)
    print("A. 年度ごとの再現性(三分位スプレッド: 上位1/3 - 下位1/3、12ヶ月後、pt)")
    print("   ※「1年度=1観測」で数えたt値。5%有意の目安は4年度なら|t|>3.18(自由度3)、3年度なら|t|>4.30")
    print("=" * 78)
    cs = cohorts(panel)
    print("年度(=決算期の年)と銘柄数: " + ", ".join(f"{c}:{len(r)}" for c, r in cs.items()))
    rows_out = []
    for f in factor_names:
        per = {}
        for c, rows in cs.items():
            sp, n = tercile_spread(rows, f)
            if n >= MIN_COHORT:
                per[c] = sp
        rows_out.append((f, per))
    for f, per in rows_out:
        detail = "  ".join(f"{c}:{v:+6.1f}" for c, v in per.items())
        print(f"  {f:14s} {fm_summary(per)}   [{detail}]")
    print()


def cohort_corr(panel, names):
    cs = cohorts(panel)
    mats = []
    for c, rows in cs.items():
        m = np.full((len(names), len(names)), np.nan)
        for i, a in enumerate(names):
            for j, b in enumerate(names):
                pair = [(s[a], s[b]) for s in rows if a in s and b in s]
                if len(pair) >= 50:
                    rho, _ = stats.spearmanr([p[0] for p in pair], [p[1] for p in pair])
                    m[i, j] = rho
        mats.append(m)
    return np.nanmean(np.stack(mats), axis=0)


def section_b(panel, names):
    print("=" * 78)
    print("B. 年度内スピアマン相関の平均(符号は「大きいほど仮説上良い」に統一済み)")
    print("=" * 78)
    avg = cohort_corr(panel, names)
    short = [n[:6] for n in names]
    print(" " * 14 + " ".join(f"{s:>7s}" for s in short))
    for i, n in enumerate(names):
        print(f"  {n[:12]:12s}" + " ".join(f"{avg[i, j]:+7.2f}" if not np.isnan(avg[i, j]) else "    nan"
                                        for j in range(len(names))))
    print()
    return avg


def fm_regression(panel, regressors):
    """年度ごとに ret12 を各変数のパーセンタイル順位(0〜1)に回帰。係数=最下位→最上位でのリターン差(pt)。"""
    cs = cohorts(panel)
    coefs = defaultdict(dict)
    ns = {}
    for c, rows in cs.items():
        rs = [s for s in rows if all(k in s for k in regressors)]
        if len(rs) < MIN_COHORT:
            continue
        X = np.column_stack([np.ones(len(rs))] + [pct_rank([s[k] for s in rs]) for k in regressors])
        y = np.array([s["ret12"] for s in rs]) * 100
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        for k, b in zip(regressors, beta[1:]):
            coefs[k][c] = b
        ns[c] = len(rs)
    return coefs, ns


def section_c(panel, quality):
    print("=" * 78)
    print("C. 質・安全性系の「逆転」はB/M(割安さ)の裏返しか?")
    print("   単独: その変数だけの年度別回帰 / B/M統制後: B/Mと同時投入した時の係数")
    print("   ダブルソート: 各年度・B/M三分位の中で質の三分位スプレッドを取り平均")
    print("=" * 78)
    cs = cohorts(panel)
    for q in quality:
        solo, _ = fm_regression(panel, [q])
        ctrl, ns = fm_regression(panel, ["B/M", q])
        ds = {}
        for c, rows in cs.items():
            rs = [s for s in rows if "B/M" in s and q in s]
            if len(rs) < MIN_COHORT:
                continue
            rs.sort(key=lambda s: s["B/M"])
            t = len(rs) // 3
            spreads = []
            for grp in (rs[:t], rs[t:2 * t], rs[2 * t:]):
                sp, n = tercile_spread(grp, q)
                if sp is not None:
                    spreads.append(sp)
            if spreads:
                ds[c] = pystats.mean(spreads)
        print(f"  {q:12s} 単独: {fm_summary(solo[q])}")
        print(f"  {'':12s} B/M統制後: {fm_summary(ctrl[q])}   (同時投入時のB/M係数 {fm_summary(ctrl['B/M'])})")
        print(f"  {'':12s} ダブルソート: {fm_summary(ds)}")
    print()


def section_d(panel, value_set):
    print("=" * 78)
    print("D. バリュー系の競争(全変数を同時投入した年度別回帰、係数=順位最下位→最上位の差pt)")
    print("=" * 78)
    for combo in value_set:
        coefs, ns = fm_regression(panel, combo)
        print(f"  投入変数: {', '.join(combo)}   (年度別n: {', '.join(f'{c}:{n}' for c, n in ns.items())})")
        for k in combo:
            detail = "  ".join(f"{c}:{v:+6.1f}" for c, v in coefs[k].items())
            print(f"    {k:12s} {fm_summary(coefs[k])}   [{detail}]")
        print()


def section_e(panel):
    print("=" * 78)
    print("E. 東証『PBR1倍割れ改善要請』(2023年3月末)との関係")
    print("=" * 78)
    cs = cohorts(panel)
    for c, rows in cs.items():
        rs = [s for s in rows if "B/M" in s]
        below = [s["ret12"] for s in rs if s["B/M"] > 1.0]   # PBR<1
        above = [s["ret12"] for s in rs if s["B/M"] <= 1.0]  # PBR>=1
        deep = [s["ret12"] for s in rs if s["B/M"] > 2.0]    # PBR<0.5
        within_below = tercile_spread([s for s in rs if s["B/M"] > 1.0], "B/M")[0]
        within_above = tercile_spread([s for s in rs if s["B/M"] <= 1.0], "B/M")[0]
        print(f"  {c}年度: PBR<1 {pystats.mean(below)*100:+6.1f}%(n={len(below)}) / "
              f"PBR≥1 {pystats.mean(above)*100:+6.1f}%(n={len(above)}) / "
              f"差{(pystats.mean(below)-pystats.mean(above))*100:+6.1f}pt / "
              f"PBR<0.5 {pystats.mean(deep)*100:+6.1f}%(n={len(deep)})")
        print(f"          PBR<1群の内部でのB/M三分位差 {within_below:+6.1f}pt / "
              f"PBR≥1群の内部 {within_above:+6.1f}pt")
    print()


def section_f():
    print("=" * 78)
    print("F. 権利付き最終日効果: イベント数ではなく『日付』単位で数え直す")
    print("=" * 78)
    d = json.load(open("rights_day_isoos_cache_prime.json", encoding="utf-8"))
    events = [e for e in d["events"] if abs(e["ret"]) <= RET_CAP]
    by_date = defaultdict(list)
    for e in events:
        by_date[e["date"]].append(e["ret"])
    dates = sorted(by_date)
    sizes = sorted((len(v) for v in by_date.values()), reverse=True)
    top10_share = sum(sizes[:10]) / len(events) * 100
    print(f"  イベント数 {len(events)} / 異なる日付数 {len(dates)} / "
          f"上位10日付に全イベントの{top10_share:.1f}%が集中")
    big = [(dt_, by_date[dt_]) for dt_ in dates if len(by_date[dt_]) >= 30]
    print(f"  30銘柄以上が集中した日付: {len(big)}日")
    for dt_, rets in big:
        print(f"    {dt_}: n={len(rets):4d} 平均{pystats.mean(rets)*100:+.2f}% 勝率"
              f"{sum(1 for r in rets if r > 0)/len(rets)*100:4.1f}%")
    date_means = [pystats.mean(by_date[dt_]) for dt_ in dates if len(by_date[dt_]) >= 5]
    t, p = stats.ttest_1samp(date_means, 0.0)
    pos = sum(1 for m in date_means if m > 0)
    print(f"  日付単位(5銘柄以上の日付{len(date_means)}日)の平均 {pystats.mean(date_means)*100:+.3f}% / "
          f"t={t:+.2f} p={p:.4g} / プラスの日付 {pos}/{len(date_means)}")
    big_means = [pystats.mean(r) for _, r in big]
    if len(big_means) >= 3:
        t2, p2 = stats.ttest_1samp(big_means, 0.0)
        print(f"  集中日(30銘柄以上)のみ: {len(big_means)}日 平均{pystats.mean(big_means)*100:+.3f}% / "
              f"t={t2:+.2f} p={p2:.4g} / プラス {sum(1 for m in big_means if m > 0)}/{len(big_means)}")
    # 市場全体の上昇日との区別: 同じ日の1306の値動きを差し引いた超過リターンで見る
    try:
        import yfinance as yf
        h = yf.Ticker("1306.T").history(period="8y")
        closes = {i.date().isoformat(): float(r["Close"]) for i, r in h.iterrows()}
        keys = sorted(closes)
        mret = {keys[i]: closes[keys[i]] / closes[keys[i - 1]] - 1 for i in range(1, len(keys))}
        # 2026-03-30の1306分割がYahoo側で未調整(-90%→+948%)のため、異常な1日変動は除外
        mret = {k: v for k, v in mret.items() if abs(v) <= 0.15}
        ex = [(pystats.mean(r) - mret[dt_]) for dt_, r in big if dt_ in mret]
        mk = [mret[dt_] for dt_, r in big if dt_ in mret]
        if len(ex) >= 3:
            t3, p3 = stats.ttest_1samp(ex, 0.0)
            print(f"  集中日の1306(TOPIX)自体の値動き 平均{pystats.mean(mk)*100:+.3f}% / "
                  f"対TOPIX超過 平均{pystats.mean(ex)*100:+.3f}% t={t3:+.2f} p={p3:.4g} "
                  f"プラス{sum(1 for x in ex if x > 0)}/{len(ex)}")
        big_dates = {dt_ for dt_, _ in big}
        other = [v for k, v in mret.items() if k not in big_dates and k >= dates[0]]
        t4, p4 = stats.ttest_ind(mk, other, equal_var=False)
        print(f"  TOPIX: 集中日 平均{pystats.mean(mk)*100:+.3f}%(n={len(mk)}) vs それ以外の日 "
              f"平均{pystats.mean(other)*100:+.3f}%(n={len(other)}) / t={t4:+.2f} p={p4:.4g}")
        for label, cond in [("3月", lambda d_: d_[5:7] == "03"), ("9月", lambda d_: d_[5:7] == "09"),
                            ("3・9月以外", lambda d_: d_[5:7] not in ("03", "09"))]:
            sub = [(pystats.mean(r) - mret[dt_]) for dt_, r in big if dt_ in mret and cond(dt_)]
            if len(sub) >= 3:
                ts, ps = stats.ttest_1samp(sub, 0.0)
                print(f"    {label}: 対TOPIX超過 平均{pystats.mean(sub)*100:+.3f}%(日付{len(sub)}) "
                      f"t={ts:+.2f} p={ps:.3g} プラス{sum(1 for x in sub if x > 0)}/{len(sub)}")
        cut = "2024-03-27"  # rights_day_isoos_lab.pyと同じ分割日
        for label, cond in [("IS(〜2024-03)", lambda d_: d_ < cut), ("OOS(2024-03〜)", lambda d_: d_ >= cut)]:
            sub = [(pystats.mean(r) - mret[dt_]) for dt_, r in big if dt_ in mret and cond(dt_)]
            raw = [pystats.mean(r) for dt_, r in big if cond(dt_)]
            ts, ps = stats.ttest_1samp(sub, 0.0)
            print(f"    {label}: 生リターン(日付平均) {pystats.mean(raw)*100:+.3f}% / 対TOPIX超過 "
                  f"{pystats.mean(sub)*100:+.3f}%(日付{len(sub)}) t={ts:+.2f} p={ps:.3g}")
    except Exception as e:
        print(f"  (1306取得失敗: {e})")
    print()


def main():
    panel = build_panel()
    print(f"結合パネル: {len(panel)}観測(ret12あり、|ret|<=200%)\n")

    all_factors = ["B/M", "EBIT/EV", "配当利回り", "EBITDA/EV", "CF/P", "ネットネット",
                   "粗利益収益性", "営業CF/総資産", "ROIC", "ROA", "Fスコア", "QMJ",
                   "-アクルーアル", "-資産成長", "-Oスコア", "ICR", "FCF/負債",
                   "-小型(=-時価総額)", "-のれん", "自社株買い", "-純株式発行", "増配", "粗利益率改善"]
    section_a(panel, all_factors)
    section_b(panel, ["B/M", "EBIT/EV", "配当利回り", "EBITDA/EV", "CF/P", "ネットネット",
                      "粗利益収益性", "営業CF/総資産", "ROIC", "ROA", "-アクルーアル", "-資産成長",
                      "-小型(=-時価総額)"])
    section_c(panel, ["粗利益収益性", "営業CF/総資産", "ROIC", "ROA", "QMJ", "Fスコア", "ICR",
                      "FCF/負債", "-アクルーアル", "-Oスコア"])
    section_d(panel, [
        ["B/M", "EBIT/EV", "配当利回り", "CF/P"],
        ["B/M", "EBIT/EV", "配当利回り", "CF/P", "ネットネット"],
        ["B/M", "粗利益収益性", "-資産成長", "-小型(=-時価総額)"],
        ["B/M", "配当利回り", "-資産成長", "-のれん", "自社株買い"],
    ])
    section_e(panel)
    section_f()


if __name__ == "__main__":
    main()
