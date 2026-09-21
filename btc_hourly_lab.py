#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ビットコイン(BTC/USD、Bitstamp)1時間足の時間帯効果 検証ラボ(バックテストのみ)
=====================================================================
※本体には組み込まない。口座・発注なし。btc_anomaly_reference.md #5の検証。

データ: Bitstamp公開API(認証不要、読み取り専用)の1時間足を2015-01-01から取得し
`btc_bitstamp_1h.csv`にキャッシュ(.gitignore対象・再配布しない。規約確認は
btc_anomaly_reference.md参照)。

検証:
  A. データ品質(欠損)
  B. 24時間帯(UTC)ごとの平均リターン・t値・プラスの年数(24個の同時検定→Bonferroni×24)
  C. **事前に決めた仮説**: 文献(Quantpedia等)が挙げたUTC22〜23時のロング(1日1往復)
     IS/OOS・暦年別・コスト後
  D. IS期間の上位2時間帯を選び直して、OOSで確認(後出し選択の検証)
  E. 「月曜アジア時間オープン効果」: 月曜UTC00〜08時 vs 火〜金の同時間帯

使い方: python btc_hourly_lab.py
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import math
import os
import statistics as pystats
import time
import urllib.request
from collections import defaultdict

CACHE = "btc_bitstamp_1h.csv"
START_TS = int(dt.datetime(2015, 1, 1, tzinfo=dt.timezone.utc).timestamp())
IS_RATIO = 0.65
COST_ONE_WAY = 0.0015  # 片道15bps(手数料10+スリッページ5)
UA = {"User-Agent": "Mozilla/5.0 (research)"}


