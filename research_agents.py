#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF戦略 研究チーム — マスター/サブエージェント構成
=====================================================
役割: 売買ルールを「考える → 検証する → 批判する → 確定する」までを自動化。
出力: research_result.json（実行チーム StrategyAgent にそのまま渡せる戦略設定）

    ResearchMasterAgent（研究の司令塔）
       ├─ IdeaAgent       … ルール案（戦略アーキタイプ）を生成
       ├─ BacktestAgent   … 過去データでルールを検証（フリクション込み）
       ├─ MetricsAgent    … 勝率・最大DD・シャープ等を計算
       ├─ OptimizeAgent   … パラメータを振って in-sample で最良を探す
       └─ CritiqueAgent   … out-of-sample で過剰最適化を炙り出し合否判定

★思想★
 - データを「学習期間(IS)」と「検証期間(OOS)」に割る。OOSで崩れる戦略は不合格。
 - フリクション（手数料・スリッページ）を必ず入れる。入れないと過大評価になる。
 - バックテストは「過去がどうだったか」を見せるだけ。未来は保証しない。
   良すぎる結果ほど疑う。それを CritiqueAgent が機械的にやる。

※データソースは今は合成（再現可能）。口座開設後 or J-Quants等の実データに
  差し替える時は load_prices() だけ置き換えればよい。
