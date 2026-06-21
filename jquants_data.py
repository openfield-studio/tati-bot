#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J-Quants 実データ取得モジュール（V2 API対応版）
================================================
研究チーム(research_agents.py)の load_prices() を、合成データから
本物の過去株価に差し替えるための部品。

★2025/12/22以降に登録した人は「V2 API」★
 認証方式が「メール/パスワード→トークン」から「APIキー方式」に変わった。
 ダッシュボードで発行したAPIキーを x-api-key ヘッダーで使う。

使い方（君のPCで）:
    1) J-Quants ダッシュボード → [API Keys] で「API Keyを発行」して値をコピー
    2) 環境変数にセット:
         set JQUANTS_API_KEY=コピーしたキー        (Windows)
         export JQUANTS_API_KEY=コピーしたキー      (Mac/Linux)
    3) research_agents.py の load_prices を ↓ で置き換え:
         from jquants_data import load_prices_jquants as load_prices

★無料プランの重要な制約★
 - データは「12週間遅延」で配信される。＝昨日の終値は取れない。
   でもバックテスト（過去の検証）には全く問題ない。
 - レートリミットは 5リクエスト/分（Free）。1銘柄なら余裕。

★分割調整について★
 1306などは過去に株式分割している。素の終値(C)を使うと分割日に
 「見かけの暴落」が出て検証が壊れる。だから必ず調整後終値(AdjC)を使う。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request
import urllib.parse

BASE = "https://api.jquants.com/v2"


# ----------------------------------------------------------------------
# 低レベル: HTTP GET（標準ライブラリのみ。追加インストール不要）
# ----------------------------------------------------------------------
def _get(url: str, headers: dict, params: dict) -> dict:
    url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


# ----------------------------------------------------------------------
# 日足取得（V2: /equities/bars/daily・ページネーション対応）
# ----------------------------------------------------------------------
def fetch_daily_closes(code: str, api_key: str,
                       date_from: str, date_to: str) -> list[float]:
    headers = {"x-api-key": api_key}
    rows: list[dict] = []
    pagination_key = None
    while True:
        params = {"code": code, "from": date_from, "to": date_to}
        if pagination_key:
            params["pagination_key"] = pagination_key
        resp = _get(f"{BASE}/equities/bars/daily", headers, params)
        rows.extend(resp.get("data", []))
        pagination_key = resp.get("pagination_key")
        if not pagination_key:
            break
    return _to_close_series(rows)


def _to_close_series(rows: list[dict]) -> list[float]:
    """日付順にソートし、調整後終値(AdjC)のリストを返す。
    欠損(None)は直前値で埋める。"""
    rows = sorted(rows, key=lambda x: x.get("Date", ""))
    out: list[float] = []
    for row in rows:
        px = row.get("AdjC")          # V2: 調整後終値
        if px is None:
            px = row.get("C")         # 念のため素の終値で代替
        if px is None:
            if out:
                px = out[-1]          # 欠損は直前値で補完
            else:
                continue
        out.append(float(px))
    return out


# ----------------------------------------------------------------------
# キャッシュ付きの公開関数（研究チームの load_prices と差し替え可能）
# ----------------------------------------------------------------------
def load_prices_jquants(symbol: str, n: int = 1500,
                        years: int = 2, cache: bool = True) -> list[float]:
    """research_agents.py の load_prices と同じシグネチャ。
    直近 years 年ぶんを取得し、終値リストを返す（末尾 n 本に切り詰め）。
    ※無料プランは直近約2年分のみ提供（それ以前は契約範囲外で取得不可）。"""
    cache_path = f"prices_{symbol}.csv"
    if cache and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            series = [float(line.strip()) for line in f if line.strip()]
        if series:
            return series[-n:]

    api_key = os.environ.get("JQUANTS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "JQUANTS_API_KEY が未設定。J-Quantsダッシュボードの[API Keys]で"
            "キーを発行し、環境変数 JQUANTS_API_KEY にセットしてください。")

    # 無料プランは12週間遅延＆直近約2年分のみ。
    # to=約90日前 / from=約2年前 に収めて契約範囲内で取得する。
    today = dt.date.today()
    date_to = (today - dt.timedelta(days=90)).isoformat()
    date_from = (today - dt.timedelta(days=365 * years + 30)).isoformat()

    series = fetch_daily_closes(symbol, api_key, date_from, date_to)

    # 4桁で取れなければ5桁コード(末尾0)で再試行（J-Quantsの内部コード対策）
    if not series and len(symbol) == 4 and symbol.isdigit():
        series = fetch_daily_closes(symbol + "0", api_key, date_from, date_to)

    if not series:
        raise RuntimeError(
            f"{symbol} の株価が取得できなかった。コード/期間/プラン範囲を確認。")

    if cache:
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write("\n".join(str(p) for p in series))

    return series[-n:]


if __name__ == "__main__":
    # 君のPCでの動作確認用:
    #   set JQUANTS_API_KEY=...  &&  python jquants_data.py 1306
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "1306"
    prices = load_prices_jquants(code)
    print(f"{code}: {len(prices)}本 取得 / "
          f"最古 {prices[0]:.1f} → 最新 {prices[-1]:.1f}")
