#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
割安株スクリーナー(日経225ユニバース)
=====================================================================
tati-botの拡張機能。日経225構成銘柄(225社)を対象に、PER・PBR・配当利回りが
魅力的で、かつ利益が出ている(質フィルター)銘柄を上位50件ランキングする。

※これはtrading_agents.py/research_agents.pyのRSI逆張り戦略とは別物で、
  「今の割安さのスナップショット」を見せるだけの参考情報。自動売買はしない
  (実際の売買は本人が手動で判断・執行する)。バックテストによる将来予測の
  検証はしていないので、「検証済みのGO戦略」と同列に扱わないこと。

スコアの考え方:
  - 割安スコア: 低PER(実績PER)・低PBR(実績PBR)・高配当利回りを、それぞれ質フィルター
    通過銘柄内でのパーセンタイル順位に変換し、単純平均する。
  - 質フィルター: 赤字(PER<=0またはNone)・ROEが極端に低い(<3%)銘柄は
    「安いだけの罠(バリュートラップ)」の可能性が高いため除外する。
  - 反発スコア(2026-09-16追加): 「割安なだけで下げ続けている銘柄」を避けるため、
    ①直近60営業日安値からの回復率、②短期(25日)/長期(75日)移動平均のトレンド、
    ③直近1ヶ月と前1ヶ月のリターンの差(下落の減速/反転)、の3つをパーセンタイル化して
    平均する。RSI(research_agents.pyと同じ計算式)も参考値として併記する。
    ★これは将来を予測するモデルではなく、単純なテクニカルルールに基づく参考シグナル。
    バックテスト検証はしていない(割安スコア同様、value_performance.pyでの追跡対象)。
  - 総合スコア = (割安スコア + 反発スコア) / 2 で最終ランキングする。

データ取得元: yfinance の Ticker.info(PER/PBR/配当利回り/ROE)と
  Ticker.history(価格推移、反発スコア用)。J-Quantsより単純だが、
  値の欠損・精度はyfinance側の仕様に依存する点に注意。

使い方: python value_screener.py
出力: value_ranking.json (dashboard.htmlが読む想定、.gitignore対象にはしない
      ―― state.json同様、金額情報を含まない銘柄横断の一般的な市況データのため)
