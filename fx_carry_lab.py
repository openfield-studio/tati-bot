#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX(EUR/JPY) スワップポイント(金利差)検証ラボ
=====================================================================
※本体(research_agents.py/trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

fx_execution_lag_lab.py で EUR/JPY戦略(買い<35/利確>55/損切り5%)がGOと判定され、
翌日約定ズレを織り込んでもプラス維持を確認した。ただし「スワップポイント(金利差
コスト/収益)は未検証」という宿題が残っていた。

news_sentiment_lab.py でニュース論調を試したが、GDELT無料APIは実質1年分しか
遡れず統計的に無意味だった(取引3回)。今回は代わりに FRED(セントルイス連銀・
無料・登録不要のCSVエンドポイント)から実際の政策金利を取得し、10年フルの
バックテスト期間をカバーしてスワップの影響を検証する。

★モデル化の割り切り★
 - 長期(ロング)ポジションを保有している間、日々「EUR金利 − JPY金利」の金利差
   (年率)を日割りでキャッシュに加減する近似で、スワップポイントを模擬する。
   実際のFX会社のスワップは金利差そのままではなく、業者のマージンが乗るため
   これでもなお楽観的な近似(業者マージン分は無視)。
 - ECB預金ファシリティ金利(日次、1999年〜): FRED "ECBDFR"
 - 日本の短期金利(月次、1985年〜): FRED "IRSTCI01JPM156N"
   月次データは月内の日に forward-fill して日次化する(政策金利は元々
   会合ごとにしか動かないので、この近似の誤差は小さい)。

使い方:
  python fx_carry_lab.py
"""
from __future__ import annotations

import csv
import io
import urllib.request

from research_agents import ResearchConfig, StrategyParams, MetricsAgent, BacktestResult, _rsi

CFG = ResearchConfig(symbol="EURJPY")
SP = StrategyParams("eurjpy_go", "rsi_only", 0, 0, 14, 75, 35, 55, 0.05, 0.0)

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


def fetch_fred_csv(series_id: str, cache_path: str) -> dict[str, float]:
    """FRED の無料CSVエンドポイント(キー不要)から系列を取得しキャッシュする。
    戻り値: {"YYYY-MM-DD": 値} (欠損は "." で表現されるため除外)"""
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
    next(reader)  # header
    for row in reader:
        if len(row) != 2 or row[1] == ".":
            continue
        out[row[0]] = float(row[1])
    return out


def fetch_eurjpy_prices(years: int) -> tuple[list[str], list[float]]:
    import yfinance as yf
    df = yf.Ticker("EURJPY=X").history(period=f"{years}y")
    df = df.dropna(subset=["Close"])
    dates = [d.strftime("%Y-%m-%d") for d in df.index]
    closes = [float(x) for x in df["Close"].tolist()]
    return dates, closes


def build_daily_carry(dates: list[str], ecb_daily: dict[str, float],
                       jpy_monthly: dict[str, float]) -> list[float]:
    """日付ごとに (ECB金利 − JPY金利) を年率%で求め、日割りの比率(小数)に変換する。
    ECBは日次forward-fill、JPYは月次値を月内forward-fillして揃える。"""
    ecb_sorted = sorted(ecb_daily.items())
    jpy_sorted = sorted(jpy_monthly.items())

    def last_value_on_or_before(sorted_items: list[tuple[str, float]], date: str) -> float:
        lo, hi, ans = 0, len(sorted_items) - 1, sorted_items[0][1]
        while lo <= hi:
            mid = (lo + hi) // 2
            if sorted_items[mid][0] <= date:
                ans = sorted_items[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        return ans

    carry = []
    for d in dates:
        ecb = last_value_on_or_before(ecb_sorted, d)
        jpy_month_key = d[:7] + "-01"
        jpy = last_value_on_or_before(jpy_sorted, jpy_month_key)
        diff_annual_pct = ecb - jpy
        carry.append(diff_annual_pct / 100 / 365)
    return carry


class CarryAdjustedBacktester:
    """rsi_onlyロジックは同じ、ロング保有中は日々スワップ(金利差)をキャッシュに反映する。"""

    def __init__(self, cfg: ResearchConfig, carry_daily: list[float], apply_carry: bool):
        self.cfg = cfg
        self.carry_daily = carry_daily
        self.apply_carry = apply_carry

    def run(self, closes: list[float], sp: StrategyParams) -> BacktestResult:
        c = self.cfg
        cash = float(c.capital_yen)
        shares = 0
        entry = 0.0
        equity_curve, trades = [], []
        fee = (c.commission_bps + c.slippage_bps) / 10000.0

        for i, px in enumerate(closes):
            if self.apply_carry and shares > 0:
                cash += shares * px * self.carry_daily[i]

            rsi = _rsi(closes, i, sp.rsi_period)
            if shares > 0:
                if px <= entry * (1 - sp.stop_loss_pct):
                    cash += shares * px * (1 - fee)
                    trades.append({"side": "SELL", "px": px, "qty": shares, "i": i})
                    shares, entry = 0, 0.0
                elif rsi is not None and rsi >= sp.rsi_exit:
                    cash += shares * px * (1 - fee)
                    trades.append({"side": "SELL", "px": px, "qty": shares, "i": i})
                    shares, entry = 0, 0.0
            elif rsi is not None and rsi < sp.rsi_oversold:
                qty = int(cash // (px * (1 + fee) * c.trade_unit)) * c.trade_unit
                if qty > 0:
                    cash -= qty * px * (1 + fee)
                    shares, entry = qty, px
                    trades.append({"side": "BUY", "px": px, "qty": qty, "i": i})

            equity_curve.append(cash + shares * px)

        return BacktestResult(equity_curve, trades, equity_curve[-1])


def report(name: str, m: dict) -> None:
    print(f"  [{name:<10}] 利益率{m['return_pct']:+7.1f}% / 最大DD{m['max_dd_pct']:5.1f}% / "
          f"Sharpe{m['sharpe']:5.2f} / 取引{m['trades']:3d}回 / 勝率{m['win_rate']*100:4.0f}%")


def main() -> None:
    print("取得中: EUR/JPY 直近10年の価格 ...")
    dates, closes = fetch_eurjpy_prices(10)
    print(f"  {len(closes)}本 ({dates[0]} 〜 {dates[-1]})")

    print("取得中: FRED ECB預金ファシリティ金利(日次) ...")
    ecb = fetch_fred_csv("ECBDFR", "fred_cache_ecbdfr.csv")
    print(f"  {len(ecb)}日分 ({min(ecb)} 〜 {max(ecb)})")

    print("取得中: FRED 日本短期金利(月次) ...")
    jpy = fetch_fred_csv("IRSTCI01JPM156N", "fred_cache_jp_rate.csv")
    print(f"  {len(jpy)}か月分 ({min(jpy)} 〜 {max(jpy)})")

    carry = build_daily_carry(dates, ecb, jpy)
    avg_diff_pct = sum(carry) / len(carry) * 365 * 100
    print(f"\n期間平均の金利差(EUR-JPY、年率): {avg_diff_pct:+.2f}%pt")

    split = int(len(closes) * CFG.is_ratio)
    periods = {
        "全期間": (0, len(closes)),
        "IS": (0, split),
        "OOS": (split, len(closes)),
    }

    met = MetricsAgent(CFG)
    no_carry_bt = CarryAdjustedBacktester(CFG, carry, apply_carry=False)
    carry_bt = CarryAdjustedBacktester(CFG, carry, apply_carry=True)

    print("\n=== スワップ未考慮(これまでの結果と同条件) ===")
    base_metrics = {}
    for label, (s, e) in periods.items():
        sub_closes = closes[s:e]
        m = met.metrics(no_carry_bt.run(sub_closes, SP))
        base_metrics[label] = m
        report(label, m)

    print("\n=== スワップ考慮(ECB-JPY金利差を日割りで反映) ===")
    carry_metrics = {}
    for label, (s, e) in periods.items():
        sub_closes = closes[s:e]
        sub_carry = carry[s:e]
        bt = CarryAdjustedBacktester(CFG, sub_carry, apply_carry=True)
        m = met.metrics(bt.run(sub_closes, SP))
        carry_metrics[label] = m
        report(label, m)

    print("\n=== 差分(スワップ考慮 − 未考慮) ===")
    for label in periods:
        d_ret = carry_metrics[label]["return_pct"] - base_metrics[label]["return_pct"]
        print(f"  [{label:<10}] 利益率差分 {d_ret:+.1f}pt")

    oos_carry = carry_metrics["OOS"]
    verdict = "GO" if oos_carry["return_pct"] > 0 and oos_carry["sharpe"] > 0 else "要再検討"
    print(f"\n=== 結論 ===")
    print(f"OOSでスワップを考慮しても利益率{oos_carry['return_pct']:+.1f}% / "
          f"Sharpe{oos_carry['sharpe']:.2f} → {verdict}")
    print("※ 金利差はECB預金ファシリティ金利と日本の短期金利の単純差。実際のFX会社の")
    print("  スワップはこれに業者マージンが乗るため、これでもなお楽観的な近似。")


if __name__ == "__main__":
    main()
