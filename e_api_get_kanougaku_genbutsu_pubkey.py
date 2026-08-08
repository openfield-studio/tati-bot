# -*- coding: utf-8 -*-
# Copyright (c) 2021 Tachibana Securities Co., Ltd. All rights reserved.

# 2021.07.08,   yo.
# 2022.10.20 reviced,   yo.
# 2025.07.27 reviced,   yo.
# 2026.05.30 reviced,   yo.
#
# 立花証券ｅ支店ＡＰＩ利用のサンプルコード
#
# 動作確認
# Python 3.13.5 / debian13
# API v4r9
#
# 利用方法: 
# 事前に「e_api_login_pubkey.py」を実行して、仮想URL等を取得しておいてください。
# 実行は「e_api_login_pubkey.py」と同じディレクトリで行ってください。
#
# ------------------------------------------------------------------
#
# APIの基本設計について
# 
# 本APIは、プログラミング初心者や非ITエンジニアの方にも
# 利用しやすいよう、URLにJSON形式のパラメーターを付加して
# 送信する独自方式を採用しています。
# 
# 一般的なWeb APIとは異なる構成ですが、
# HTTPヘッダーやPOSTデータなどの知識を最小限に
# 抑えながら利用できることを重視しています。
# 
# このため、本APIは、URLとJSON文字列を組み立てて
# 送信するだけで利用でき、特別な知識を必要とせず、
# 各種スクリプト言語からも実装しやすいことを
# 優先した設計となっています。
#  
# ------------------------------------------------------------------
# 
#  
# == ご注意: ========================================
#   本番環境にに接続した場合、実際に市場に注文が出ます。
#   市場で約定した場合取り消せません。
# ==================================================
#
# 機能: 現物可能額取得
#

import urllib3
import datetime
import json
import os
import urllib.parse
from zoneinfo import ZoneInfo


# =========================================================================
# --- 設定項目（定数定義:セットアップマニュアルに完全準拠） ---
# =========================================================================
FNAME_URL_INFO = "file_url_info.txt"                # API接続情報ファイル
# FNAME_PASSWD2 = "./.auth/file_pwd2.txt"              # 第二パスワード保存ファイル
FNAME_LOGIN_RESPONSE = "./.auth/file_login_response.txt"  # ログイン応答保存先
FNAME_INFO_P_NO = "file_info_p_no.txt"              # p_no保存ファイル

# --- 通信堅牢化のための設定項目 ---
API_TIMEOUT_SECONDS = 15.0  # タイムアウト時間（秒）: 応答がない場合15秒で切り上げる
MAX_RETRY_COUNT = 3         # 最大リトライ回数: 通信エラー時に自動再試行する回数
RETRY_INTERVAL_SECONDS = 5  # リトライ間隔（秒）: 再試行する前に待機する時間
# =========================================================================


# --- 共通ユーティリティ関数 ----------------------------------------------

def func_p_sd_date():
    """
    機能: システム時刻を"p_sd_date"の書式の文字列で返す。
    返値: "p_sd_date"の書式の文字列。 API規定書式 "YYYY.MM.DD-hh:mm:ss.sss"
    引数1: なし
    備考: 
        日本標準時（Japan Standard Time、JST）を利用のこと。
    """
    dt_now = datetime.datetime.now(
        # 日本標準時（Japan Standard Time、JST）を利用
        ZoneInfo("Asia/Tokyo")
    )
    # 年.月.日-時:分:秒 の部分を作成
    str_date = dt_now.strftime("%Y.%m.%d-%H:%M:%S")
    
    # マイクロ秒（6桁ゼロ埋め）から先頭の3桁を切り出してミリ秒を作成
    str_micro = f"{dt_now.microsecond:06d}"
    str_ms = str_micro[0:3]
    
    # ドットで結合してAPI規定書式を完成
    return str_date + "." + str_ms


def func_replace_urlencode(str_input):
    """
    URLエンコードを行う。

    URLでは、スペースや「&」「+」「?」などの記号が
    特別な意味を持つため、そのまま送信できない場合がある。
    そのため、これらの文字を「%xx」形式へ変換する。

    例:
        "A B+C" → "A%20B%2BC"

    本サンプルでは Python標準ライブラリの
    urllib.parse.quote() を利用してURLエンコードを行う。

    他言語へ移植する場合も、自前で変換処理を作成するのではなく、
    各言語が提供する標準のURLエンコード関数を利用することを推奨する。

    主な対応例:
        Python      : urllib.parse.quote()
        Java        : java.net.URLEncoder.encode()
        C#          : Uri.EscapeDataString()
        JavaScript  : encodeURIComponent()
        Go          : url.QueryEscape()

    Parameters
    ----------
    str_input : str
        URLエンコード対象文字列

    Returns
    -------
    str
        URLエンコード後の文字列
    """
    return urllib.parse.quote(str_input, safe='')


