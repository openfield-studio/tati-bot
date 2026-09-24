#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
レジームシフト・ボット(1321/1571) — ドローダウン基準レジームフィルター戦略
=============================================================
証券会社: 立花証券 e支店 API(未接続、trading_agents.pyと同じ枠組みを踏襲)
対象    : 1321(NEXT FUNDS 日経225ETF、ロング)/ 1571(NEXT FUNDS 日経平均インバース、
          単純-1倍。下落相場でのベア代替として「買うだけ」で使う。信用売り不要)

背景・設計根拠
--------------
2026-09-24のセッション(SESSION_LOG.md項目81〜111、FACTOR_RESEARCH_LOG.mdキュー#16)で
検証・確定した戦略をそのまま実装したもの。1306の既存戦略(trading_agents.py、RSI売られすぎの
純粋な逆張り)とは対象銘柄・ロジックとも別物であり、既存の1306ボットとは完全に独立して動く
(既存のtrading_agents.py/research_agents.py/value_screener.pyは一切変更していない)。

ロジック(1321自身の値動きで判定):
  1. レジーム判定: 直近252営業日高値からのドローダウンが20%以上→「下落相場」、
     未満→「通常相場」
  2. ショック検知: 1日の下落が-2.5%以下、cooldown15営業日(同じ下落局面の重複検知を防ぐ)
  3. ノーポジ時にショックを検知したら:
       通常相場 → 1321を新規購入(損切り30%、利確なし)
       下落相場 → 1571を新規購入(利確5%・損切り18%、単純-1倍なので「買うだけ」でベア相当)
  4. 保有中は、利確/損切り/最大保有20営業日のいずれかに達したら手仕舞い

★安全設計(trading_agents.pyと同じ考え方)★
 - 既定は DRY_RUN=True(紙トレード)。実弾発注はまだ実装していない(口座・銘柄追加の
   判断が別途必要なため、今回は信号生成とpaper-fill記録のみ)。
 - state_regime_shift.json は公開用(GitHub Pages配信想定、金額は出さない)。
 - position_regime_shift.json は非公開(.gitignore対象、金額・エントリー日を含む正確な状態)。
 - history_regime_shift.jsonl は非公開の日次履歴。

使い方: python regime_shift_agent.py
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
from typing import Optional

import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("regime_shift_agent")


# ======================================================================
# 0. 設定
# ======================================================================
@dataclasses.dataclass
class Config:
    dry_run: bool = True                 # 実弾発注はまだ未実装(常にTrue運用)
    enable_live_trading: bool = False    # 将来立花API接続時のための予約フラグ

    capital_yen: int = 500_000
    symbol_long: str = "1321"            # 通常相場での買い対象
    symbol_bear: str = "1571"            # 下落相場での代替買い対象(単純-1倍インバース)
    trade_unit: int = 1                  # ETFの売買単位(1321/1571は1株単位、要最終確認)

    high_window: int = 252               # レジーム判定用トレーリングハイの営業日数
    dd_threshold: float = 0.20           # このドローダウン以上で「下落相場」
    shock_threshold: float = -0.025      # 1日でこの下落率以下を「ショック」とみなす
    cooldown_days: int = 15              # 同じ下落局面の重複検知を防ぐ営業日数
    max_hold_days: int = 20              # 最大保有営業日数(これに達したら強制手仕舞い)
    long_stop_loss: float = 0.30         # 1321側の損切り(過去最悪-26.77%に余裕を持たせた値)
    bear_take_profit: float = 0.05       # 1571側の利確
    bear_stop_loss: float = 0.18         # 1571側の損切り(過去最悪-13.79%に余裕を持たせた値)

    state_path: str = "state_regime_shift.json"          # 公開・シグナルのみ
    position_path: str = "position_regime_shift.json"    # 非公開・.gitignore対象
    history_path: str = "history_regime_shift.jsonl"     # 非公開・.gitignore対象
    kill_switch_path: str = "STOP"       # 既存の1306ボットと共通のキルスイッチファイル


CFG = Config()


# ======================================================================
# 1. 価格データ取得
# ======================================================================
def fetch_closes(ticker: str, min_days: int = 300) -> list[tuple[dt.date, float]]:
    """yfinanceから終値を取得(分割断崖チェック込み、fetch_yf.py/1306ボットと同じ方式)。"""
    df = yf.Ticker(ticker).history(period="max", auto_adjust=True).dropna(subset=["Close"])
    dates = [idx.date() for idx in df.index]
    px = [float(x) for x in df["Close"].tolist()]
    for i in range(1, len(px)):
        r = px[i] / px[i - 1]
        if r < 0.7:
            factor = round(1 / r)
            if factor >= 2:
                for k in range(i):
                    px[k] /= factor
        elif r > 1.4:
            factor = round(r)
            if factor >= 2:
                for k in range(i):
                    px[k] *= factor
    if len(px) < min_days:
        log.warning("%s: データが%d本しかない(%d本未満)。レジーム判定の精度に注意", ticker, len(px), min_days)
    return list(zip(dates, px))


# ======================================================================
# 2. 状態の読み込み(非公開position.json)
# ======================================================================
def load_position() -> dict:
    if os.path.exists(CFG.position_path):
        try:
            with open(CFG.position_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("position読み込み失敗(新規扱い): %s", e)
    return {"holding": None, "entry_date": None, "entry_price": 0.0, "quantity": 0,
            "last_shock_index": -10**9}


def save_position(pos: dict) -> None:
    with open(CFG.position_path, "w", encoding="utf-8") as f:
        json.dump(pos, f, ensure_ascii=False, indent=2)


# ======================================================================
# 3. シグナル判定
# ======================================================================
def decide_signal(closes_long: list[tuple[dt.date, float]],
                   closes_bear: list[tuple[dt.date, float]], pos: dict) -> dict:
    dates_long = [d for d, _ in closes_long]
    px_long = {d: p for d, p in closes_long}
    px_bear = {d: p for d, p in closes_bear}

    today = dates_long[-1]
    today_price_long = px_long[today]
    i_today = len(dates_long) - 1

    # --- レジーム判定(直近high_window営業日の高値からのドローダウン) ---
    high_slice = [px_long[d] for d in dates_long[max(0, i_today - CFG.high_window + 1):i_today + 1]]
    trailing_high = max(high_slice)
    dd = 1 - today_price_long / trailing_high
    regime = "bear" if dd >= CFG.dd_threshold else "bull"

    # --- 保有中: 手仕舞い判定 ---
    if pos["holding"] is not None:
        held_days = i_today - dates_long.index(dt.date.fromisoformat(pos["entry_date"])) \
            if pos["entry_date"] in [d.isoformat() for d in dates_long] else CFG.max_hold_days
        entry_price = pos["entry_price"]
        if pos["holding"] == "long":
            cur_price = today_price_long
            r = cur_price / entry_price - 1
            if r <= -CFG.long_stop_loss:
                return {"action": "SELL", "target": "1321", "regime": regime, "dd": dd,
                        "reason": f"損切り(1321、取得比{r*100:+.1f}% <= -{CFG.long_stop_loss*100:.0f}%)"}
            if held_days >= CFG.max_hold_days:
                return {"action": "SELL", "target": "1321", "regime": regime, "dd": dd,
                        "reason": f"最大保有{CFG.max_hold_days}営業日に到達(取得比{r*100:+.1f}%)"}
            return {"action": "HOLD", "target": "1321", "regime": regime, "dd": dd,
                    "reason": f"1321保有継続(取得比{r*100:+.1f}%、{held_days}日目)"}
        else:  # holding == "bear"(1571保有)
            if today not in px_bear:
                return {"action": "HOLD", "target": "1571", "regime": regime, "dd": dd,
                        "reason": "1571の本日データ未取得"}
            cur_price = px_bear[today]
            r = cur_price / entry_price - 1
            if r >= CFG.bear_take_profit:
                return {"action": "SELL", "target": "1571", "regime": regime, "dd": dd,
                        "reason": f"利確(1571、取得比{r*100:+.1f}% >= +{CFG.bear_take_profit*100:.0f}%)"}
            if r <= -CFG.bear_stop_loss:
                return {"action": "SELL", "target": "1571", "regime": regime, "dd": dd,
                        "reason": f"損切り(1571、取得比{r*100:+.1f}% <= -{CFG.bear_stop_loss*100:.0f}%)"}
            if held_days >= CFG.max_hold_days:
                return {"action": "SELL", "target": "1571", "regime": regime, "dd": dd,
                        "reason": f"最大保有{CFG.max_hold_days}営業日に到達(取得比{r*100:+.1f}%)"}
            return {"action": "HOLD", "target": "1571", "regime": regime, "dd": dd,
                    "reason": f"1571保有継続(取得比{r*100:+.1f}%、{held_days}日目)"}

    # --- ノーポジ時: ショック検知(cooldown考慮) ---
    day_ret = today_price_long / px_long[dates_long[i_today - 1]] - 1 if i_today > 0 else 0.0
    is_shock = day_ret <= CFG.shock_threshold
    cooldown_ok = (i_today - pos.get("last_shock_index", -10**9)) >= CFG.cooldown_days

    if is_shock and cooldown_ok:
        target = "1571" if regime == "bear" else "1321"
        return {"action": "BUY", "target": target, "regime": regime, "dd": dd,
                "reason": f"ショック検知(本日{day_ret*100:+.2f}%)、レジーム={regime}→{target}を新規購入",
                "shock_index": i_today}
    elif is_shock:
        return {"action": "NONE", "target": None, "regime": regime, "dd": dd,
                "reason": f"ショック検知したがcooldown中(本日{day_ret*100:+.2f}%)",
                "shock_index": i_today}  # cooldownタイマーは更新する
    else:
        return {"action": "NONE", "target": None, "regime": regime, "dd": dd,
                "reason": f"ショックなし(本日{day_ret*100:+.2f}%、DD={dd*100:.1f}%、レジーム={regime})"}


# ======================================================================
# 4. 実行(DRY-RUNのpaper-fill、実発注はまだ未実装)
# ======================================================================
def apply_paper_fill(decision: dict, pos: dict, px_long: dict, px_bear: dict, today: dt.date) -> dict:
    if decision["action"] == "BUY":
        price = px_long[today] if decision["target"] == "1321" else px_bear[today]
        qty = int(CFG.capital_yen // (price * CFG.trade_unit)) * CFG.trade_unit
        pos["holding"] = "long" if decision["target"] == "1321" else "bear"
        pos["entry_date"] = today.isoformat()
        pos["entry_price"] = price
        pos["quantity"] = qty
        pos["last_shock_index"] = decision.get("shock_index", pos.get("last_shock_index"))
    elif decision["action"] == "SELL":
        pos["holding"] = None
        pos["entry_date"] = None
        pos["entry_price"] = 0.0
        pos["quantity"] = 0
    elif decision["action"] == "NONE" and "shock_index" in decision:
        pos["last_shock_index"] = decision["shock_index"]
    return pos


def append_history(row: dict) -> None:
    rows = []
    if os.path.exists(CFG.history_path):
        try:
            with open(CFG.history_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                        if r.get("date") != row["date"]:
                            rows.append(r)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.warning("history読み込み失敗(新規作成扱い): %s", e)
    rows.append(row)
    rows.sort(key=lambda r: r.get("date", ""))
    with open(CFG.history_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ======================================================================
# 5. メイン
# ======================================================================
def main() -> None:
    if os.path.exists(CFG.kill_switch_path):
        log.warning("STOPファイル検出。全停止します。")
        return

    closes_long = fetch_closes(f"{CFG.symbol_long}.T")
    closes_bear = fetch_closes(f"{CFG.symbol_bear}.T", min_days=100)
    today = closes_long[-1][0]
    px_long = dict(closes_long)
    px_bear = dict(closes_bear)

    pos = load_position()
    decision = decide_signal(closes_long, closes_bear, pos)

    log.info("判定: %s / 対象=%s / レジーム=%s(DD=%.1f%%) / %s",
             decision["action"], decision["target"], decision["regime"],
             decision["dd"] * 100, decision["reason"])

    if not CFG.dry_run and CFG.enable_live_trading:
        raise NotImplementedError("実発注はまだ実装していない(口座・銘柄追加の判断が別途必要)")

    if decision["action"] in ("BUY", "SELL"):
        pos = apply_paper_fill(decision, pos, px_long, px_bear, today)
        log.info("[DRY-RUN] %s %s を紙トレードで記録", decision["action"], decision["target"])
    elif decision["action"] == "NONE" and "shock_index" in decision:
        pos["last_shock_index"] = decision["shock_index"]
    save_position(pos)

    public_snapshot = {
        "updated": dt.datetime.now().isoformat(timespec="seconds"),
        "date": today.isoformat(),
        "regime": decision["regime"],
        "drawdown_pct": round(decision["dd"] * 100, 1),
        "action": decision["action"],
        "target": decision["target"],
        "reason": decision["reason"],
        "holding": pos["holding"],
        "mode": "DRY-RUN" if CFG.dry_run else "LIVE",
    }
    with open(CFG.state_path, "w", encoding="utf-8") as f:
        json.dump(public_snapshot, f, ensure_ascii=False, indent=2)

    append_history({**public_snapshot, "entry_price": pos.get("entry_price"),
                     "quantity": pos.get("quantity")})
    log.info("state_regime_shift.json(公開)・position_regime_shift.json(非公開)を更新")


if __name__ == "__main__":
    main()
