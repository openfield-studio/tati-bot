#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fx_lab.py — FX(USD/JPY)で同じRSI逆張り戦略を検証する実験室
================================================================
1306で採用した「純RSI逆張り」を、為替(USD/JPY)にそのまま適用したら
どうなるかを、同じ検証パイプライン(IS/OOS + ウォークフォワード)で試す。

★重要な前提★
  レバレッジ1倍で計算する(現物の1306と同じ土俵で比較するため)。
  国内FX会社は個人で最大25倍まで使えるが、レバレッジを上げると
  損益も同じ倍率で拡大するだけなので、まずは「土台の戦略に優位性が
  あるか」を1倍で確認するのが先。倍率の話はそのあと。

★このスクリプトが検証しないもの★
  - スワップポイント(通貨間の金利差による日々のコスト/収益)は含めていない。
    実際のFX取引にはこれが乗る。円安・円高局面や政策金利差で符号が変わるため、
    ここでは意図的に含めず「価格変動だけでの優位性」を見る。
  - 1306と違い、為替はスプレッド(売値と買値の差)が主なコスト。
    ここでは簡易的に commission_bps/slippage_bps を流用している。

使い方(君のPCで):
  pip install yfinance          (未インストールなら)
  python fx_lab.py               USD/JPYの10年データを取得して検証
  python fx_lab.py EURJPY 10      他通貨ペアや年数も指定可能

同じフォルダに research_agents.py が必要(Backtester等を再利用するため)。
"""
from __future__ import annotations
import sys

sys.path.insert(0, ".")
from research_agents import Backtester, MetricsAgent, StrategyParams, ResearchConfig


def fetch_fx(pair: str, years: int) -> list[float]:
    """yfinanceでFXレートを取得。USDJPY等は '通貨ペア=X' の形式。"""
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance が未インストール。先に:  pip install yfinance")
        sys.exit(1)

    ticker = f"{pair}=X"
    print(f"取得中: {ticker} / 直近{years}年 ...")
    df = yf.Ticker(ticker).history(period=f"{years}y")
    if df is None or df.empty:
        print(f"データが取れなかった: {ticker}。通貨ペア表記を確認(例: USDJPY, EURJPY)。")
        sys.exit(1)

    closes = [float(x) for x in df["Close"].dropna().tolist()]
    print(f"取得完了: {len(closes)}本 (最古 {closes[0]:.2f} → 最新 {closes[-1]:.2f})")
    return closes


def sp(oversold: float, exit_: float, stop: float) -> StrategyParams:
    return StrategyParams("fx", "rsi_only", 0, 0, 14, 75, oversold, exit_, stop, 0.0)


def main() -> None:
    pair = sys.argv[1] if len(sys.argv) > 1 else "USDJPY"
    years = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    prices = fetch_fx(pair, years)
    n = len(prices)

    # 1306と同じコスト構造・資金設定を使い回す(レバレッジ1倍=trade_unitの概念は不要)
    cfg = ResearchConfig()
    bt = Backtester(cfg)
    met = MetricsAgent(cfg)

    split = int(n * 0.65)
    print(f"\n=== {pair} 全期間 (IS {split}本 + OOS {n - split}本) ===\n")

    print("【1306で採用した設定そのまま試す】")
    candidates = [(35, 50, 0.05), (40, 50, 0.08)]
    for ov, ex, stop in candidates:
        m_full = met.metrics(bt.run(prices, sp(ov, ex, stop)))
        m_is = met.metrics(bt.run(prices[:split], sp(ov, ex, stop)))
        m_oos = met.metrics(bt.run(prices[split:], sp(ov, ex, stop)))
        print(f"  <{ov}/>{ex} 損切{stop*100:.0f}%: "
              f"全期間{m_full['return_pct']:+7.1f}% (DD{m_full['max_dd_pct']:.1f}%) / "
              f"IS{m_is['return_pct']:+7.1f}% / OOS{m_oos['return_pct']:+7.1f}% "
              f"/ 取引{m_full['trades']}回")

    print("\n【ウォークフォワード検証】(区切りを4パターンずらす、<40/50/損切8%で実施)")
    bounds = [int(n * r) for r in (0.50, 0.625, 0.75, 0.875)] + [n]
    folds = []
    for k in range(4):
        seg = prices[bounds[k]:bounds[k + 1]]
        if len(seg) < 60:
            continue
        m = met.metrics(bt.run(seg, sp(40, 50, 0.08)))
        folds.append(m["return_pct"])
        print(f"  区間{k+1}: {m['return_pct']:+7.1f}%  (取引{m['trades']}回)")
    positive = sum(1 for f in folds if f > 0)
    print(f"  → {positive}/{len(folds)} 区間プラス")

    print("\n【簡易パラメータ感度マップ】(全期間・利益率%)")
    exits = [45, 50, 55]
    print("        exit:" + "".join(f"{e:>7}" for e in exits))
    for ov in (25, 30, 35, 40, 45):
        row = [met.metrics(bt.run(prices, sp(ov, e, 0.08)))["return_pct"] for e in exits]
        print(f"  買い<{ov:2d}    " + "".join(f"{r:+7.0f}" for r in row))

    print("\n注意: スワップポイント・実際のスプレッドは未考慮。")
    print("      レバレッジは1倍(現物同等)で計算。25倍等にすると損益もDDも同倍率で拡大する。")
    print("      1306で効いたパラメータが為替でも効くとは限らない─これはあくまで最初の下調べ。")


if __name__ == "__main__":
    main()
