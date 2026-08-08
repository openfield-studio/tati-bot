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
# 機能: 注文約定一覧取得
# ==================================================
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
# --- 利用時に変数を設定してください -------------------------------------------
# コマンド用パラメーター -------------------    

S_ORDER_ISSUE_CODE = ''    # 銘柄コード     ''：指定なし の場合、一覧全体を取得する。

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
# p14/46 No.13 CLMOrderList を参照してください。
#
# 13 CLMOrderList
#  1	sCLMID	メッセージＩＤ	char*	I/O	"CLMOrderList"
#  2	sIssueCode	銘柄コード	char[12]	I/O	銘柄コード（6501 等）
#  3	sSikkouDay	注文執行予定日	char[8]	I/O	YYYYMMDD  CLMKabuCorrectOrder、CLMKabuCancelOrder、CLMOrderListDetail におけるsEigyouDayと同値
#  4	sOrderSyoukaiStatus	注文照会状態	char[1]	I/O	値無し：指定なし。 1：未約定、2：全部約定、3：一部約定、4：訂正取消(可能な注文）、5：未約定 + 一部約定
#  5	sResultCode	結果コード	char[9]	O	０：ＯＫ、０以外：CLMMsgTable.sMsgIdで検索しテキストを表示。 0～999999999、左詰め、マイナスの場合なし
#  6	sResultText	結果テキスト	char[512]	O	ShiftJis
#  7	sWarningCode	警告コード	char[9]	O	０：ＯＫ、０以外：CLMMsgTable.sMsgIdで検索しテキストを表示。 0～999999999、左詰め、マイナスの場合なし
#  8	sWarningText	警告テキスト	char[512]	O	ShiftJis
#  9	aOrderList	注文リスト （※項目数に増減がある場合は、右記のカラム数も変更すること）	char[17]	O	以下レコードを配列で設定
# 10-1	sOrderWarningCode	警告コード	char[9]	O	０：ＯＫ、０以外：CLMMsgTable.sMsgIdで検索しテキストを表示。0～999999999、左詰め、マイナスの場合なし
# 11-2	sOrderWarningText	警告テキスト	char[512]	O	ShiftJis
# 12-3	sOrderOrderNumber	注文番号	char[8]	O	0～99999999、左詰め、マイナスの場合なし
# 13-4	sOrderIssueCode	銘柄コード	char[12]	O	-
# 14-5	sOrderSizyouC	市場	char[2]	O	00：東証
# 15-6	sOrderZyoutoekiKazeiC	譲渡益課税区分	char[1]	O	1：特定、3：一般、5：NISA
# 16-7	sGenkinSinyouKubun	現金信用区分	char[1]	O	0：現物、2：新規(制度信用6ヶ月)、4：返済(制度信用6ヶ月)、6：新規(一般信用6ヶ月)、8：返済(一般信用6ヶ月)
# 17-8	sOrderBensaiKubun	弁済区分	char[2]	O	00：なし、26：制度信用6ヶ月、29：制度信用無期限、36：一般信用6ヶ月、39：一般信用無期限
# 18-9	sOrderBaibaiKubun	売買区分	char[1]	O	1：売、3：買、5：現渡、7：現引
# 19-10	sOrderOrderSuryou	注文株数	char[13]	O	照会機能仕様書 ２－７．（３）、（１）一覧 No.12。 0～9999999999999、左詰め、マイナスの場合なし
# 20-11	sOrderCurrentSuryou	有効株数	char[13]	O	0～9999999999999、左詰め、マイナスの場合なし
# 21-12	sOrderOrderPrice	注文単価	char[14]	O	0.0000～999999999.9999、左詰め、マイナスの場合なし、小数点以下桁数切詰
# 22-13	sOrderCondition	執行条件	char[1]	O	0：指定なし、2：寄付、4：引け、6：不成
# 23-14	sOrderOrderPriceKubun	注文値段区分	char[1]	O	△：未使用、 1：成行、2：指値、3：親注文より高い、4：親注文より低い
# 24-15	sOrderGyakusasiOrderType	逆指値注文種別	char[1]	O	0：通常、1：逆指値、2：通常＋逆指値
# 25-16	sOrderGyakusasiZyouken	逆指値条件	char[14]	O	0.0000～999999999.9999、左詰め、マイナスの場合なし、小数点以下桁数切詰
# 26-17	sOrderGyakusasiKubun	逆指値値段区分	char[1]	O	△：未使用、 0：成行、1：指値
# 27-18	sOrderGyakusasiPrice	逆指値値段	char[14]	O	0.0000～999999999.9999、左詰め、マイナスの場合なし、小数点以下桁数切詰
# 28-19	sOrderTriggerType	トリガータイプ	char[1]	O	0：未トリガー, 1：自動, 2：手動発注, 3：手動失効。 初期状態は「0」で、トリガー発火後は「1/2/3」のどれかに遷移する
# 29-20	sOrderTatebiType	建日種類	char[1]	O	△：指定なし、 1：個別指定、2：建日順、3：単価益順、4：単価損順
# 30-21	sOrderZougen	リバース増減値	char[14]	O	項目は残すが使用しない
# 31-22	sOrderYakuzyouSuryo	成立株数	char[13]	O	0～9999999999999、左詰め、マイナスの場合なし
# 32-23	sOrderYakuzyouPrice	成立単価	char[14]	O	照会機能仕様書 ２－７．（３）、（１）一覧 No.16。 0.0000～999999999.9999、左詰め、マイナスの場合なし、小数点以下桁数切詰
# 33-24	sOrderUtidekiKbn	内出来区分	char[1]	O	△：約定分割以外、 2：約定分割
# 34-25	sOrderSikkouDay	執行日	char[8]	O	YYYYMMDD
# 35-26	sOrderStatusCode	状態コード	char[2]	O	
                                                                #[逆指値]、[通常+逆指値]注文時以外の状態
                                                                #0：受付未済
                                                                #1：未約定
                                                                #2：受付エラー
                                                                #3：訂正中
                                                                #4：訂正完了
                                                                #5：訂正失敗
                                                                #6：取消中
                                                                #7：取消完了
                                                                #8：取消失敗
                                                                #9：一部約定
                                                                #10：全部約定
                                                                #11：一部失効
                                                                #12：全部失効
                                                                #13：発注待ち
                                                                #14：無効
                                                                #15：切替注文
                                                                #16：切替完了
                                                                #17：切替注文失敗
                                                                #19：繰越失効
                                                                #20：一部障害処理
                                                                #21：障害処理
                                                                #[逆指値]、[通常+逆指値]注文時の状態
                                                                #15：逆指注文(切替中)
                                                                #16：逆指注文(未約定)
                                                                #17：逆指注文(失敗)
                                                                #50：発注中 
