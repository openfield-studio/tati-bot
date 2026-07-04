#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF自動売買ボット — マスター/サブエージェント構成（骨組み）
=============================================================
証券会社 : 立花証券 e支店 API（v4r8 / v4r9想定）
対象     : 国内ETF（例 1306 / 1321 など）
資金     : 10万円スタート想定

設計思想
--------
MasterAgent（司令塔）が、毎営業日の引け後に各サブエージェントを順番に呼ぶ。
各サブエージェントは1つの責務だけを持ち、共有の TradingContext を読み書きする。

    MasterAgent
       ├─ DataAgent       … 株価データ取得
       ├─ StrategyAgent   … MA・RSIで売買シグナル判定
       ├─ RiskAgent       … 資金管理・発注可否・キルスイッチ
       ├─ ExecutionAgent  … 立花APIで発注（DRY_RUN対応）
       └─ ReporterAgent   … JSON状態出力（スマホ用）＋ログ

★安全設計★
 - 既定は DRY_RUN=True（紙トレード）。実弾発注は明示的に2つのフラグを立てた時だけ。
 - 1度に1ポジションのみ。最大投資額に上限。1日1回しか動かない冪等ガード。
 - kill_switch ファイルが存在したら全停止。

※ DataAgent と ExecutionAgent の中の「# TODO(立花)」部分は、口座開設後に
   立花公式のPythonサンプル(te_api_client.py)の実装を差し込む。電文の項目名は
   公式マニュアル「REQUEST I/F 注文入力機能引数項目仕様」に従うこと。
