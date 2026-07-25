#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ニュース論調フィルター 検証ラボ(EUR/JPY・過去1年)
=====================================================================
※本体(research_agents.py/trading_agents.py)には組み込まない。「試したらどうなるか」の記録。

fx_research_lab.py で EUR/JPY 単独戦略(買い<35/利確>55/損切り5%)がGOと判定された。
値動き(RSI)だけでなく「情報」を監視して反映できないか、という発案を受けて、
GDELT Project(無料・登録不要のニュース論調データベース)から ECB(欧州中央銀行)と
BOJ(日銀)関連ニュースの日次論調(Average Tone)を取得し、単純なフィルターとして
RSI戦略に足したらどう変わるかを見る、最初の一歩の実験。

★重要な前提・割り切り★
 - GDELTの無料APIは過去1年分(timespan=1y)しか遡れない。よって検証期間は約1年のみ。
   1306/FXで行ってきた「10年データ・IS/OOS・ウォークフォワード」のような統計的な
   厳密さは望めない(取引回数が数回〜十数回程度しかない)。ここでの結果は
   「方向性の当たり」を見る参考程度であり、GO/NO-GOの確定判定ではない。
 - "Average Tone"はニュース記事全体の論調スコア(ポジティブ/ネガティブ)であり、
   金融政策のスタンス(タカ派/ハト派)を直接表すものではない。危機報道・災害報道
   なども論調を下げるため、経済的な意味は弱いノイジーな代理指標にすぎない。
 - ここでは「ECB論調 − BOJ論調」を単純な合成スコアとし、直近5日平滑化した値が
   過去1年の下位20%タイル(＝いつもよりかなりネガティブ)のときは新規BUYを見送る、
   という単純な regime filter を試す。理屈: 異常にネガティブな報道が多い日は
   相場が荒れやすく、RSI押し目買いが機能しにくいのでは、という仮説の検証。

使い方:
  python news_sentiment_lab.py
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Optional

import yfinance as yf

from research_agents import ResearchConfig, StrategyParams, MetricsAgent, BacktestResult, _rsi

CFG = ResearchConfig(symbol="EURJPY")
SP = StrategyParams("eurjpy_go", "rsi_only", 0, 0, 14, 75, 35, 55, 0.05, 0.0)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def fetch_gdelt_tone(theme: str) -> dict[str, float]:
    """GDELT DOC 2.0 APIで指定テーマの過去1年・日次平均トーンを取得。
    無料APIはレート制限(429)が厳しいため、一度取れた生レスポンスはディスクに
    キャッシュして使い回す(同じテーマを何度も叩き直さない)。"""
    slug = "".join(c.lower() if c.isalnum() else "_" for c in theme).strip("_")
    cache_path = f"gdelt_cache_{slug}.json"
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        params = {
            "query": f'"{theme}" sourcelang:english',
            "mode": "timelinetone",
            "format": "json",
            "timespan": "1y",
        }
        url = GDELT_URL + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read().decode())
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    series = data["timeline"][0]["data"]
    # 日付キーは "YYYYMMDD" 形式に正規化(yfinanceの日付と突き合わせやすくする)
    return {pt["date"][:8]: pt["value"] for pt in series}


def fetch_eurjpy_prices(years: int = 1) -> tuple[list[str], list[float]]:
    df = yf.Ticker("EURJPY=X").history(period=f"{years}y")
    df = df.dropna(subset=["Close"])
    dates = [d.strftime("%Y%m%d") for d in df.index]
    closes = [float(x) for x in df["Close"].tolist()]
    return dates, closes


def smoothed_net_tone(dates: list[str], ecb: dict[str, float], boj: dict[str, float]) -> list[Optional[float]]:
    """日付ごとに ECB論調-BOJ論調 を計算し、直近5日(過去分のみ)で平滑化する。"""
    raw = []
    for d in dates:
        e, b = ecb.get(d), boj.get(d)
        raw.append(e - b if e is not None and b is not None else None)

    out: list[Optional[float]] = []
    for i in range(len(raw)):
        window = [v for v in raw[max(0, i - 4):i + 1] if v is not None]
        out.append(sum(window) / len(window) if window else None)
    return out