def func_read_from_file(str_fname):
    """ファイルから文字情報を一括読み込み（BOMを排除）"""
    str_read = ''
    try:
        # utf-8-sig を指定してBOMを自動的に排除しファイルを開く
        with open(str_fname, 'r', encoding='utf-8-sig') as fin:
            while True:
                line = fin.readline()
                if not line:
                    break
                str_read = str_read + line
        return str_read
    except IOError as e:
        print(f"[エラー] ファイルを読み込めません: {str_fname}")
        raise e


def func_write_to_file(str_fname_output, str_data):
    """ファイルに書き込み、権限を所有者のみ(600)に制限"""
    try:
        # 出力先フォルダの存在を確認し、存在しない場合は自動作成
        str_dir = os.path.dirname(str_fname_output)
        if str_dir and not os.path.exists(str_dir):
            os.makedirs(str_dir, exist_ok=True)

        # データをファイルへ書き込み
        with open(str_fname_output, 'w', encoding='utf-8') as fout:
            fout.write(str_data)
        
        # パーミッションを600（所有者のみ読み書き可能）に制限
        os.chmod(str_fname_output, 0o600)
    except IOError as e:
        print(f"[エラー] ファイルに書き込めません: {str_fname_output}")
        raise e


def func_get_url_info(fname):
    """
    file_url_info.txt からAPI接続設定を取得

    機能: API接続情報をファイルから取得し辞書型で返す
    引数1: 接続先情報を保存したファイル名: fname_url_info

    サポートへの問い合わせは、sJsonOfmt:'5'でお願いします。
    """
    str_url_info = func_read_from_file(fname)
    # JSON形式の文字列を辞書型で取り出す
    return  json.loads(str_url_info)    


def func_get_login_response(str_fname):
    '''
    ログインレスポンスを取得
    '''
    str_login_response = func_read_from_file(str_fname)
    dic_login_response = json.loads(str_login_response)
    return dic_login_response
    

def func_get_p_no(fname):
    """ 
    機能: p_noをファイルから取得する
    引数1: p_noを保存したファイル名（fname_info_p_no = "e_api_info_p_no.txt"）
    """
    str_p_no_info = func_read_from_file(fname)
    # JSON形式の文字列を辞書型で取り出す
    json_p_no_info = json.loads(str_p_no_info)
    int_p_no = int(json_p_no_info.get('p_no'))
    return int_p_no


def func_save_p_no(str_fname_output, int_p_no):
    """p_noを保存するためのJSONファイルを生成"""
    p_no_dict = {"p_no": str(int_p_no)}
    json_data = json.dumps(p_no_dict, indent=4)
    func_write_to_file(str_fname_output, json_data)
    print(f'現在の "p_no" を保存しました。 p_no = {int_p_no} -> {str_fname_output}')


def func_make_url_request_from_dic(
                                    auth_flg, \
                                    url_target, \
                                    work_dic_req
                                ) :
    '''
    API問合せ用完全URL（クエリパラメータ付）を作成
    
    本APIは一般的なREST APIとは異なり、
    JSONをHTTPボディではなくURLに付加して送信します。
    詳細はAPIマニュアル参照。
    備考：
        サポートへの問い合わせを考慮し、項目ごとの改行とタブを入れてあります。
    '''
    str_url = url_target
    if auth_flg:
        str_url = urllib.parse.urljoin(str_url, 'auth/')
    json_param = json.dumps(work_dic_req, indent=4, ensure_ascii=False)
    return f"{str_url}?{json_param}"


