#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX 最終チェック(翌営業日約定ズレ + スワップポイント 同時考慮)
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

fx_execution_lag_lab.py(約定ズレ)と fx_carry_lab.py(スワップ/金利差)を
それぞれ単独で検証したが、実運用では両方が同時にかかる。この2つを同時に
織り込んだ、最も実運用に近い最終チェックを行う。

対象は2通貨:
 - EUR/JPY: fx_research_lab.pyでGO判定(買い<35/利確>55/損切り5%)
 - USD/JPY: fx_research_lab.pyでNO-GO判定(買い<30/利確>55/損切り5%)。
   NO-GOだった戦略にキャリー(金利差)の追い風を足しても結論が変わらないかを
   念のため確認する(USDはドル金利がJPYよりかなり高く保たれてきたため、
   EUR以上にキャリーの影響が大きい可能性がある)。

金利データ(FRED、無料・キー不要):
 - EUR: ECBDFR(ECB預金ファシリティ金利、日次)
 - USD: DFF(FF金利、日次)
 - JPY: IRSTCI01JPM156N(日本の短期金利、月次→日割りforward-fill)

使い方:
  python fx_final_check_lab.py
"""
from __future__ import annotations

import csv
import io
import json
import urllib.request

import yfinance as yf

from research_agents import ResearchConfig, StrategyParams, MetricsAgent, BacktestResult, _rsi

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def fetch_fred_csv(series_id: str, cache_path: str) -> dict[str, float]:
    try:
        with open(cache_path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        with urllib.request.urlopen(FRED_URL.format(series_id=series_id), timeout=30) as r:
            text = r.read().decode()
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)

    out = {}
    reader = csv.reader(io.StringIO(text))
    next(reader)
    for row in reader:
        if len(row) != 2 or not row[1] or row[1] == ".":
            continue
        out[row[0]] = float(row[1])
    return out


def fetch_open_close(pair: str, years: int = 10) -> tuple[list[str], list[float], list[float]]:
    ticker = f"{pair}=X"
    df = yf.Ticker(ticker).history(period=f"{years}y")
    df = df.dropna(subset=["Open", "Close"])
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    opens = [float(x) for x in df["Open"].tolist()]
    closes = [float(x) for x in df["Close"].tolist()]
    return dates, opens, closes


def _last_on_or_before(sorted_items, date):
    lo, hi, ans = 0, len(sorted_items) - 1, sorted_items[0][1]
    while lo <= hi:
        mid = (lo + hi) // 2
        if sorted_items[mid][0] <= date:
            ans = sorted_items[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def build_daily_carry(dates: list[str], base_rate: dict[str, float], base_monthly: bool,
                       quote_rate_monthly: dict[str, float]) -> list[float]:
    """base通貨金利 − quote(JPY)金利 の日割り比率(小数)。
    月次系列は当月1日キーで forward-fill する。"""
    base_sorted = sorted(base_rate.items())
    quote_sorted = sorted(quote_rate_monthly.items())

    carry = []
    for d in dates:
        base_key = d[:7] + "-01" if base_monthly else d
        b = _last_on_or_before(base_sorted, base_key)
        q = _last_on_or_before(quote_sorted, d[:7] + "-01")
        carry.append((b - q) / 100 / 365)
    return carry


class FinalBacktester:
    """約定は翌営業日始値、判定は当日終値RSI、保有中は日々スワップを反映する
    (execution_lag_labとcarry_labの合成)。"""

    def __init__(self, cfg: ResearchConfig, carry_daily: list[float]):
        self.cfg = cfg
        self.carry_daily = carry_daily

    def run(self, opens: list[float], closes: list[float], sp: StrategyParams) -> BacktestResult:
        c = self.cfg
        cash = float(c.capital_yen)
        shares = 0
        entry = 0.0
        equity_curve, trades = [], []
        fee = (c.commission_bps + c.slippage_bps) / 10000.0
        pending = None

        for i in range(len(closes)):
            if pending == "BUY" and shares == 0:
                px = opens[i]
                qty = int(cash // (px * (1 + fee) * c.trade_unit)) * c.trade_unit
                if qty > 0:
                    cash -= qty * px * (1 + fee)
                    shares, entry = qty, px
                    trades.append({"side": "BUY", "px": px, "qty": qty, "i": i})
            elif pending == "SELL" and shares > 0:
                px = opens[i]
                cash += shares * px * (1 - fee)
                trades.append({"side": "SELL", "px": px, "qty": shares, "i": i})
                shares, entry = 0, 0.0
            pending = None

            if shares > 0:
                cash += shares * closes[i] * self.carry_daily[i]

            close_px = closes[i]
            rsi = _rsi(closes, i, sp.rsi_period)
            if shares > 0:
                if close_px <= entry * (1 - sp.stop_loss_pct):
                    pending = "SELL"
                elif rsi is not None and rsi >= sp.rsi_exit:
                    pending = "SELL"
            elif rsi is not None and rsi < sp.rsi_oversold:
                pending = "BUY"

            equity_curve.append(cash + shares * close_px)

        return BacktestResult(equity_curve, trades, equity_curve[-1])


def report(name: str, m: dict) -> None:
    print(f"  [{name:<10}] 利益率{m['return_pct']:+7.1f}% / 最大DD{m['max_dd_pct']:5.1f}% / "
          f"Sharpe{m['sharpe']:5.2f} / 取引{m['trades']:3d}回 / 勝率{m['win_rate']*100:4.0f}%")


def check_pair(pair: str, base_rate_series: str, base_cache: str, base_monthly: bool = False) -> None:
    with open(f"research_result_{pair.lower()}.json", encoding="utf-8") as f:
        res = json.load(f)
    sp_dict = res["strategy"]
    sp = StrategyParams(**{**sp_dict, "name": f"{pair}_final"})
    print(f"\n########## {pair} (研究チーム判定: {res['verdict']}) ##########")
    print(f"戦略: 買い<{sp.rsi_oversold:.0f} 利確>{sp.rsi_exit:.0f} 損切り{sp.stop_loss_pct*100:.0f}%")

    cfg = ResearchConfig(symbol=pair)
    dates, opens, closes = fetch_open_close(pair, years=10)
    print(f"価格データ: {len(closes)}本 ({dates[0]} 〜 {dates[-1]})")

    base_rate = fetch_fred_csv(base_rate_series, base_cache)
    jpy_rate = fetch_fred_csv("IRSTCI01JPM156N", "fred_cache_jp_rate.csv")
    carry = build_daily_carry(dates, base_rate, base_monthly, jpy_rate)
    avg_diff = sum(carry) / len(carry) * 365 * 100
    print(f"期間平均金利差(対JPY、年率): {avg_diff:+.2f}%pt")

    split = int(len(closes) * cfg.is_ratio)
    periods = {"全期間": (0, len(closes)), "IS": (0, split), "OOS": (split, len(closes))}

    met = MetricsAgent(cfg)
    bt = FinalBacktester(cfg, carry)

    print("最終チェック(翌日約定ズレ + スワップ 同時考慮):")
    for label, (s, e) in periods.items():
        m = met.metrics(bt.run(opens[s:e], closes[s:e], sp))
        report(label, m)
        if label == "OOS":
            verdict = "GO" if m["return_pct"] > 0 and m["sharpe"] > 0 else "NO-GO寄り"
            print(f"  → OOS最終結論: {verdict}")


def main() -> None:
    check_pair("EURJPY", "ECBDFR", "fred_cache_ecbdfr.csv")
    check_pair("USDJPY", "DFF", "fred_cache_dff.csv")
    check_pair("GBPJPY", "IUDSOIA", "fred_cache_gbp.csv")
    check_pair("AUDJPY", "IRSTCI01AUM156N", "fred_cache_aud.csv", base_monthly=True)
    check_pair("NZDJPY", "IR3TIB01NZM156N", "fred_cache_nzd.csv", base_monthly=True)


if __name__ == "__main__":
    main()