class NewsFilteredBacktester:
    """rsi_onlyロジックはそのまま、追加で『ニュース論調が下位P%のときは新規BUY禁止』を足す。"""

    def __init__(self, cfg: ResearchConfig, veto_threshold: Optional[float]):
        self.cfg = cfg
        self.veto_threshold = veto_threshold  # Noneならフィルターなし(ベースライン)

    def run(self, closes: list[float], tone: list[Optional[float]], sp: StrategyParams) -> BacktestResult:
        c = self.cfg
        cash = float(c.capital_yen)
        shares = 0
        entry = 0.0
        equity_curve, trades = [], []
        fee = (c.commission_bps + c.slippage_bps) / 10000.0

        for i, px in enumerate(closes):
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
                blocked = (self.veto_threshold is not None
                           and tone[i] is not None and tone[i] < self.veto_threshold)
                if not blocked:
                    qty = int(cash // (px * (1 + fee) * c.trade_unit)) * c.trade_unit
                    if qty > 0:
                        cash -= qty * px * (1 + fee)
                        shares, entry = qty, px
                        trades.append({"side": "BUY", "px": px, "qty": qty, "i": i})

            equity_curve.append(cash + shares * px)

        return BacktestResult(equity_curve, trades, equity_curve[-1])


def main() -> None:
    print("取得中: EUR/JPY 直近1年の価格 ...")
    dates, closes = fetch_eurjpy_prices(1)
    print(f"  {len(closes)}本 ({dates[0]} 〜 {dates[-1]})")

    print("取得中: GDELT ECB論調(過去1年) ...")
    ecb = fetch_gdelt_tone("European Central Bank")
    print(f"  {len(ecb)}日分")

    print("待機中(GDELTレート制限対応、20秒)...")
    time.sleep(20)

    print("取得中: GDELT BOJ論調(過去1年) ...")
    boj = fetch_gdelt_tone("Bank of Japan")
    print(f"  {len(boj)}日分")

    tone = smoothed_net_tone(dates, ecb, boj)
    valid_tone = [t for t in tone if t is not None]
    threshold = sorted(valid_tone)[int(len(valid_tone) * 0.20)] if valid_tone else None
    print(f"\n下位20%タイル閾値(ECB-BOJ論調、5日平滑): {threshold:.3f}" if threshold is not None
          else "\n論調データが日付と噛み合わず、閾値を計算できなかった。")

    met = MetricsAgent(CFG)

    base_bt = NewsFilteredBacktester(CFG, veto_threshold=None)
    m_base = met.metrics(base_bt.run(closes, tone, SP))

    print("\n【ベースライン: RSIのみ(ニュースフィルターなし)】")
    print(f"  利益率{m_base['return_pct']:+.1f}% / 最大DD{m_base['max_dd_pct']:.1f}% / "
          f"Sharpe{m_base['sharpe']:.2f} / 取引{m_base['trades']}回 / 勝率{m_base['win_rate']*100:.0f}%")

    if threshold is not None:
        filt_bt = NewsFilteredBacktester(CFG, veto_threshold=threshold)
        m_filt = met.metrics(filt_bt.run(closes, tone, SP))
        print("\n【RSI + ニュース論調フィルター(下位20%タイルの日はBUY見送り)】")
        print(f"  利益率{m_filt['return_pct']:+.1f}% / 最大DD{m_filt['max_dd_pct']:.1f}% / "
              f"Sharpe{m_filt['sharpe']:.2f} / 取引{m_filt['trades']}回 / 勝率{m_filt['win_rate']*100:.0f}%")

    print("\n注意: 検証期間は約1年のみ(GDELT無料APIの制約)、取引回数も少なく統計的信頼性は低い。")
    print("      Average Toneは金融政策スタンスを直接表さない、ノイジーな代理指標。")
    print("      あくまで『方向性の当たり外れ』を見る最初の一歩であり、GO/NO-GOの確定判定ではない。")


if __name__ == "__main__":
    main()
