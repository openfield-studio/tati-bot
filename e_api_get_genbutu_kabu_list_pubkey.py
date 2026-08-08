# -*- coding: utf-8 -*-
# Copyright (c) 2026 Tachibana Securities Co., Ltd. All rights reserved.

# 2021.07.08,   yo.
# 2022.10.20 reviced,   yo.
# 2025.07.27 reviced,   yo.
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
# 機能: 現物株預り一覧取得を行ないます。
# 

import urllib3
import datetime
import json
import os
import urllib.parse
from zoneinfo import ZoneInfo


# =========================================================================
# --- 設定項目（定数定義） ---
# =========================================================================
# コマンド用パラメーター -------------------    
S_ISSUE_CODE  = ''     # 銘柄コード 例:9984。 '':省略時全銘柄取得

# --- 共通設定項目 ------------------------------------------------------------
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
# p8/46 No.8 CLMGenbutuKabuList を参照してください。
#
#   8 CLMGenbutuKabuList
#  1	sCLMID	メッセージＩＤ	char*	I/O	CLMGenbutuKabuList
#  2	sIssueCode	銘柄コード	char[12]	I/O	銘柄コード（6501 等）
#  3	sResultCode	結果コード	char[9]	O	業務処理．エラーコード 0：正常、5桁数字：「結果テキスト」に対応するエラーコード
#  4	sResultText	結果テキスト	char[512]	O	ShiftJis  「結果コード」に対応するテキスト
#  5	sWarningCode	警告コード	char[9]	O	０：ＯＫ、０以外：CLMMsgTable.sMsgIdで検索しテキストを表示。0～999999999、左詰め、マイナスの場合なし
#  6	sWarningText	警告テキスト	char[512]	O	ShiftJis
#  7	sTokuteiGaisanHyoukagakuGoukei	概算評価額合計(特定口座残高)	char[16]	O	照会機能仕様書 ２－１．（３）、（１）残高 No.1-1。0～9999999999999999、左詰め、マイナスの場合なし
#  8	sIppanGaisanHyoukagakuGoukei	概算評価額合計(一般口座残高)	char[16]	O	照会機能仕様書 ２－１．（３）、（１）残高 No.2-1。0～9999999999999999、左詰め、マイナスの場合なし
#  9	sNisaGaisanHyoukagakuGoukei	概算評価額合計(NISA口座残高)	char[16]	O	照会機能仕様書 ２－１．（３）、（１）残高 No.3-1。0～9999999999999999、左詰め、マイナスの場合なし
# 10	sTotalGaisanHyoukagakuGoukei	残高合計_概算評価額合計	char[16]	O	照会機能仕様書 ２－１．（３）、（１）残高 No.4。0～9999999999999999、左詰め、マイナスの場合なし
# 11	sTokuteiGaisanHyoukaSonekiGoukei	概算評価損益合計(特定口座残高)	char[16]	O	照会機能仕様書 ２－１．（３）、（１）残高 No.1-2。-999999999999999～9999999999999999、左詰め、マイナスの場合あり
# 12	sIppanGaisanHyoukaSonekiGoukei	概算評価損益合計(一般口座残高)	char[16]	O	照会機能仕様書 ２－１．（３）、（１）残高 No.2-2。-999999999999999～9999999999999999、左詰め、マイナスの場合あり
# 13	sNisaGaisanHyoukaSonekiGoukei	概算評価損益合計(NISA口座残高)	char[16]	O	照会機能仕様書 ２－１．（３）、（１）残高 No.3-2。-999999999999999～9999999999999999、左詰め、マイナスの場合あり
# 14	sTotalGaisanHyoukaSonekiGoukei	概算評価損益合計(残高合計)	char[16]	O	照会機能仕様書 ２－１．（３）、（１）残高 No.4-1。-999999999999999～9999999999999999、左詰め、マイナスの場合あり
# 15	aGenbutuKabuList	現物株リスト	char[17]	O	以下レコードを配列で設定
# 16-1	sUriOrderWarningCode	警告コード	char[9]	O	業務処理．ワーニングコード 0：正常、5桁数字：「警告テキスト」に対応するワーニングコード
# 17-2	sUriOrderWarningText	警告テキスト	char[512]	O	ShiftJis  「警告コード」に対応するテキスト
# 18-3	sUriOrderIssueCode	銘柄コード	char[12]	O	指定された銘柄に紐付く銘柄コード(銘柄マスタ(株式）に存在する銘柄コード）上限9桁
# 19-4	sUriOrderZyoutoekiKazeiC	口座	char[1]	O	譲渡益課税Ｃ(1：特定, 3：一般, 5：NISA)
# 20-5	sUriOrderZanKabuSuryou	残高株数	char[13]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.5。0～9999999999999、左詰め、マイナスの場合なし
# 21-6	sUriOrderUritukeKanouSuryou	売付可能株数	char[13]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.6。0～9999999999999、左詰め、マイナスの場合なし
# 22-7	sUriOrderGaisanBokaTanka	概算簿価単価	char[14]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.8。0.0000～999999999.9999、左詰め、マイナスの場合なし
# 23-8	sUriOrderHyoukaTanka	評価単価	char[14]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.9。0.0000～999999999.9999、左詰め、マイナスの場合なし、小数点以下桁数切詰
# 24-9	sUriOrderGaisanHyoukagaku	評価金額	char[16]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.10。0～9999999999999999、左詰め、マイナスの場合なし
# 25-10	sUriOrderGaisanHyoukaSoneki	評価損益	char[16]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.11。-999999999999999～9999999999999999、左詰め、マイナスの場合あり
# 26-11	sUriOrderGaisanHyoukaSonekiRitu	評価損益率	char[16]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.12。-999999999.99～9999999999.99、左詰め、マイナスの場合あり
# 27-12	sSyuzituOwarine	前日終値	char[14]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.13。0.0000～999999999.9999、左詰め、マイナスの場合なし、小数点以下桁数切詰
# 28-13	sZenzituHi	前日比	char[13]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.14。-9999999.9999～99999999.9999、左詰め、マイナスの場合あり、小数点以下桁数切詰めなし
# 29-14	sZenzituHiPer	前日比(%)	char[7]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.15。-999.99～999.99、左詰め、マイナスの場合あり、小数点以下桁数切詰めなし
# 30-15	sUpDownFlag	騰落率Flag	char[2]	O	照会機能仕様書 ２－１．（３）、（２）一覧 No.16 11段階のFlag
#   					01：+5.01  以上
#   					02：+3.01  ～+5.00
#   					03：+2.01  ～+3.00
#   					04：+1.01  ～+2.00
#   					05：+0.01  ～+1.00
#   					06：0 変化なし
#   					07：-0.01  ～-1.00
#   					08：-1.01  ～-2.00
#   					09：-2.01  ～-3.00
#   					10：-3.01  ～-5.00
#   					11：-5.01  以下
# 31-16	sNissyoukinKasikabuZan	証金貸株残	char[13]	O	0～9999999999999、左詰め、マイナスの場合なし