"""

from __future__ import annotations

import abc
import dataclasses
import datetime as dt
import json
import logging
import math
import os
import random
from typing import Optional


# ======================================================================
# 0. 設定
# ======================================================================
@dataclasses.dataclass
class Config:
    # --- 安全フラグ（ここが最重要）-------------------------------------
    dry_run: bool = True                # True = 発注せず判定だけ（紙トレード）
    enable_live_trading: bool = False   # 実弾を出すには True が別途必要
    # ↑ dry_run=False かつ enable_live_trading=True の時だけ本当に発注する

    # --- 資金・銘柄 ----------------------------------------------------
    capital_yen: int = 500_000          # 運用資金
    max_position_yen: int = 500_000     # 1ポジション上限（資金を超えない）
    symbol: str = "1306"                # 対象ETF（例: TOPIX連動 1306）
    trade_unit: int = 10                # 売買単位（research_result.jsonで上書き）
    #   ※10万円では「100株単位・株価1000円超」のETFは1単元が買えない。
    #     1株単位 or 株価の低いETFを選ぶか、資金を増やす必要がある。

    # --- 戦略パラメータ（research_result.json から自動で上書きされる）-----
    strategy_kind: str = "rsi_only"     # "rsi_only" / "mean_reversion" / "trend"
    sma_fast: int = 0
    sma_slow: int = 0
    rsi_period: int = 14
    rsi_overbought: float = 75.0        # これ以上は買い見送り（高値掴み回避）
    rsi_oversold: float = 35.0          # これ以下＝売られすぎ→買い（逆張り）
    rsi_exit: float = 50.0              # ここまでRSI回復で利確
    stop_loss_pct: float = 0.05         # 含み損でこの率に達したら損切り

    # --- 研究チームの結果ファイル（GO戦略をここから読む）---------------
    research_result_path: str = "research_result.json"
    require_go_verdict: bool = True     # 判定がGO以外なら新規買いを止める安全弁
    verdict: str = "UNKNOWN"            # research_result.json から読み込む判定

    # --- API（口座開設後に設定）---------------------------------------
    api_url: str = "https://demo-kabuka.e-shiten.jp/e_api_v4r8/auth/"  # まずデモ環境
    user_id: str = "YOUR_ID"
    password: str = "YOUR_PASSWORD"

    # --- ファイルパス --------------------------------------------------
    state_path: str = "state.json"      # スマホダッシュボードが読むファイル
    history_path: str = "history.jsonl" # 毎日の判定履歴(1行1レコード、追記式)
    kill_switch_path: str = "STOP"      # このファイルがあれば全停止


CFG = Config()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


# ======================================================================
# 1. 共有コンテキスト（エージェント間で受け渡す箱）
# ======================================================================
@dataclasses.dataclass
class TradingContext:
    date: str
    symbol: str
    prices: list[float] = dataclasses.field(default_factory=list)  # 終値の時系列
    last_price: float = 0.0

    # StrategyAgent が書く
    signal: str = "HOLD"          # "BUY" / "SELL" / "HOLD"
    confidence: float = 0.0       # 0.0〜1.0
    reason: str = ""

    # 現在のポジション
    has_position: bool = False
    entry_price: float = 0.0
    quantity: int = 0

    # RiskAgent が書く
    approved: bool = False
    order_quantity: int = 0

    # ExecutionAgent が書く
    executed: bool = False
    execution_note: str = ""

    # 損益（参考表示用）
    unrealized_pl: int = 0

    # 指標（ダッシュボード表示用）
    rsi: float = 0.0


# ======================================================================
# 2. ベースエージェント（全サブの共通親）
# ======================================================================
class BaseAgent(abc.ABC):
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.log = logging.getLogger(self.__class__.__name__)

    @abc.abstractmethod
    def run(self, ctx: TradingContext) -> TradingContext:
        ...


# ======================================================================
# 3. DataAgent — 株価データ取得
# ======================================================================
class DataAgent(BaseAgent):
    """終値の時系列を ctx.prices に詰める。
    口座開設前は合成データで動かして全体フローを確認できる。"""

    def run(self, ctx: TradingContext) -> TradingContext:
        prices = self._fetch_from_api(ctx.symbol)
        if prices is None:
            prices = self._load_cache(ctx.symbol)
            if prices is not None:
                self.log.info("実データキャッシュ prices_%s.csv を使用（DRY-RUN用）", ctx.symbol)
        if prices is None:
            self.log.warning("API未接続＆キャッシュ無しのため合成データで代用（フロー確認用）")
            prices = self._synthetic_series(n=260, seed=ctx.symbol)
        ctx.prices = prices
        ctx.last_price = prices[-1]
        self.log.info("取得 %d 本 / 最新終値 %.1f円", len(prices), ctx.last_price)
        return ctx

    @staticmethod
    def _load_cache(symbol: str) -> Optional[list[float]]:
        """research_agents / fetch_yf が作る prices_<symbol>.csv を読む。
        口座開設前のDRY-RUNを本物の過去株価で回すために使う。"""
        path = f"prices_{symbol}.csv"
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                series = [float(line.strip()) for line in f if line.strip()]
            return series or None
        except Exception:
            return None

    def _fetch_from_api(self, symbol: str) -> Optional[list[float]]:
        # TODO(立花): te_api_client でログイン→マスタ/時系列取得を実装。
        #   1) login(api_url, user_id, password)  ※電話認証が必要
        #   2) 返却された仮想URL(sUrlRequest)へ問い合わせ
        #   3) 日足の終値リストを返す
        # 未実装の間は None を返し、下の合成データにフォールバックする。
        return None

    @staticmethod
    def _synthetic_series(n: int, seed: str) -> list[float]:
        rng = random.Random(sum(ord(c) for c in str(seed)))
        price = 1000.0
        out = []
        for _ in range(n):
            price *= 1 + rng.gauss(0.0004, 0.012)  # ゆるやかな上昇トレンド＋ノイズ
            out.append(round(price, 1))
        return out


# ======================================================================
# 4. StrategyAgent — シグナル判定（研究チームが検証したロジックと一致）
# ======================================================================
class StrategyAgent(BaseAgent):
    """研究チームでGOが出た rsi_only（純RSI逆張り）と同じ判定を行う。
    ・ノーポジ: RSI < rsi_oversold（売られすぎ）→ BUY
    ・保有中:   損切り(entry比 -stop_loss_pct) → SELL / RSI >= rsi_exit(回復) → SELL
    検証と実行のロジックを一致させることで、バックテストの妥当性を保つ。"""

    def run(self, ctx: TradingContext) -> TradingContext:
        p = ctx.prices
        if len(p) <= self.cfg.rsi_period:
            ctx.signal, ctx.reason = "HOLD", "データ不足"
            return ctx

        rsi = self._rsi(p, self.cfg.rsi_period)
        ctx.rsi = round(rsi, 1)

        if self.cfg.strategy_kind == "rsi_only":
            if ctx.has_position:
                # 損切り優先 → RSI回復で利確
                if ctx.entry_price > 0 and ctx.last_price <= ctx.entry_price * (1 - self.cfg.stop_loss_pct):
                    ctx.signal = "SELL"
                    ctx.reason = f"損切り(取得{ctx.entry_price:.1f}比 -{self.cfg.stop_loss_pct*100:.0f}%) / RSI={rsi:.0f}"
                    ctx.confidence = 1.0
                elif rsi >= self.cfg.rsi_exit:
                    ctx.signal = "SELL"
                    ctx.reason = f"利確: RSI回復({rsi:.0f}≧{self.cfg.rsi_exit:.0f})"
                    ctx.confidence = round(max(0.0, min(1.0, (rsi - self.cfg.rsi_exit) / 30 + 0.5)), 2)
                else:
                    ctx.signal = "HOLD"
                    ctx.reason = f"保有継続: RSI={rsi:.0f}（利確{self.cfg.rsi_exit:.0f}/損切り{self.cfg.stop_loss_pct*100:.0f}%待ち）"
            else:
                if rsi < self.cfg.rsi_oversold:
                    ctx.signal = "BUY"
                    ctx.reason = f"売られすぎ: RSI={rsi:.0f} < {self.cfg.rsi_oversold:.0f}（押し目）"
                    ctx.confidence = round(max(0.0, min(1.0, (self.cfg.rsi_oversold - rsi) / 30 + 0.5)), 2)
                else:
                    ctx.signal = "HOLD"
                    ctx.reason = f"押し目待ち: RSI={rsi:.0f} ≧ {self.cfg.rsi_oversold:.0f}"
        else:
            # 念のため: 想定外の戦略種別では新規は出さず安全側へ
            ctx.signal = "HOLD"
            ctx.reason = f"未対応の戦略種別({self.cfg.strategy_kind})のため見送り"

        self.log.info("シグナル %s (確度%.0f%%) — %s",
                      ctx.signal, ctx.confidence * 100, ctx.reason)
        return ctx

    @staticmethod
    def _sma(p: list[float], n: int) -> float:
        return sum(p[-n:]) / n

    @staticmethod
    def _rsi(p: list[float], n: int) -> float:
        gains, losses = [], []
        for i in range(-n, 0):
            diff = p[i] - p[i - 1]
            (gains if diff >= 0 else losses).append(abs(diff))
        avg_gain = sum(gains) / n if gains else 0.0
        avg_loss = sum(losses) / n if losses else 0.0
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))


# ======================================================================
# 5. RiskAgent — 資金管理・発注可否・キルスイッチ
# ======================================================================
class RiskAgent(BaseAgent):
    def run(self, ctx: TradingContext) -> TradingContext:
        # キルスイッチ最優先
        if os.path.exists(self.cfg.kill_switch_path):
            ctx.approved = False
            ctx.reason += " | STOPファイル検出→全停止"
            self.log.warning("キルスイッチ作動。発注しません。")
            return ctx

        if ctx.signal == "BUY" and not ctx.has_position:
            # 安全弁: 研究チームの判定がGO以外なら新規買いを承認しない
            if self.cfg.require_go_verdict and self.cfg.verdict != "GO":
                ctx.approved = False
                ctx.reason += f" | 判定が{self.cfg.verdict}のため新規買い見送り(GO以外)"
                self.log.warning("買い見送り: research判定=%s（GOでないため）", self.cfg.verdict)
                return ctx
            budget = min(self.cfg.capital_yen, self.cfg.max_position_yen)
            unit = self.cfg.trade_unit  # ETFごとの売買単位
            qty = int(budget // (ctx.last_price * unit)) * unit
            if qty <= 0:
                ctx.approved, ctx.reason = False, ctx.reason + " | 資金不足で1単元買えない"
            else:
                ctx.approved, ctx.order_quantity = True, qty
                self.log.info("買い承認: %d株 (約%s円)", qty, f"{int(qty * ctx.last_price):,}")

        elif ctx.signal == "SELL" and ctx.has_position:
            ctx.approved, ctx.order_quantity = True, ctx.quantity
            self.log.info("売り承認: %d株 全数決済", ctx.quantity)

        else:
            ctx.approved = False
            self.log.info("発注なし（条件未成立 or ポジション状態と不一致）")
        return ctx


# ======================================================================
# 6. ExecutionAgent — 立花APIで発注（DRY_RUN対応）
# ======================================================================
class ExecutionAgent(BaseAgent):
    def run(self, ctx: TradingContext) -> TradingContext:
        if not ctx.approved:
            return ctx

        live = (not self.cfg.dry_run) and self.cfg.enable_live_trading
        if not live:
            ctx.executed = True
            ctx.execution_note = f"[DRY-RUN] {ctx.signal} {ctx.order_quantity}株 を発注した想定"
            self.log.info(ctx.execution_note)
            self._apply_paper_fill(ctx)
            return ctx

        # ----- ここから本番発注 -----
        try:
            ok = self._place_order(ctx)        # TODO(立花)
            ctx.executed = ok
            ctx.execution_note = "実発注 成功" if ok else "実発注 失敗"
            if ok:
                self._apply_paper_fill(ctx)
            self.log.info(ctx.execution_note)
        except Exception as e:               # 発注は必ず握りつぶさずログ
            ctx.executed = False
            ctx.execution_note = f"発注例外: {e}"
            self.log.exception("発注で例外")
        return ctx

    def _place_order(self, ctx: TradingContext) -> bool:
        # TODO(立花): te_api_client で
        #   1) login（電話認証）→ sUrlRequest 取得
        #   2) 新規注文電文をPOST（v4r8でPOST対応）
        #      売買区分 / 銘柄コード=ctx.symbol / 数量=ctx.order_quantity /
        #      注文条件=成行 or 指値 …は「注文入力機能引数項目仕様」に従う
        #   3) 結果コードを判定して True/False
        raise NotImplementedError("口座開設後に立花サンプルを差し込む")

    @staticmethod
    def _apply_paper_fill(ctx: TradingContext) -> None:
        """約定したものとして手元のポジション状態を更新（DRY/本番共通の帳簿）"""
        if ctx.signal == "BUY":
            ctx.has_position = True
            ctx.entry_price = ctx.last_price
            ctx.quantity = ctx.order_quantity
        elif ctx.signal == "SELL":
            ctx.has_position = False
            ctx.entry_price = 0.0
            ctx.quantity = 0


# ======================================================================
# 7. ReporterAgent — スマホ用JSON出力＋ログ
# ======================================================================
class ReporterAgent(BaseAgent):
    def run(self, ctx: TradingContext) -> TradingContext:
        if ctx.has_position:
            ctx.unrealized_pl = int((ctx.last_price - ctx.entry_price) * ctx.quantity)

        snapshot = {
            "updated": dt.datetime.now().isoformat(timespec="seconds"),
            "date": ctx.date,
            "symbol": ctx.symbol,
            "last_price": ctx.last_price,
            "signal": ctx.signal,
            "confidence": ctx.confidence,
            "reason": ctx.reason,
            "rsi": ctx.rsi,
            "rsi_oversold": self.cfg.rsi_oversold,
            "rsi_exit": self.cfg.rsi_exit,
            "verdict": self.cfg.verdict,
            "has_position": ctx.has_position,
            "entry_price": ctx.entry_price,
            "quantity": ctx.quantity,
            "unrealized_pl": ctx.unrealized_pl,
            "executed": ctx.executed,
            "execution_note": ctx.execution_note,
            "mode": "DRY-RUN" if self.cfg.dry_run else "LIVE",
        }
        with open(self.cfg.state_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        # 履歴ログに1行追記（state.jsonは上書きされるが、こちらは積み上がる）
        self._append_history(snapshot)

        self.log.info("state.json 更新（スマホ表示用）/ 含み損益 %s円", f"{ctx.unrealized_pl:+,}")
        return ctx

    def _append_history(self, snapshot: dict) -> None:
        """同じ日に複数回実行されても、その日の行は1本に保つ（冪等）。
        壊れた行があっても他の行に影響しないようJSON Lines形式で書く。"""
        rows = []
        if os.path.exists(self.cfg.history_path):
            try:
                with open(self.cfg.history_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                            if row.get("date") != snapshot["date"]:
                                rows.append(row)
                        except json.JSONDecodeError:
                            continue  # 壊れた行はスキップ（履歴全体を守る）
            except Exception as e:
                self.log.warning("history.jsonl 読み込み失敗（新規作成扱いにする）: %s", e)

        rows.append(snapshot)
        rows.sort(key=lambda r: r.get("date", ""))
        try:
            with open(self.cfg.history_path, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.log.info("history.jsonl 更新（累計%d日分）", len(rows))
        except Exception as e:
            self.log.warning("history.jsonl 書き込み失敗（state.jsonは正常に更新済み）: %s", e)


# ======================================================================
# 8. MasterAgent — 司令塔
# ======================================================================
class MasterAgent:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.log = logging.getLogger("MasterAgent")
        # サブエージェントを実行順に並べる（ここを差し替えれば構成変更も簡単）
        self.pipeline: list[BaseAgent] = [
            DataAgent(cfg),
            StrategyAgent(cfg),
            RiskAgent(cfg),
            ExecutionAgent(cfg),
            ReporterAgent(cfg),
        ]

    def _load_position(self) -> dict:
        if os.path.exists(self.cfg.state_path):
            try:
                with open(self.cfg.state_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def run_once(self) -> TradingContext:
        today = dt.date.today().isoformat()
        prev = self._load_position()

        # 冪等ガード：同じ日に2回動かさない
        if prev.get("date") == today and prev.get("_run_done"):
            self.log.info("本日は実行済み。スキップ。")

        ctx = TradingContext(date=today, symbol=self.cfg.symbol)
        # 前回のポジション状態を引き継ぐ
        ctx.has_position = prev.get("has_position", False)
        ctx.entry_price = prev.get("entry_price", 0.0)
        ctx.quantity = prev.get("quantity", 0)

        self.log.info("=== %s 取引サイクル開始 (mode=%s) ===",
                      today, "DRY-RUN" if self.cfg.dry_run else "LIVE")
        for agent in self.pipeline:
            ctx = agent.run(ctx)
        self.log.info("=== サイクル完了 ===")
        return ctx


# ======================================================================
# 9. 研究結果(research_result.json)の読み込み → CFGへ反映
# ======================================================================
def load_research_into_cfg(cfg: Config) -> None:
    """研究チームの出力を読み、戦略パラメータと判定をCFGに反映する。
    ファイルが無ければ既定値のまま（その場合はGO以外扱いで新規買いは止まる）。"""
    log = logging.getLogger("research")
    if not os.path.exists(cfg.research_result_path):
        log.warning("%s が見つからない。先に research_agents.py を実行して戦略を作ること。"
                    "（このままだと判定UNKNOWNで新規買いは行いません）",
                    cfg.research_result_path)
        return
    try:
        with open(cfg.research_result_path, encoding="utf-8") as f:
            res = json.load(f)
    except Exception as e:
        log.warning("research_result.json の読み込み失敗: %s", e)
        return

    cfg.verdict = res.get("verdict", "UNKNOWN")
    if res.get("symbol"):
        cfg.symbol = str(res["symbol"])
    if res.get("trade_unit"):
        cfg.trade_unit = int(res["trade_unit"])

    sp = res.get("strategy") or {}
    if sp:
        cfg.strategy_kind = sp.get("kind", cfg.strategy_kind)
        cfg.rsi_period = int(sp.get("rsi_period", cfg.rsi_period))
        cfg.rsi_overbought = float(sp.get("rsi_overbought", cfg.rsi_overbought))
        cfg.rsi_oversold = float(sp.get("rsi_oversold", cfg.rsi_oversold))
        cfg.rsi_exit = float(sp.get("rsi_exit", cfg.rsi_exit))
        cfg.stop_loss_pct = float(sp.get("stop_loss_pct", cfg.stop_loss_pct))

    log.info("研究結果を反映: 判定=%s / 種別=%s / 銘柄=%s / "
             "売られすぎ<%.0f 利確>%.0f 損切り%.0f%%",
             cfg.verdict, cfg.strategy_kind, cfg.symbol,
             cfg.rsi_oversold, cfg.rsi_exit, cfg.stop_loss_pct * 100)
    if cfg.verdict != "GO":
        log.warning("判定が GO ではない(%s)。安全弁により新規買いは行いません。", cfg.verdict)


# ======================================================================
# 10. エントリーポイント
# ======================================================================
def main() -> None:
    load_research_into_cfg(CFG)        # ← GO戦略を読み込んでから動かす
    master = MasterAgent(CFG)
    master.run_once()


if __name__ == "__main__":
    main()