def fetch_all():
    rows, start = [], START_TS
    now = int(time.time())
    while start < now:
        url = f"https://www.bitstamp.net/api/v2/ohlc/btcusd/?step=3600&limit=1000&start={start}"
        for attempt in range(4):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                    data = json.loads(r.read())["data"]["ohlc"]
                break
            except Exception as e:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        if not data:
            break
        for c in data:
            rows.append((int(c["timestamp"]), float(c["open"]), float(c["high"]),
                         float(c["low"]), float(c["close"]), float(c["volume"])))
        last = int(data[-1]["timestamp"])
        if last + 3600 <= start:
            break
        start = last + 3600
        time.sleep(0.25)
    rows = sorted(set(rows))
    with open(CACHE, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return rows


def load():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return [tuple(float(x) if i else int(x) for i, x in enumerate(r)) for r in csv.reader(f)]
    print("Bitstamp 1時間足を取得中(初回のみ、約130リクエスト)...")
    return fetch_all()


def tstat(xs):
    n = len(xs)
    if n < 3:
        return 0.0
    sd = pystats.stdev(xs)
    return pystats.mean(xs) / (sd / math.sqrt(n)) if sd > 0 else 0.0


def main():
    rows = load()
    # 1時間足の時間帯リターン = close/open - 1
    obs = []  # (datetime, ret)
    for ts, o, h, l, c, v in rows:
        if o > 0:
            obs.append((dt.datetime.fromtimestamp(ts, dt.timezone.utc), c / o - 1))
    print(f"1時間足 {len(obs)}本 / {obs[0][0]:%Y-%m-%d}〜{obs[-1][0]:%Y-%m-%d}")
    span_hours = (obs[-1][0] - obs[0][0]).total_seconds() / 3600
    print(f"欠損率(期間内の本来の本数に対して): {(1 - len(obs) / span_hours) * 100:.1f}%\n")

    split_dt = obs[int(len(obs) * IS_RATIO)][0]
    print(f"IS/OOS分割日: {split_dt:%Y-%m-%d}(前{IS_RATIO:.0%}/後{1-IS_RATIO:.0%})\n")

    by_hour = defaultdict(list)          # h -> [(date, ret)]
    for d, r in obs:
        by_hour[d.hour].append((d, r))

    # ---- B ----
    print("=" * 84)
    print("B. UTC時間帯別の平均リターン(全期間、片道コスト前)  ※24個同時検定→Bonferroni閾値|t|>3.0目安")
    print("=" * 84)
    print(f"{'UTC':>4s} {'平均bps':>8s} {'t値':>6s} {'プラス年':>8s}")
    all_years = sorted({d.year for d, _ in obs})
    for h in range(24):
        rs = [r for _, r in by_hour[h]]
        yr = defaultdict(list)
        for d, r in by_hour[h]:
            yr[d.year].append(r)
        pos = sum(1 for y in yr if pystats.mean(yr[y]) > 0)
        flag = " *" if abs(tstat(rs)) > 3.0 else ""
        print(f"{h:>4d} {pystats.mean(rs)*1e4:>8.2f} {tstat(rs):>6.2f} {pos:>4d}/{len(yr):<3d}{flag}")

    # ---- C ----
    def window_returns(hours, lo, hi):
        """指定時間帯(連続する時間の集合)を1日1往復で保有するときの日次リターン(複利連結)。"""
        byday = defaultdict(float)
        for h in hours:
            for d, r in by_hour[h]:
                if lo <= d < hi:
                    byday[d.date()] = (1 + byday[d.date()]) * (1 + r) - 1 if d.date() in byday else r
        return byday

    def report_hours(label, hours, lo, hi):
        by = window_returns(hours, lo, hi)
        gross = [v for v in by.values()]
        net = [v - 2 * COST_ONE_WAY for v in gross]
        if not gross:
            print(f"  {label}: データなし")
            return
        eq = 1.0
        for v in net:
            eq *= 1 + v
        print(f"  {label}: {len(gross)}日 / 1日あたり グロス{pystats.mean(gross)*1e4:+.1f}bps(t={tstat(gross):+.2f}) "
              f"→ コスト後{pystats.mean(net)*1e4:+.1f}bps(t={tstat(net):+.2f}) / 複利累計(コスト後){(eq-1)*100:+.0f}%")

    t0, t1 = obs[0][0], obs[-1][0] + dt.timedelta(hours=1)
    print("\n" + "=" * 84)
    print("C. 事前仮説: UTC22時・23時のロング(22:00に買い、翌0:00に売る、1日1往復、往復コスト30bps)")
    print("=" * 84)
    report_hours("全期間", [22, 23], t0, t1)
    report_hours("IS    ", [22, 23], t0, split_dt)
    report_hours("OOS   ", [22, 23], split_dt, t1)
    print("  暦年別(グロスbps/日、コスト後bps/日):")
    for y in all_years:
        lo = dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc)
        hi = dt.datetime(y + 1, 1, 1, tzinfo=dt.timezone.utc)
        by = window_returns([22, 23], lo, hi)
        if len(by) >= 100:
            g = pystats.mean(by.values()) * 1e4
            print(f"    {y}: グロス{g:+6.1f} / コスト後{g - 60 * 0.5:+6.1f}  (n={len(by)}日)")

    # ---- D ----
    print("\n" + "=" * 84)
    print("D. IS期間の平均リターン上位2時間帯を選び直し → OOSで確認")
    print("=" * 84)
    is_mean = {h: pystats.mean([r for d, r in by_hour[h] if d < split_dt]) for h in range(24)}
    top2 = sorted(is_mean, key=is_mean.get, reverse=True)[:2]
    print(f"  IS上位2時間帯(UTC): {top2}(IS平均 {[round(is_mean[h]*1e4,2) for h in top2]} bps/時)")
    report_hours("IS ", top2, t0, split_dt)
    report_hours("OOS", top2, split_dt, t1)
    oos_mean = {h: pystats.mean([r for d, r in by_hour[h] if d >= split_dt]) for h in range(24)}
    rank_oos = sorted(oos_mean, key=oos_mean.get, reverse=True)
    print(f"  OOSでのその2時間帯の順位(24中): {[rank_oos.index(h)+1 for h in top2]}")
    common = len(set(sorted(is_mean, key=is_mean.get, reverse=True)[:6]) & set(rank_oos[:6]))
    print(f"  IS上位6とOOS上位6の重なり: {common}/6(偶然なら平均1.5個)")

    # ---- E ----
    print("\n" + "=" * 84)
    print("E. 月曜アジア時間オープン効果: 月曜UTC00〜08時の合計リターン vs 火〜金の同時間帯")
    print("=" * 84)
    daily = defaultdict(float)
    for d, r in obs:
        if d.hour < 8:
            k = d.date()
            daily[k] = (1 + daily[k]) * (1 + r) - 1 if k in daily else r
    mon, other = defaultdict(list), defaultdict(list)
    for day, v in daily.items():
        wd = day.weekday()
        (mon if wd == 0 else other if wd in (1, 2, 3, 4) else defaultdict(list))[day.year].append(v)
    print(f"{'年':>5s} {'月曜bps':>9s} {'火〜金bps':>9s} {'差':>7s}")
    diffs = []
    for y in sorted(mon):
        if len(mon[y]) >= 30 and other[y]:
            m, o = pystats.mean(mon[y]) * 1e4, pystats.mean(other[y]) * 1e4
            diffs.append(m - o)
            print(f"{y:>5d} {m:>9.1f} {o:>9.1f} {m-o:>+7.1f}")
    if len(diffs) > 1:
        print(f"→ 月曜が上回った年 {sum(1 for x in diffs if x > 0)}/{len(diffs)}、年度間t={tstat(diffs):+.2f}")

    print("\n注意: 独立な相場サイクルは3〜4回のみ。24時間帯の総当たり(B)は多重検定で偶然の当たりが出やすい。")


if __name__ == "__main__":
    main()