"""
from __future__ import annotations
import json
import time
import datetime as dt

import yfinance as yf

from research_agents import _rsi

# 日経225構成銘柄(2026年9月時点、日経平均プロフィル準拠)
NIKKEI225 = [
    ("1332", "ニッスイ"), ("1605", "ＩＮＰＥＸ"), ("1721", "コムシスＨＤ"),
    ("1801", "大成建"), ("1802", "大林組"), ("1803", "清水建"), ("1808", "長谷工"),
    ("1812", "鹿島"), ("1925", "大和ハウス"), ("1928", "積水ハウス"),
    ("1963", "日揮ＨＤ"), ("2002", "日清粉Ｇ"), ("2269", "明治ＨＤ"),
    ("2282", "日本ハム"), ("2413", "エムスリー"), ("2432", "ＤｅＮＡ"),
    ("2501", "サッポロビー"), ("2502", "アサヒ"), ("2503", "キリンＨＤ"),
    ("2768", "双日"), ("2801", "キッコーマン"), ("2802", "味の素"),
    ("285A", "キオクシアＨＤ"), ("2871", "ニチレイ"), ("2914", "ＪＴ"),
    ("3086", "Ｊフロント"), ("3092", "ＺＯＺＯ"), ("3099", "ミツコシイセタン"),
    ("3289", "東急不ＨＤ"), ("3382", "７＆Ｉ－ＨＤ"), ("3401", "帝人"),
    ("3402", "東レ"), ("3405", "クラレ"), ("3407", "旭化成"), ("3436", "ＳＵＭＣＯ"),
    ("3659", "ネクソン"), ("3697", "ＳＨＩＦＴ"), ("3861", "王子ＨＤ"),
    ("4004", "レゾナックＨＤ"), ("4005", "住友化"), ("4021", "日産化"),
    ("4042", "東ソー"), ("4043", "トクヤマ"), ("4061", "デンカ"), ("4062", "イビデン"),
    ("4063", "信越化"), ("4151", "協和キリン"), ("4183", "三井化学"),
    ("4188", "三菱ケミＧ"), ("4208", "ＵＢＥ"), ("4307", "ＮＲＩ"),
    ("4324", "電通Ｇ"), ("4385", "メルカリ"), ("4452", "花王"), ("4502", "武田"),
    ("4503", "アステラス薬"), ("4506", "住友ファーマ"), ("4507", "塩野義"),
    ("4519", "中外薬"), ("4523", "エーザイ"), ("4543", "テルモ"),
    ("4568", "第一三共"), ("4578", "大塚ＨＤ"), ("4661", "ＯＬＣ"),
    ("4689", "ＬＩＮＥヤフー"), ("4704", "トレンド"), ("4751", "サイバエージ"),
    ("4755", "楽天Ｇ"), ("4901", "富士フイルム"), ("4902", "コニカミノルタ"),
    ("4911", "資生堂"), ("5019", "出光興産"), ("5020", "ＥＮＥＯＳ"),
    ("5101", "浜ゴム"), ("5108", "ブリヂストン"), ("5201", "ＡＧＣ"),
    ("5214", "日電硝"), ("5233", "太平洋セメ"), ("5301", "東海カーボ"),
    ("5332", "ＴＯＴＯ"), ("5333", "ＮＧＫ"), ("5401", "日本製鉄"),
    ("5406", "神戸鋼"), ("5411", "ＪＦＥ"), ("543A", "ＡＲＣＨＩＯＮ"),
    ("5631", "日製鋼"), ("5706", "三井金属"), ("5711", "三菱マ"),
    ("5713", "住友鉱"), ("5714", "ＤＯＷＡ"), ("5801", "古河電"),
    ("5802", "住友電"), ("5803", "フジクラ"), ("5831", "しずおか"),
    ("6098", "リクルートＨＤ"), ("6103", "オークマ"), ("6113", "アマダ"),
    ("6146", "ディスコ"), ("6178", "日本郵政"), ("6273", "ＳＭＣ"),
    ("6301", "コマツ"), ("6302", "住友重"), ("6305", "日立建"), ("6326", "クボタ"),
    ("6361", "荏原"), ("6367", "ダイキン"), ("6471", "日精工"), ("6472", "ＮＴＮ"),
    ("6473", "ジェイテクト"), ("6479", "ミネベアミツミ"), ("6501", "日立"),
    ("6503", "三菱電"), ("6504", "富士電機"), ("6506", "安川電"),
    ("6526", "ソシオネクスト"), ("6532", "ベイカレント"), ("6645", "オムロン"),
    ("6701", "ＮＥＣ"), ("6702", "富士通"), ("6723", "ルネサス"),
    ("6724", "エプソン"), ("6752", "パナソニックＨ"), ("6753", "シャープ"),
    ("6758", "ソニーＧ"), ("6762", "ＴＤＫ"), ("6770", "アルプスアル"),
    ("6841", "横河電"), ("6857", "アドバンテ"), ("6861", "キーエンス"),
    ("6902", "デンソー"), ("6920", "レーザーテク"), ("6954", "ファナック"),
    ("6963", "ローム"), ("6971", "京セラ"), ("6976", "太陽誘電"),
    ("6981", "村田製"), ("6988", "日東電"), ("7004", "カナデビア"),
    ("7011", "三菱重"), ("7012", "川重"), ("7013", "ＩＨＩ"), ("7186", "横浜ＦＧ"),
    ("7201", "日産自"), ("7202", "いすゞ"), ("7203", "トヨタ"),
    ("7211", "三菱自"), ("7261", "マツダ"), ("7267", "ホンダ"), ("7269", "スズキ"),
    ("7270", "ＳＵＢＡＲＵ"), ("7272", "ヤマハ発"), ("7453", "良品計画"),
    ("7532", "パンパシＨＤ"), ("7731", "ニコン"), ("7733", "オリンパス"),
    ("7735", "スクリン"), ("7741", "ＨＯＹＡ"), ("7751", "キヤノン"),
    ("7752", "リコー"), ("7832", "バンダイナム"), ("7911", "ＴＯＰＰＡＮＨＤ"),
    ("7912", "大日印"), ("7951", "ヤマハ"), ("7974", "任天堂"), ("8001", "伊藤忠"),
    ("8002", "丸紅"), ("8015", "豊通商"), ("8031", "三井物"), ("8035", "東エレク"),
    ("8053", "住友商"), ("8058", "三菱商"), ("8233", "高島屋"), ("8252", "丸井Ｇ"),
    ("8253", "クレセゾン"), ("8267", "イオン"), ("8304", "あおぞら"),
    ("8306", "三菱ＵＦＪ"), ("8308", "りそなＨＤ"), ("8309", "三住トラスト"),
    ("8316", "三井住友"), ("8331", "千葉銀"), ("8354", "ふくおか"),
    ("8411", "みずほ"), ("8591", "オリックス"), ("8601", "大和証Ｇ"),
    ("8604", "野村ＨＤ"), ("8630", "ＳＯＭＰＯＨＤ"), ("8697", "ＪＰＸ"),
    ("8725", "ＭＳ＆ＡＤ"), ("8750", "第一ライフＧ"), ("8766", "東京海上"),
    ("8795", "Ｔ＆ＤＨＤ"), ("8801", "三井不"), ("8802", "菱地所"),
    ("8804", "東建物"), ("8830", "住友不"), ("9001", "東武"), ("9005", "東急"),
    ("9007", "小田急"), ("9008", "京王"), ("9009", "京成"), ("9020", "ＪＲ東日本"),
    ("9021", "ＪＲ西日本"), ("9022", "ＪＲ東海"), ("9064", "ヤマトＨＤ"),
    ("9101", "郵船"), ("9104", "商船三井"), ("9107", "川崎船"), ("9147", "ＮＸＨＤ"),
    ("9201", "ＪＡＬ"), ("9202", "ＡＮＡ"), ("9432", "ＮＴＴ"), ("9433", "ＫＤＤＩ"),
    ("9434", "ソフトバンク"), ("9501", "東電力ＨＤ"), ("9502", "中部電"),
    ("9503", "関西電"), ("9531", "東ガス"), ("9532", "大ガス"), ("9602", "東宝"),
    ("9735", "セコム"), ("9766", "コナミＧ"), ("9843", "ニトリＨＤ"),
    ("9983", "ファーストリテイ"), ("9984", "ソフトバンクＧ"),
]

MIN_ROE = 0.03  # これ未満(赤字含む)は質フィルターで除外
RECENT_LOW_WINDOW = 60  # 直近安値からの回復率を見る営業日数
MA_SHORT, MA_LONG = 25, 75  # 短期/長期移動平均
OVERBOUGHT_RSI = 70  # これ以上は「既に反発しきった」として除外


def fetch_metrics(code: str, name: str) -> dict | None:
    try:
        info = yf.Ticker(f"{code}.T").info
    except Exception as e:
        print(f"  [警告] {code} {name}: 取得失敗({e})")
        return None

    per = info.get("trailingPE")
    pbr = info.get("priceToBook")
    div_yield = info.get("dividendYield") or 0.0
    roe = info.get("returnOnEquity")
    price = info.get("currentPrice") or info.get("regularMarketPrice")

    if per is None or per <= 0 or pbr is None or pbr <= 0 or roe is None:
        return None  # 赤字・データ欠損は除外
    if roe < MIN_ROE:
        return None  # バリュートラップ回避の質フィルター

    return {
        "code": code, "name": name, "per": per, "pbr": pbr,
        "dividend_yield": div_yield, "roe": roe, "price": price,
    }


def fetch_turnaround_signals(code: str) -> dict | None:
    """直近の値動きから「下げ止まり/反発の兆し」を単純なルールで数値化する。
    将来を予測するモデルではなく、あくまで参考のテクニカルシグナル。"""
    try:
        hist = yf.Ticker(f"{code}.T").history(period="1y")
        closes = [float(x) for x in hist["Close"].dropna().tolist()]
    except Exception:
        return None
    need = max(RECENT_LOW_WINDOW, MA_LONG) + 21
    if len(closes) < need:
        return None

    current = closes[-1]
    recent_low = min(closes[-RECENT_LOW_WINDOW:])
    off_low_pct = (current / recent_low - 1) * 100 if recent_low > 0 else 0.0

    ma_short = sum(closes[-MA_SHORT:]) / MA_SHORT
    ma_long = sum(closes[-MA_LONG:]) / MA_LONG
    trend_pct = (ma_short / ma_long - 1) * 100 if ma_long > 0 else 0.0

    ret_recent = closes[-1] / closes[-21] - 1
    ret_prior = closes[-21] / closes[-41] - 1
    decel_pct = (ret_recent - ret_prior) * 100  # プラス=下落が減速/反転している

    rsi14 = _rsi(closes, len(closes) - 1, 14)

    return {
        "off_low_pct": off_low_pct, "trend_pct": trend_pct,
        "decel_pct": decel_pct, "rsi14": rsi14,
    }


def percentile_rank(values: list[float], reverse: bool = False) -> list[float]:
    """小さいほど良い指標はreverse=False(順位が高いほど良い)、
    大きいほど良い指標はreverse=Trueで、0〜1のパーセンタイル順位に変換する。"""
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=reverse)
    ranks = [0.0] * len(values)
    n = len(values)
    for rank, idx in enumerate(order):
        ranks[idx] = 1.0 - rank / max(1, n - 1)  # 1.0=最良、0.0=最悪
    return ranks


def main() -> None:
    print(f"日経225、{len(NIKKEI225)}銘柄のデータを取得中(yfinance)...")
    rows = []
    for i, (code, name) in enumerate(NIKKEI225, 1):
        m = fetch_metrics(code, name)
        if m:
            rows.append(m)
        if i % 20 == 0:
            print(f"  {i}/{len(NIKKEI225)}件処理済み...")
        time.sleep(0.1)  # yfinance側への配慮

    print(f"\n質フィルター後: {len(rows)}/{len(NIKKEI225)}銘柄が対象")

    per_scores = percentile_rank([r["per"] for r in rows])       # 低PERほど高得点
    pbr_scores = percentile_rank([r["pbr"] for r in rows])       # 低PBRほど高得点
    div_scores = percentile_rank([r["dividend_yield"] for r in rows], reverse=True)  # 高配当ほど高得点

    for r, ps, bs, ds in zip(rows, per_scores, pbr_scores, div_scores):
        r["value_score"] = round((ps + bs + ds) / 3, 4)

    print(f"反発シグナル(価格推移)を取得中... ({len(rows)}銘柄)")
    ta_rows = []
    for i, r in enumerate(rows, 1):
        ta = fetch_turnaround_signals(r["code"])
        if ta:
            r.update(ta)
            ta_rows.append(r)
        if i % 30 == 0:
            print(f"  {i}/{len(rows)}件処理済み...")
        time.sleep(0.1)

    # 既に反発しきった(過熱)銘柄は、ここで完全に対象から除外する
    # (パーセンタイル計算のプールにも入れない。含めると分母が歪むため)
    is_overbought = lambda r: r["rsi14"] is not None and r["rsi14"] >= OVERBOUGHT_RSI
    overbought = [r for r in ta_rows if is_overbought(r)]
    eligible = [r for r in ta_rows if not is_overbought(r)]
    print(f"除外(RSI{OVERBOUGHT_RSI}以上、既に反発しきった可能性): {len(overbought)}銘柄")

    off_low_scores = percentile_rank([r["off_low_pct"] for r in eligible], reverse=True)
    trend_scores = percentile_rank([r["trend_pct"] for r in eligible], reverse=True)
    decel_scores = percentile_rank([r["decel_pct"] for r in eligible], reverse=True)
    for r, o, t, d in zip(eligible, off_low_scores, trend_scores, decel_scores):
        r["turnaround_score"] = round((o + t + d) / 3, 4)
        r["combined_score"] = round((r["value_score"] + r["turnaround_score"]) / 2, 4)
    print(f"反発シグナル取得できた銘柄: {len(ta_rows)}/{len(rows)}(うちランキング対象{len(eligible)})")

    eligible.sort(key=lambda r: r["combined_score"], reverse=True)
    top50 = eligible[:50]

    output = {
        "updated": dt.datetime.now().isoformat(timespec="seconds"),
        "universe": "nikkei225",
        "universe_size": len(NIKKEI225),
        "screened": len(eligible),
        "quality_filter": f"PER>0 かつ ROE>={MIN_ROE*100:.0f}%(赤字・低ROEは除外)、"
                          f"RSI{OVERBOUGHT_RSI}以上は既に反発しきった可能性として除外"
                          f"(今回{len(overbought)}銘柄除外)",
        "method": "割安スコア(PER・PBR・配当利回りのパーセンタイル平均)と"
                  "反発スコア(直近安値からの回復率・短期/長期移動平均トレンド・"
                  "下落の減速のパーセンタイル平均)を1:1で組み合わせた総合スコア(0〜1)でランキング。",
        "disclaimer": "検証済みの売買シグナルではなく、現時点の割安さ・値動きのスナップショット。"
                      "反発シグナルは将来を予測するものではなく単純なテクニカルルールに基づく参考値。"
                      "売買は自己判断で。",
        "ranking": [
            {
                "rank": i + 1, "code": r["code"], "name": r["name"],
                "price": r["price"], "per": round(r["per"], 2),
                "pbr": round(r["pbr"], 2),
                "dividend_yield_pct": round(r["dividend_yield"], 2),
                "roe_pct": round(r["roe"] * 100, 1),
                "value_score": r["value_score"],
                "turnaround_score": r["turnaround_score"],
                "combined_score": r["combined_score"],
                "rsi14": round(r["rsi14"], 1) if r["rsi14"] is not None else None,
                "off_low_pct": round(r["off_low_pct"], 1),
                "trend_pct": round(r["trend_pct"], 2),
            }
            for i, r in enumerate(top50)
        ],
    }

    with open("value_ranking.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 追跡用の履歴に今回のTOP50を追記(1行=1銘柄、run_dateで回を識別)
    run_date = dt.date.today().isoformat()
    with open("value_history.jsonl", "a", encoding="utf-8") as f:
        for item in output["ranking"]:
            f.write(json.dumps({"run_date": run_date, **item}, ensure_ascii=False) + "\n")

    print(f"\n=== 割安株ランキング TOP10(全50件はvalue_ranking.json参照) ===")
    for r in top50[:10]:
        rsi_s = f"{r['rsi14']:.0f}" if r["rsi14"] is not None else "-"
        print(f"  {r['code']} {r['name']:12s} PER{r['per']:.1f} PBR{r['pbr']:.2f} "
              f"配当{r['dividend_yield']:.1f}% ROE{r['roe']*100:.1f}% RSI{rsi_s} "
              f"底値比+{r['off_low_pct']:.1f}% 割安{r['value_score']:.2f} 反発{r['turnaround_score']:.2f} "
              f"総合{r['combined_score']:.3f}")

    print(f"\nvalue_ranking.json に上位50件を出力、value_history.jsonlに追記しました。")


if __name__ == "__main__":
    main()