def func_get_genbutu_kabu_list(
                                    int_p_no,
                                    str_sIssueCode,
                                    dic_login_property, 
                                    str_sJsonOfmt
                                ):
    """ --------------------------
    機能: 現物株預り一覧取得
    返値: API応答（辞書型）
    引数1: p_no
    引数2: 銘柄コード（6501等、'':省略時全銘柄取得）
    引数3: class_login_property（request通番）, 口座属性クラス
    備考:
        銘柄コードは省略可。
    """
    dic_req_item = {
        'p_no': str(int_p_no),
        'p_sd_date': func_p_sd_date(),   
        'sCLMID': 'CLMGenbutuKabuList',         # 現物預かり一覧を指定。
        'sIssueCode': str_sIssueCode,           # 銘柄コード     ''：指定なし の場合、一覧全体を取得する。
        'sJsonOfmt': str_sJsonOfmt              # サポートへの問い合わせは、sJsonOfmt:'5'を指定した送信電文と受信電文でお願いします。
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
    
    # ログイン応答を保存した「file_login_response.txt」から、仮想URLと課税flgを取得
    dic_login_property = func_get_login_response(FNAME_LOGIN_RESPONSE)

    # 現在（前回利用した）のp_noをファイルから取得する
    my_p_no = func_get_p_no(FNAME_INFO_P_NO)
    my_p_no = my_p_no + 1
    # 更新した"p_no"を保存する。
    func_save_p_no(FNAME_INFO_P_NO, my_p_no)

    print()
    print('-- 現物株預り一覧 取得 -------------------------------------------------------------')
    dic_return = func_get_genbutu_kabu_list(
                                                my_p_no,
                                                S_ISSUE_CODE,
                                                dic_login_property,
                                                dic_url_info.get("sJsonOfmt")
                                            )
    # 送信項目、戻り値の解説は、マニュアル「立花証券・ｅ支店・ＡＰＩ（ｖ〇）、REQUEST I/F、機能毎引数項目仕様」
    # p8/46 No.8 CLMGenbutuKabuList を参照してください

    if dic_return is not None:
        print(' 1 メッセージＩＤ:\t', dic_return.get('sCLMID'))
        print(' 2 銘柄コード:\t', dic_return.get('sIssueCode'))
        print(' 3 結果コード:\t', dic_return.get('sResultCode'))
        print(' 4 結果テキスト:\t', dic_return.get('sResultText'))
        print(' 5 警告コード:\t', dic_return.get('sWarningCode'))
        print(' 6 警告テキスト:\t', dic_return.get('sWarningText'))
        print(' 7 概算評価額合計(特定口座残高):\t', dic_return.get('sTokuteiGaisanHyoukagakuGoukei'))
        print(' 8 概算評価額合計(一般口座残高):\t', dic_return.get('sIppanGaisanHyoukagakuGoukei'))
        print(' 9 概算評価額合計(NISA口座残高):\t', dic_return.get('sNisaGaisanHyoukagakuGoukei'))
        print('10 残高合計_概算評価額合計:\t', dic_return.get('sTotalGaisanHyoukagakuGoukei'))
        print('11 概算評価損益合計(特定口座残高):\t', dic_return.get('sTokuteiGaisanHyoukaSonekiGoukei'))
        print('12 概算評価損益合計(一般口座残高):\t', dic_return.get('sIppanGaisanHyoukaSonekiGoukei'))
        print('13 概算評価損益合計(NISA口座残高):\t', dic_return.get('sNisaGaisanHyoukaSonekiGoukei'))
        print('14 概算評価損益合計(残高合計):\t', dic_return.get('sTotalGaisanHyoukaSonekiGoukei'))
        print()
        print()
        
    print('==========================')
    list_aGenbutuKabuList = dic_return.get("aGenbutuKabuList")
    print('15 現物株リスト: = aGenbutuKabuList')
    print('件数:', len(list_aGenbutuKabuList))
    print()
    # 'aGenbutuKabuList'の返値の処理。
    # データ形式は、"aGenbutuKabuList":[{...},{...}, ... ,{...}]
    for i in range(len(list_aGenbutuKabuList)):
        print('No.', i+1, '---------------')
        print('16- 1 警告コード:\t', list_aGenbutuKabuList[i].get('sUriOrderWarningCode'))
        print('17- 2 警告テキスト:\t', list_aGenbutuKabuList[i].get('sUriOrderWarningText'))
        print('18- 3 銘柄コード:\t', list_aGenbutuKabuList[i].get('sUriOrderIssueCode'))
        print('19- 4 口座:\t', list_aGenbutuKabuList[i].get('sUriOrderZyoutoekiKazeiC'))
        print('20- 5 残高株数:\t', list_aGenbutuKabuList[i].get('sUriOrderZanKabuSuryou'))
        print('21- 7 売付可能株数:\t', list_aGenbutuKabuList[i].get('sUriOrderUritukeKanouSuryou'))
        print('22- 8 概算簿価単価:\t', list_aGenbutuKabuList[i].get('sUriOrderGaisanBokaTanka'))
        print('23- 9 評価単価:\t', list_aGenbutuKabuList[i].get('sUriOrderHyoukaTanka'))
        print('24-10 評価金額:\t', list_aGenbutuKabuList[i].get('sUriOrderGaisanHyoukagaku'))
        print('25-11 評価損益:\t', list_aGenbutuKabuList[i].get('sUriOrderGaisanHyoukaSoneki'))
        print('26-12 評価損益率:\t', list_aGenbutuKabuList[i].get('sUriOrderGaisanHyoukaSonekiRitu'))
        print('27-13 前日終値:\t', list_aGenbutuKabuList[i].get('sSyuzituOwarine'))
        print('28-14 前日比:\t', list_aGenbutuKabuList[i].get('sZenzituHi'))
        print('29-15 前日比(%):\t', list_aGenbutuKabuList[i].get('sZenzituHiPer'))
        print('30-16 騰落率Flag:\t', list_aGenbutuKabuList[i].get('sUpDownFlag'))
        print('31-17 証金貸株残:\t', list_aGenbutuKabuList[i].get('sNissyoukinKasikabuZan'))
        print()
        print()
    
        
            
    print()    
    print('p_errno', dic_return.get('p_errno'))
    print('p_err', dic_return.get('p_err'))
    # 仮想URLが無効になっている場合
    if dic_return.get('p_errno') == '2':
        print()    
        print("仮想URLが有効ではありません。")
        print("電話認証＋e_api_login_tel.py実行")
        print("を再度実行してください。")
        
    print()    
    print()    
    # "p_no"を保存する。
    func_save_p_no(FNAME_INFO_P_NO, my_p_no)
       