def func_api_req(str_request_method, str_url): 
    """
    APIリクエストの送信と、Shift-JIS応答のデコード（リトライ・タイムアウト対応版）
    """
    # HTTP通信ライブラリ urllib3 を利用します。
    #
    # requests ライブラリでも同様の処理は可能ですが、
    # 本サンプルでは APIサーバーへの接続処理が分かりやすいよう、
    # より基本的な urllib3 を利用しています。
    #
    # 他言語へ移植する場合も、
    # 「HTTPクライアント生成 → リクエスト送信 → レスポンス受信」
    # の流れを対応するライブラリへ置き換えてください。

    print('--- 送信電文 -------------------------------------------')
    print(str_url)

    # 接続および読み込みのタイムアウト時間を設定
    timeout_config = urllib3.Timeout(connect=API_TIMEOUT_SECONDS, read=API_TIMEOUT_SECONDS)
    http = urllib3.PoolManager()
    
    response_data = None
    status_code = None

    # 最大試行回数に達するまで通信をリトライ
    for attempt in range(1, MAX_RETRY_COUNT + 1):
        try:
            # 2回目以降の試行（再接続）の前に、指定されたインターバル時間待機
            if attempt > 1:
                print(f"[{attempt}/{MAX_RETRY_COUNT} 回目] 再接続を試みます...（{RETRY_INTERVAL_SECONDS}秒待機）")
                time.sleep(RETRY_INTERVAL_SECONDS)

            req = http.request(str_request_method, str_url, timeout=timeout_config)
            status_code = req.status
            response_data = req.data
            break  # 正常に通信できた場合はループを抜ける

        except (TimeoutError, MaxRetryError) as ce:
            print(f"\n[警告] 通信エラーが発生しました (試行: {attempt}/{MAX_RETRY_COUNT})")
            print(f"エラー詳細: {ce}")
            
            # 最大リトライ回数を超えて失敗した場合はConnectionErrorを発生
            if attempt == MAX_RETRY_COUNT:
                raise ConnectionError(
                    f"APIサーバーへの接続に規定回数失敗しました。サーバーがメンテナンス中か、停止している可能性があります。\n"
                    f"設定されたタイムアウト時間: {API_TIMEOUT_SECONDS}秒"
                )
        except Exception as ex:
            print(f"\n[警告] 予期せぬネットワーク例外が発生しました: {ex}")
            if attempt == MAX_RETRY_COUNT:
                raise ex

    print(f"HTTP Status: {status_code}")

    # 受信した電文をShift-JISからUTF-8へデコード（不正なバイトは無視）
    str_response = response_data.decode("shift-jis", errors="ignore")
    print('--- 受信電文 -------------------------------------------')
    print(str_response)
    print('--------------------------------------------------------')

    return str_response


# --- 共通ユーティリティ関数 ----------------------------------------------




# 参考資料（必ず最新の資料を参照してください。）
#マニュアル
#「立花証券・ｅ支店・ＡＰＩ（v4r2）、REQUEST I/F、機能毎引数項目仕様」
# (api_request_if_clumn_v4r2.pdf)
# p13/46 No.10 CLMZanKaiKanougaku 項目1-11 を参照してください。
#
# 10 CLMZanKaiKanougaku
#  1 sCLMID	メッセージＩＤ          char*	    I/O	"CLMZanKaiKanougaku"
#  2 sIssueCode	銘柄コード          char[12]	I/O	銘柄コード（6501 等）
#  3 sSizyouC	市場	            char[2]     I/O	00:東証"
#  4 sResultCode	結果コード      char[9]     O	0:ＯＫ、0以外:CLMMsgTable.sMsgIdで検索しテキストを表示。 0～999999999、左詰め、マイナスの場合なし
#  5 sResultText	結果テキスト    char[512]   O	ShiftJis"
#  6 sWarningCode	警告コード	    char[9]	    O	0:ＯＫ、0以外:CLMMsgTable.sMsgIdで検索しテキストを表示。 0～999999999、左詰め、マイナスの場合なし
#  7 sWarningText	警告テキスト	char[512]	O	ShiftJis"
#  8 sSummaryUpdate	更新日時	    char[12]	O	YYYYMMDDHHMM 照会機能仕様書 ２－４．（３）、(以下は標準WebになくRich-I/Fにある項目) No.1
#  9 sSummaryGenkabuKaituke	株式現物買付可能額	        char[16]	O	照会機能仕様書 ２－４．（３）、（A）現物取引 - 買付注文 - 通常 No.4。 0～9999999999999999、左詰め、マイナスの場合なし
# 10 sSummaryNisaKaitukeKanougaku	NISA口座買付可能額	char[16]	O	照会機能仕様書 ２－４．（３）、（A）現物取引 - 買付注文 - 通常 No.5。 0～9999999999999999、左詰め、マイナスの場合なし
# 11 sHusokukinHasseiFlg	不足金発生フラグ	        char[1]	    O	照会機能仕様書 ２－４．（３）、(以下は標準WebになくRich-I/Fにある項目) No.2。 不足金発生フラグ、'0': 未発生, '1': 発生

