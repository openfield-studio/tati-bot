# -*- coding: utf-8 -*-
# ============================================================
# 損失上限ガード(キルスイッチ連動)
# 2026-10-02 新規作成。段階3(少額の実弾テスト)の安全装置として、
# 実弾の発注スクリプトを実行する前に必ず呼ぶことを想定。
#
# 動作:
#   1. e_api_login_pubkey.pyを実行してログインし直す(仮想URLを最新化)
#   2. 現物買付可能額(現金)+現物保有評価額(API) = 現在の総資産を取得
#   3. 初回実行時はこの値を「基準値」としてファイルに記録するだけ(停止しない)
#   4. 2回目以降は基準値と比較し、下落率が閾値を超えていたら
#      STOPファイル(regime_shift_agent.py / trading_agents.pyと共通のキルスイッチ)
#      を作成して異常終了する
#
# 閾値は「基準値比-20%」のみ(2026-10-02、ユーザーの「予算変わると金額だと
# 毎回設定しなおさないといけない」を受けて金額ベースの閾値を撤廃、割合のみに一本化)。
#
# 使い方: python loss_limit_guard.py
#   終了コード0: 発注を続行してよい
#   終了コード1: 損失上限を超えた、またはログイン失敗のため停止
# ============================================================
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys

from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STOP_PATH = os.path.join(BASE_DIR, "STOP")
BASELINE_PATH = os.path.join(BASE_DIR, ".auth", "loss_guard_baseline.json")  # 非公開(.gitignore対象)
FNAME_LOGIN_RESPONSE = os.path.join(BASE_DIR, ".auth", "file_login_response.txt")
FNAME_URL_INFO = os.path.join(BASE_DIR, "file_url_info.txt")
FNAME_INFO_P_NO = os.path.join(BASE_DIR, "file_info_p_no.txt")

# --- 閾値設定(割合のみ。予算が変わっても再設定不要) ---
THRESHOLD_PCT = 0.20        # 基準値比-20%で停止


def _load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_total_assets() -> float:
    """ログインし直し、現金(買付可能額)+保有株評価額を合算して現在の総資産を返す。"""
    # 1. ログインし直す(仮想URLの有効期限切れ対策、既存スクリプトをそのまま実行)
    result = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "e_api_login_pubkey.py")],
        cwd=BASE_DIR, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ログインに失敗しました(終了コード{result.returncode})")

    # 2. 現金(買付可能額)を取得
    cash_mod = _load_module(os.path.join(BASE_DIR, "e_api_get_kanougaku_genbutsu_pubkey.py"), "_loss_guard_cash")
    dic_url_info = cash_mod.func_get_url_info(FNAME_URL_INFO)
    dic_login_property = cash_mod.func_get_login_response(FNAME_LOGIN_RESPONSE)
    p_no = cash_mod.func_get_p_no(FNAME_INFO_P_NO) + 1
    cash_mod.func_save_p_no(FNAME_INFO_P_NO, p_no)
    cash_resp = cash_mod.func_kanougaku_genbutsu(p_no, dic_login_property, dic_url_info.get("sJsonOfmt"))
    if cash_resp.get("p_errno") not in ("0", 0):
        raise RuntimeError(f"買付可能額の取得に失敗: {cash_resp.get('p_err')}")
    cash = float(cash_resp.get("sSummaryGenkabuKaituke") or 0)

    # 3. 保有株の評価額合計を取得
    holdings_mod = _load_module(os.path.join(BASE_DIR, "e_api_get_genbutu_kabu_list_pubkey.py"), "_loss_guard_holdings")
    p_no = cash_mod.func_get_p_no(FNAME_INFO_P_NO) + 1
    cash_mod.func_save_p_no(FNAME_INFO_P_NO, p_no)
    holdings_resp = holdings_mod.func_get_genbutu_kabu_list(p_no, "", dic_login_property, dic_url_info.get("sJsonOfmt"))
    if holdings_resp.get("p_errno") not in ("0", 0):
        raise RuntimeError(f"保有株一覧の取得に失敗: {holdings_resp.get('p_err')}")
    stock_value = float(holdings_resp.get("sTotalGaisanHyoukagakuGoukei") or 0)

    return cash + stock_value


def main() -> int:
    if os.path.exists(STOP_PATH):
        print("[loss_limit_guard] 既にSTOPファイルが存在します。発注は行われません。")
        return 1

    try:
        total_assets = fetch_total_assets()
    except Exception as e:
        print(f"[loss_limit_guard] 資産取得に失敗したため、安全側に倒して停止します: {type(e).__name__}: {e}")
        return 1

    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    if os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, encoding="utf-8") as f:
            baseline = json.load(f)
        base_assets = baseline["total_assets"]
        drop_pct = 1 - (total_assets / base_assets) if base_assets > 0 else 0.0
        drop_yen = base_assets - total_assets
        print(f"[loss_limit_guard] 基準値={base_assets:,.0f}円 現在={total_assets:,.0f}円 "
              f"下落率={drop_pct*100:.1f}% 下落額={drop_yen:,.0f}円")
        if drop_pct >= THRESHOLD_PCT:
            with open(STOP_PATH, "w", encoding="utf-8") as f:
                f.write(f"loss_limit_guard: 基準値比-{drop_pct*100:.1f}%({drop_yen:,.0f}円)で"
                         f"閾値(-{THRESHOLD_PCT*100:.0f}%)を超過したため停止 "
                         f"{dt.datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()}\n")
            print("[loss_limit_guard] 損失上限を超過。STOPファイルを作成し停止します。")
            return 1
        print("[loss_limit_guard] 損失上限内。発注を続行してよい。")
        return 0
    else:
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump({"total_assets": total_assets, "recorded_at": dt.datetime.now(ZoneInfo("Asia/Tokyo")).isoformat()},
                       f, ensure_ascii=False, indent=2)
        print(f"[loss_limit_guard] 初回実行。基準値{total_assets:,.0f}円を記録しました。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