"""

from __future__ import annotations

import abc
import dataclasses
import json
import logging
import math
import random
from typing import Optional


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    datefmt="%H:%M:%S")


# ======================================================================
# 0. 設定・戦略パラメータ
# ======================================================================
@dataclasses.dataclass
class ResearchConfig:
    capital_yen: int = 500_000
    trade_unit: int = 10                 # 1306想定（売買単位10株）
    symbol: str = "1306"
    commission_bps: float = 5.0          # 片道手数料(0.05%)を仮置き（実際の料率に合わせる）
    slippage_bps: float = 3.0            # スリッページ(0.03%)
    is_ratio: float = 0.65               # 前65%を学習(IS)、残り35%を検証(OOS)
    trading_days_per_year: int = 245
    result_path: str = "research_result.json"


@dataclasses.dataclass
class StrategyParams:
    """実行チームの StrategyAgent と同じ意味のパラメータ（そのまま渡せる）"""
    name: str = "trend"
    kind: str = "trend"                  # "trend"=順張り / "mean_reversion"=押し目買い
    sma_fast: int = 25
    sma_slow: int = 75
    rsi_period: int = 14
    rsi_overbought: float = 75.0         # trend用: これ以上は高値掴み回避で買わない
    rsi_oversold: float = 35.0           # MR用: これ以下を「押し目」とみなして買う
    rsi_exit: float = 55.0               # MR用: ここまでRSI回復で利確
    stop_loss_pct: float = 0.08          # 含み損で損切り（MRは浅め推奨）
    take_profit_pct: float = 0.0         # 0=利確なし（trendはトレンドを伸ばす）

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


CFG = ResearchConfig()


# ======================================================================
# 1. データ（本物のJ-Quantsデータを優先・取れなければ合成にフォールバック）
# ======================================================================
def load_prices_synthetic(symbol: str, n: int = 1500) -> list[float]:
    """再現可能な合成日足。前半は上昇トレンド、後半はレンジ＋急落を混ぜて
    『IS で良くても OOS で崩れる』状況を意図的に作る（批判機能のテスト用）。"""
    rng = random.Random(sum(ord(c) for c in symbol) + 7)
    price = 4000.0
    out = []
    for i in range(n):
        if i < n * 0.6:
            drift, vol = 0.0006, 0.011          # 上昇基調
        else:
            drift, vol = -0.0002, 0.018         # 失速＋荒れ相場
        price *= 1 + rng.gauss(drift, vol)
        price = max(price, 100.0)
        out.append(round(price, 1))
    return out


def load_prices(symbol: str, n: int = 6000) -> list[float]:
    """本物のJ-Quantsデータを優先して取得。
    取得できない場合（未設定・通信失敗など）は合成データにフォールバックし、
    『今どっちを使っているか』を必ずログに出す（取り違え防止）。"""
    log = logging.getLogger("load_prices")
    try:
        from jquants_data import load_prices_jquants
        prices = load_prices_jquants(symbol, n=n)
        log.info("★実データ(J-Quants)を使用: %s / %d本 (%.1f→%.1f)",
                 symbol, len(prices), prices[0], prices[-1])
        return prices
    except Exception as e:
        log.warning("実データ取得に失敗→合成データで代用します（理由: %s）", e)
        return load_prices_synthetic(symbol, n=n)


# ======================================================================
# 2. 指標とシグナル生成（実行チームと同じロジック＝検証の整合性を担保）
# ======================================================================
def _sma(p: list[float], i: int, n: int) -> Optional[float]:
    if i + 1 < n:
        return None
    return sum(p[i + 1 - n:i + 1]) / n


def _rsi(p: list[float], i: int, n: int) -> Optional[float]:
    if i < n:
        return None
    gains = losses = 0.0
    for k in range(i - n + 1, i + 1):
        d = p[k] - p[k - 1]
        if d >= 0:
            gains += d
        else:
            losses += -d
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


# ======================================================================
# 3. バックテスタ（単一ポジション・買いのみ・フリクション込み）
# ======================================================================
@dataclasses.dataclass
class BacktestResult:
    equity_curve: list[float]
    trades: list[dict]
    final_equity: float


class Backtester:
    def __init__(self, cfg: ResearchConfig):
        self.cfg = cfg

    def run(self, prices: list[float], sp: StrategyParams) -> BacktestResult:
        c = self.cfg
        cash = float(c.capital_yen)
        shares = 0
        entry = 0.0
        equity_curve, trades = [], []
        fee = (c.commission_bps + c.slippage_bps) / 10000.0

        for i, px in enumerate(prices):
            fast = _sma(prices, i, sp.sma_fast) if sp.sma_fast > 0 else None
            slow = _sma(prices, i, sp.sma_slow) if sp.sma_slow > 0 else None
            rsi = _rsi(prices, i, sp.rsi_period)

            # ---- 手仕舞い判定（保有中）----
            if shares > 0:
                exit_now, why = False, ""
                if sp.stop_loss_pct > 0 and px <= entry * (1 - sp.stop_loss_pct):
                    exit_now, why = True, "stop"
                elif sp.take_profit_pct > 0 and px >= entry * (1 + sp.take_profit_pct):
                    exit_now, why = True, "take"
                elif sp.kind == "mean_reversion":
                    # 押し目買い: RSIが回復したら利確 / 長期MA割れでトレンド崩れ撤退
                    if rsi is not None and rsi >= sp.rsi_exit:
                        exit_now, why = True, "rsi_recover"
                    elif slow is not None and px < slow:
                        exit_now, why = True, "trend_break"
                elif sp.kind == "rsi_only":
                    # 純RSI逆張り: RSIが回復したら利確（MAは見ない）
                    if rsi is not None and rsi >= sp.rsi_exit:
                        exit_now, why = True, "rsi_recover"
                else:
                    # 順張り: 短期MAが長期MAを下抜けたら撤退
                    if fast is not None and slow is not None and fast < slow:
                        exit_now, why = True, "trend_down"
                if exit_now:
                    cash += shares * px * (1 - fee)
                    trades.append({"side": "SELL", "px": px, "qty": shares,
                                   "why": why, "i": i})
                    shares, entry = 0, 0.0

            # ---- 新規買い判定（ノーポジ）----
            elif rsi is not None:
                buy_now = False
                if sp.kind == "rsi_only":
                    # 純RSI逆張り: 売られすぎだけで拾う（MAフィルタなし＝取引が増える）
                    buy_now = rsi < sp.rsi_oversold
                elif sp.kind == "mean_reversion":
                    # 上昇基調(株価>長期MA)の中で、RSIが売られすぎ＝押し目を拾う
                    buy_now = (slow is not None) and (px > slow) and (rsi < sp.rsi_oversold)
                else:
                    # 順張り: 短期MA>長期MA かつ 買われすぎでない
                    buy_now = (fast is not None and slow is not None and fast > slow
                               and rsi < sp.rsi_overbought)
                if buy_now:
                    budget = cash
                    qty = int(budget // (px * (1 + fee) * c.trade_unit)) * c.trade_unit
                    if qty > 0:
                        cash -= qty * px * (1 + fee)
                        shares, entry = qty, px
                        trades.append({"side": "BUY", "px": px, "qty": qty, "i": i})

            equity_curve.append(cash + shares * px)

        return BacktestResult(equity_curve, trades, equity_curve[-1])


# ======================================================================
# 4. ベースエージェント
# ======================================================================
class BaseAgent(abc.ABC):
    def __init__(self, cfg: ResearchConfig):
        self.cfg = cfg
        self.log = logging.getLogger(self.__class__.__name__)

    @abc.abstractmethod
    def run(self, ctx: dict) -> dict: ...


# ======================================================================
# 5. IdeaAgent — ルール案（アーキタイプ）を生成
# ======================================================================
class IdeaAgent(BaseAgent):
    def run(self, ctx: dict) -> dict:
        # 純RSI逆張り（MAなし）。エントリー条件は「RSIが売られすぎ」の1つだけ。
        # トレンドフィルタを外したぶん、押し目買いより頻繁にエントリーする＝
        # 2年データでも取引数を稼いで検証しやすくなる狙い。
        # StrategyParams(name, kind, fast, slow, rsi_period, overbought,
        #                oversold, exit, stop, take)
        ideas = [
            StrategyParams("rsi_30_50", "rsi_only", 0, 0, 14, 75, 30, 50, 0.05, 0.0),
            StrategyParams("rsi_30_55", "rsi_only", 0, 0, 14, 75, 30, 55, 0.05, 0.0),
            StrategyParams("rsi_35_50", "rsi_only", 0, 0, 14, 75, 35, 50, 0.05, 0.0),
            StrategyParams("rsi_25_55", "rsi_only", 0, 0, 14, 75, 25, 55, 0.06, 0.0),
        ]
        ctx["ideas"] = ideas
        self.log.info("純RSI逆張り案 %d 個を生成: %s",
                      len(ideas), ", ".join(s.name for s in ideas))
        return ctx


# ======================================================================
# 6. BacktestAgent — 各案を学習期間(IS)で検証
# ======================================================================
class BacktestAgent(BaseAgent):
    def run(self, ctx: dict) -> dict:
        bt = Backtester(self.cfg)
        ctx["bt_is"] = {s.name: bt.run(ctx["prices_is"], s) for s in ctx["ideas"]}
        self.log.info("学習期間(IS)で %d 案をバックテスト完了", len(ctx["ideas"]))
        return ctx


# ======================================================================
# 7. MetricsAgent — 成績指標を計算
# ======================================================================
class MetricsAgent(BaseAgent):
    def run(self, ctx: dict) -> dict:
        ctx["metrics_is"] = {name: self.metrics(res)
                             for name, res in ctx["bt_is"].items()}
        self.log.info("指標計算完了（IS）")
        for name, m in ctx["metrics_is"].items():
            self.log.info("  %-11s 利益率%+6.1f%% / 最大DD%5.1f%% / "
                          "Sharpe%5.2f / 取引%3d / 勝率%4.0f%%",
                          name, m["return_pct"], m["max_dd_pct"],
                          m["sharpe"], m["trades"], m["win_rate"] * 100)
        return ctx

    def metrics(self, res: BacktestResult) -> dict:
        eq = res.equity_curve
        start, end = eq[0], eq[-1]
        ret = (end / start - 1) * 100

        # 最大ドローダウン
        peak, max_dd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            max_dd = max(max_dd, (peak - v) / peak)

        # 日次リターンからSharpe（年率）
        rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]
        if len(rets) > 1:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            sd = math.sqrt(var)
            sharpe = (mean / sd * math.sqrt(self.cfg.trading_days_per_year)
                      if sd > 0 else 0.0)
        else:
            sharpe = 0.0

        # 勝率・プロフィットファクタ（往復ペアで集計）
        wins = losses = 0
        gross_win = gross_loss = 0.0
        buy = None
        for t in res.trades:
            if t["side"] == "BUY":
                buy = t
            elif t["side"] == "SELL" and buy:
                pnl = (t["px"] - buy["px"]) * t["qty"]
                if pnl >= 0:
                    wins += 1; gross_win += pnl
                else:
                    losses += 1; gross_loss += -pnl
                buy = None
        closed = wins + losses
        win_rate = wins / closed if closed else 0.0
        pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

        return {"return_pct": ret, "max_dd_pct": max_dd * 100, "sharpe": sharpe,
                "trades": closed, "win_rate": win_rate,
                "profit_factor": pf,
                "calmar": (ret / (max_dd * 100)) if max_dd > 0 else float("inf")}


# ======================================================================
# 8. OptimizeAgent — IS でパラメータを振って最良を探す
# ======================================================================
class OptimizeAgent(BaseAgent):
    def run(self, ctx: dict) -> dict:
        bt = Backtester(self.cfg)
        met = MetricsAgent(self.cfg)
        base = max(ctx["metrics_is"].items(),
                   key=lambda kv: kv[1]["calmar"])[0]
        seed = next(s for s in ctx["ideas"] if s.name == base)

        best, best_score, tested = None, -1e9, 0

        if seed.kind == "rsi_only":
            # ★過剰最適化対策★ 売られすぎ閾値と利確閾値だけを少数試行。損切り5%固定。
            for oversold in (25, 30, 35):
                for rsi_exit in (50, 55):
                    sp = StrategyParams("optimized", "rsi_only",
                                        0, 0, seed.rsi_period,
                                        seed.rsi_overbought, oversold,
                                        rsi_exit, 0.05, 0.0)
                    m = met.metrics(bt.run(ctx["prices_is"], sp))
                    tested += 1
                    if m["trades"] < 3:
                        continue
                    if m["calmar"] > best_score:
                        best, best_score = sp, m["calmar"]
        elif seed.kind == "mean_reversion":
            # ★過剰最適化対策★ 探索を最小限に。
            # slow=75(標準)・利確55・損切り5%は固定し、丸い数字のみ少数試行。
            # ノブを減らすほど「たまたま当たり」が減って信頼できる。
            for slow in (50, 75):
                for oversold in (40, 45):
                    sp = StrategyParams("optimized", "mean_reversion",
                                        0, slow, seed.rsi_period,
                                        seed.rsi_overbought, oversold,
                                        55, 0.05, 0.0)
                    m = met.metrics(bt.run(ctx["prices_is"], sp))
                    tested += 1
                    if m["trades"] < 3:
                        continue
                    if m["calmar"] > best_score:
                        best, best_score = sp, m["calmar"]
        else:
            # ★過剰最適化対策★ 順張りも探索を最小限に。
            # 損切り8%固定、丸い数字のMA組み合わせのみ少数試行。
            for fast in (10, 25):
                for slow in (50, 75):
                    if fast >= slow:
                        continue
                    sp = StrategyParams("optimized", "trend", fast, slow,
                                        seed.rsi_period, seed.rsi_overbought,
                                        stop_loss_pct=0.08)
                    m = met.metrics(bt.run(ctx["prices_is"], sp))
                    tested += 1
                    if m["trades"] < 3:
                        continue
                    if m["calmar"] > best_score:
                        best, best_score = sp, m["calmar"]

        ctx["optimized"] = best
        ctx["optimize_tested"] = tested
        if best is None:
            self.log.warning("最適化: %d 通り試したが、有効な設定なし"
                             "（取引が成立しにくい相場）。", tested)
        else:
            self.log.info("最適化: %d 通り試行 → 最良 %s (IS Calmar=%.2f)",
                          tested, _describe(best), best_score)
        return ctx


def _describe(sp: StrategyParams) -> str:
    if sp.kind == "rsi_only":
        return (f"純RSI逆張り 売られすぎ<{sp.rsi_oversold:.0f} "
                f"利確>{sp.rsi_exit:.0f} 損切り{sp.stop_loss_pct*100:.0f}%")
    if sp.kind == "mean_reversion":
        return (f"押し目買い slow={sp.sma_slow} 売られすぎ<{sp.rsi_oversold:.0f} "
                f"利確>{sp.rsi_exit:.0f} 損切り{sp.stop_loss_pct*100:.0f}%")
    return (f"順張り fast={sp.sma_fast} slow={sp.sma_slow} "
            f"損切り{sp.stop_loss_pct*100:.0f}%")


# ======================================================================
# 9. CritiqueAgent — OOSで過剰最適化を炙り出し合否判定（研究チームの良心）
# ======================================================================
class CritiqueAgent(BaseAgent):
    def run(self, ctx: dict) -> dict:
        bt = Backtester(self.cfg)
        met = MetricsAgent(self.cfg)
        sp = ctx["optimized"]
        if sp is None:
            ctx["metrics_oos"] = {}
            ctx["verdict"] = "NO-GO"
            ctx["warnings"] = ["有効な戦略が見つからなかった（取引が成立しにくい設定/相場）。"
                               "ルール案かデータを見直すこと。"]
            self.log.warning("判定: NO-GO（有効な戦略なし）")
            return ctx

        m_is = met.metrics(bt.run(ctx["prices_is"], sp))
        m_oos = met.metrics(bt.run(ctx["prices_oos"], sp))
        ctx["metrics_oos"] = m_oos

        warnings, verdict = [], "GO"

        # (1) IS→OOS の劣化（過剰最適化の典型）
        if m_is["calmar"] > 0 and m_oos["calmar"] < m_is["calmar"] * 0.4:
            warnings.append(
                f"OOSで成績が大きく劣化(Calmar {m_is['calmar']:.2f}→"
                f"{m_oos['calmar']:.2f})。過剰最適化の疑い濃厚。")
            verdict = "NO-GO"

        # (2) OOSで負け
        if m_oos["return_pct"] < 0 or m_oos["sharpe"] < 0:
            warnings.append(
                f"検証期間(OOS)で損失(利益率{m_oos['return_pct']:+.1f}%, "
                f"Sharpe{m_oos['sharpe']:.2f})。本番投入は危険。")
            verdict = "NO-GO"

        # (3) 取引数が少なすぎ＝統計的に当てにならない
        if m_oos["trades"] < 8:
            warnings.append(
                f"OOSの取引回数が{m_oos['trades']}回と少なく、結果はまぐれの可能性。")
            if verdict == "GO":
                verdict = "CAUTION"

        # (4) ドローダウンが深い
        if m_oos["max_dd_pct"] > 25:
            warnings.append(
                f"OOS最大ドローダウン{m_oos['max_dd_pct']:.0f}%。"
                f"50万なら一時的に約{int(self.cfg.capital_yen*m_oos['max_dd_pct']/100):,}円減る覚悟が要る。")
            if verdict == "GO":
                verdict = "CAUTION"

        # (5) 探索しすぎ警告（試行回数が多いほど偶然ヒットが混じる）
        if ctx.get("optimize_tested", 0) > 20:
            warnings.append(
                f"最適化で{ctx['optimize_tested']}通り試した＝偶然の勝ちパターンを"
                f"拾ってる可能性。パラメータは単純なほど信頼できる。")

        ctx["verdict"] = verdict
        ctx["warnings"] = warnings
        self.log.info("OOS成績: 利益率%+.1f%% / 最大DD%.1f%% / Sharpe%.2f / 取引%d回",
                      m_oos["return_pct"], m_oos["max_dd_pct"],
                      m_oos["sharpe"], m_oos["trades"])
        self.log.info("判定: %s", verdict)
        for w in warnings:
            self.log.warning("⚠ %s", w)
        return ctx


# ======================================================================
# 10. ResearchMasterAgent — 司令塔
# ======================================================================
class ResearchMasterAgent:
    def __init__(self, cfg: ResearchConfig):
        self.cfg = cfg
        self.log = logging.getLogger("ResearchMaster")
        self.pipeline = [IdeaAgent(cfg), BacktestAgent(cfg), MetricsAgent(cfg),
                         OptimizeAgent(cfg), CritiqueAgent(cfg)]

    def run(self) -> dict:
        prices = load_prices(self.cfg.symbol)
        split = int(len(prices) * self.cfg.is_ratio)
        ctx = {"prices": prices,
               "prices_is": prices[:split],
               "prices_oos": prices[split:]}

        self.log.info("=== 研究開始 / 全%d本（IS %d本 + OOS %d本）===",
                      len(prices), split, len(prices) - split)
        for agent in self.pipeline:
            ctx = agent.run(ctx)

        sp = ctx["optimized"]
        result = {
            "symbol": self.cfg.symbol,
            "trade_unit": self.cfg.trade_unit,
            "verdict": ctx["verdict"],
            "warnings": ctx["warnings"],
            "strategy": sp.as_dict() if sp is not None else None,
            "in_sample": (ctx["metrics_is"][max(
                ctx["metrics_is"], key=lambda k: ctx["metrics_is"][k]["calmar"])]
                if ctx.get("metrics_is") else {}),
            "out_of_sample": ctx.get("metrics_oos", {}),
            "note": "バックテストは過去の検証であり将来を保証しない。"
                    "判定がGOでも少額・DRY-RUNから始めること。",
        }
        with open(self.cfg.result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        self.log.info("=== 研究完了 → %s に出力 ===", self.cfg.result_path)
        return result


def main() -> None:
    ResearchMasterAgent(CFG).run()


if __name__ == "__main__":
    main()