def func_kanougaku_genbutsu(
                                int_p_no, 
                                dic_login_property, 
                                str_sJsonOfmt
                            ):
    """ --------------------------
    機能: 現物買い付け可能額取得 sCLMID: CLMZanKaiKanougaku
    返値: API応答（辞書型）
    引数1: p_no
    引数2: sJsonOfmt
    引数3: ログインレスポンス。辞書型。
    備考:
        送信項目の解説は、
        「立花証券・ｅ支店・ＡＰＩ専用ページ」マニュアル
        3.業務機能（REQUEST I/F）
        7.買余力      sCLMID	機能ＩＤ	CLMZanKaiKanougaku
        を参照してください。 
    """
    dic_req_item = {
        'p_no': str(int_p_no),
        'p_sd_date': func_p_sd_date(),   
        'sCLMID': 'CLMZanKaiKanougaku',        # 買余力を指示。
        'sJsonOfmt': str_sJsonOfmt             # サポートへの問い合わせは、sJsonOfmt:'5'を指定した送信電文と受信電文でお願いします。
    }

    # URL文字列の作成
    str_url = func_make_url_request_from_dic(
                                                False, \
                                                dic_login_property.get('sUrlRequest'), \
                                                dic_req_item
                                            )

    # リクエストメソッドの指定('GET'、'POST'どちらでも動作します。)
    str_api_response = func_api_req('GET', str_url)

    # apiの返り値（JSON形式の文字列）を辞書型で取り出す
    dic_api_response = json.loads(str_api_response)

    return dic_api_response
    
    
# ======================================================================================================
# ==== プログラム始点 =================================================================================
# ======================================================================================================

if __name__ == "__main__":
    
    # 接続情報をファイルから読み込む。
    dic_url_info = func_get_url_info(FNAME_URL_INFO)
    
    # # 22.第二パスワード
    # # APIでは第２暗証番号を省略できない。 関連資料:「立花証券・e支店・API、インターフェース概要」の「3-2.ログイン、ログアウト」参照
    # # URLに「#」「+」「/」「:」「=」などの記号を利用した場合エラーとなるため、URLエンコーディングを行う。
    # # APIへの入力文字列（特にパスワードで記号を利用している場合）で注意が必要。
    # #   '#' →   '%23'
    # #   '+' →   '%2B'
    # #   '/' →   '%2F'
    # #   ':' →   '%3A'
    # #   '=' →   '%3D'
    # my_sSecondPassword = func_read_from_file(fname_pwd2).strip()
    # my_account_property.sSecondPassword = func_replace_urlecnode(my_sSecondPassword)        # urlエンコーディング
    
    # ログイン応答を保存した「file_login_response.txt」から、仮想URLと課税flgを取得
    dic_login_property = func_get_login_response(FNAME_LOGIN_RESPONSE)

    # 現在（前回利用した）のp_noをファイルから取得する
    my_p_no = func_get_p_no(FNAME_INFO_P_NO)
    my_p_no = my_p_no + 1
    # 更新した"p_no"を保存する。
    func_save_p_no(FNAME_INFO_P_NO, my_p_no)

    print()
    print('--- 現物買余力の照会 -------------------------------------------------------------')
    dic_return = func_kanougaku_genbutsu(
                                        my_p_no, 
                                        dic_login_property,
                                        dic_url_info.get("sJsonOfmt")
                                    )
    
    if dic_return is not None:
        print('結果')
        print('更新日時= ', dic_return.get("sSummaryUpdate"))     # 株式現物買付可能額
        print('株式現物買付可能額= ', dic_return.get("sSummaryGenkabuKaituke"))     # 株式現物買付可能額
        print('NISA口座買付可能額= ', dic_return.get("sSummaryNisaKaitukeKanougaku"))     # NISA口座買付可能額

    print()    
    print('p_errno', dic_return.get('p_errno'))
    print('p_err', dic_return.get('p_err'))
    # 仮想URLが無効になっている場合
    if dic_return.get('p_errno') == '2':
        print()    
        print("仮想URLが有効ではありません。")
        print("ログイン情報は有効ですか。: ", fname_login_response)
        
    print()    
    print()    
    # 最終的な"p_no"を保存する。
    func_save_p_no(FNAME_INFO_P_NO, my_p_no)
       