# 36-27	sOrderStatus	状態	char[20]	O	
# 37-28	sOrderYakuzyouStatus	約定ステータス	char[2]	O	0：未約定、1：一部約定、2：全部約定、3：約定中
# 38-29	sOrderOrderDateTime	注文日付	char[14]	O	YYYYMMDDHHMMSS,00000000000000
# 39-30	sOrderOrderExpireDay	有効期限	char[8]	O	YYYYMMDD,00000000
# 40-31	sOrderKurikosiOrderFlg	繰越注文フラグ	char[1]	O	0：当日注文、1：繰越注文、2：無効
# 41-32	sOrderCorrectCancelKahiFlg	訂正取消可否フラグ	char[1]	O	0：可(取消、訂正)、1：否、2：一部可(取消のみ)
# 42-33	sGaisanDaikin	概算代金	char[16]	O	-999999999999999～9999999999999999、左詰め、マイナスの場合あり


def func_get_orderlist(
                            int_p_no,
                            str_sOrderIssueCode, 
                            dic_login_property, 
                            str_sJsonOfmt
                        ):
    """ --------------------------
    機能: 注文約定一覧の取得
    返値: API応答（辞書型）
    引数1: p_no
    引数2: 銘柄コード（銘柄コードは省略可。''：指定なし の場合、一覧全体を取得する。）  
    引数3: sJsonOfmt サポートへの問い合わせは、sJsonOfmt:'5'を指定した送信電文と受信電文でお願いします。
    備考:    
    """
    dic_req_item = {
        'p_no': str(int_p_no),
        'p_sd_date': func_p_sd_date(),   
        'sCLMID': 'CLMOrderList',               # 注文約定一覧を指定。
        'sIssueCode': str_sOrderIssueCode,      # 銘柄コード     ''：指定なし の場合、一覧全体を取得する。
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
    print('-- 注文約定一覧の取得 -------------------------------------------------------------')
    dic_return = func_get_orderlist(
                                    my_p_no,
                                    S_ORDER_ISSUE_CODE,
                                    dic_login_property,
                                    dic_url_info.get("sJsonOfmt")
                                )
    # 送信項目、戻り値の解説は、マニュアル「立花証券・ｅ支店・ＡＰＩ（ｖ〇）、REQUEST I/F、機能毎引数項目仕様」
    # p14/46 No.13 CLMOrderList を参照してください。
    
    if dic_return is not None:
        print("結果コード= ", dic_return.get("sResultCode"))           # 5
        print("結果テキスト= ", dic_return.get("sResultText"))  # 6
        dic_aOrderList = dic_return.get("aOrderList")
        if dic_aOrderList is not None:
            print('注文リスト= aOrderList')
            print('件数:', len(dic_aOrderList))
            print()
        
            # 'aOrderList'の返値の処理。
            # データ形式は、"aOrderList":[{...},{...}, ... ,{...}]
            for i in range(len(dic_aOrderList)):
                print('No.', i+1, '---------------')
                print('警告コード:\t', dic_aOrderList[i].get('sOrderWarningCode'))
                print('警告テキスト:\t', dic_aOrderList[i].get('sOrderWarningText'))
                print('注文番号:\t', dic_aOrderList[i].get('sOrderOrderNumber'))
                print('銘柄コード:\t', dic_aOrderList[i].get('sOrderIssueCode'))
                print('市場:\t', dic_aOrderList[i].get('sOrderSizyouC'))
                print('譲渡益課税区分:\t', dic_aOrderList[i].get('sOrderZyoutoekiKazeiC'))
                print('現金信用区分:\t', dic_aOrderList[i].get('sGenkinSinyouKubun'))
                print('弁済区分:\t', dic_aOrderList[i].get('sOrderBensaiKubun'))
                print('売買区分:\t', dic_aOrderList[i].get('sOrderBaibaiKubun'))
                print('注文株数:\t', dic_aOrderList[i].get('sOrderOrderSuryou'))
                print('有効株数:\t', dic_aOrderList[i].get('sOrderCurrentSuryou'))
                print('注文単価:\t', dic_aOrderList[i].get('sOrderOrderPrice'))
                print('執行条件:\t', dic_aOrderList[i].get('sOrderCondition'))
                print('注文値段区分:\t', dic_aOrderList[i].get('sOrderOrderPriceKubun'))
                print('逆指値注文種別:\t', dic_aOrderList[i].get('sOrderGyakusasiOrderType'))
                print('逆指値条件:\t', dic_aOrderList[i].get('sOrderGyakusasiZyouken'))
                print('逆指値値段区分:\t', dic_aOrderList[i].get('sOrderGyakusasiKubun'))
                print('逆指値値段:\t', dic_aOrderList[i].get('sOrderGyakusasiPrice'))
                print('トリガータイプ:\t', dic_aOrderList[i].get('sOrderTriggerType'))
                print('建日種類:\t', dic_aOrderList[i].get('sOrderTatebiType'))
                print('リバース増減値:\t', dic_aOrderList[i].get('sOrderZougen'))
                print('成立株数:\t', dic_aOrderList[i].get('sOrderYakuzyouSuryo'))
                print('成立単価:\t', dic_aOrderList[i].get('sOrderYakuzyouPrice'))
                print('内出来区分:\t', dic_aOrderList[i].get('sOrderUtidekiKbn'))
                print('執行日:\t', dic_aOrderList[i].get('sOrderSikkouDay'))
                print('状態:\t', dic_aOrderList[i].get('sOrderStatus'))
                print('約定ステータス:\t', dic_aOrderList[i].get('sOrderYakuzyouStatus'))
                print('注文日付:\t', dic_aOrderList[i].get('sOrderOrderDateTime'))
                print('有効期限:\t', dic_aOrderList[i].get('sOrderOrderExpireDay'))
                print('繰越注文フラグ:\t', dic_aOrderList[i].get('sOrderKurikosiOrderFlg'))
                print('訂正取消可否フラグ:\t', dic_aOrderList[i].get('sOrderCorrectCancelKahiFlg'))
                print('概算代金:\t', dic_aOrderList[i].get('sGaisanDaikin'))
                print()
                
           
    print()
    print('p_errno', dic_return.get('p_errno'))
    print('p_err', dic_return.get('p_err'))
    # 仮想URLが無効になっている場合
    if dic_return.get('p_errno') == '2':
        print()    
        print("仮想URLが有効ではありません。")
        print("電話認証 + e_api_login_tel.py実行")
        print("を再度行い、新しく仮想URL（1日券）を取得してください。")

    print()    
    print()    
    # "p_no"を保存する。
    func_save_p_no(FNAME_INFO_P_NO, my_p_no)
    
