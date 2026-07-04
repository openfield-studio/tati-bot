#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yfinance で長期(5年など)の調整後終値を取得し、
研究チームが読むキャッシュ prices_<code>.csv を上書きするスクリプト。

狙い:
  無料プランのJ-Quantsは2年分しか取れず、検証期間(OOS)で取引が
  成立しない壁にぶつかった。yfinanceなら5年でも10年でも無料で取れる。
  これで「長期データならOOSの壁を越えられるか」をタダで確認する。

準備(君のPCで一度だけ):
  pip install yfinance

使い方:
  python fetch_yf.py 1306 5      # 1306を5年分
  python fetch_yf.py 1306 10     # 10年分にしたい時
  → prices_1306.csv が出来る/上書きされる
  → そのあと  python research_agents.py  を実行すれば5年データで検証

注意:
  - yfinanceは非公式(Yahoo!ファイナンス)。たまに仕様変更で止まることがある。
    あくまで「研究の下調べ」用途。本番執行は立花APIなので問題なし。
  - 東証銘柄のティッカーは "コード.T"（例: 1306.T）。
  - auto_adjust=True で分割・配当調整済みの終値を使う(検証の連続性のため)。
"""

from __future__ import annotations
import sys


def fetch_and_cache(code: str, years: int = 5) -> None:
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance が未インストール。先に:  pip install yfinance")
        sys.exit(1)

    ticker = f"{code}.T"           # 東証
    print(f"取得中: {ticker} / 直近{years}年 ...")

    df = yf.Ticker(ticker).history(period=f"{years}y", auto_adjust=True)
    if df is None or df.empty:
        print(f"データが取れなかった: {ticker}。コードや期間を確認。")
        sys.exit(1)

    closes = [float(x) for x in df["Close"].dropna().tolist()]
    if not closes:
        print("終値が空だった。")
        sys.exit(1)

    # ★安全装置★ 分割の断崖チェック（auto_adjustがYahoo側で効いてない事故対策）
    # 1日で±30%超の変化は相場ではなく分割とみなし、それ以前を係数で調整する。
    # (2026年の1306で実際に発生: 1:10分割が未調整のまま届き、ニセの-90%が混入した)
    fixes = []
    for i in range(1, len(closes)):
        r = closes[i] / closes[i - 1]
        if r < 0.7:                      # 例: 1:10分割なら r≒0.1
            factor = round(1 / r)
            if factor >= 2:
                for k in range(i):
                    closes[k] /= factor
                fixes.append((i, f"1:{factor}分割"))
        elif r > 1.4:                    # 逆併合(例: 10:1)のケース
            factor = round(r)
            if factor >= 2:
                for k in range(i):
                    closes[k] *= factor
                fixes.append((i, f"{factor}:1併合"))
    if fixes:
        print(f"⚠ 分割/併合の断崖を検出→自動修復した: {fixes}")
        worst = max(abs(closes[i]/closes[i-1]-1) for i in range(1, len(closes)))
        print(f"  修復後の最大日次変動: {worst*100:.1f}%（10%前後までなら正常）")

    path = f"prices_{code}.csv"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(str(round(c, 2)) for c in closes))

    print(f"完了: {path} に {len(closes)}本 書き込み "
          f"(最古 {closes[0]:.1f} → 最新 {closes[-1]:.1f})")
    print("次:  python research_agents.py  を実行（自動でこのキャッシュを読む）")


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "1306"
    years = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    fetch_and_cache(code, years)
