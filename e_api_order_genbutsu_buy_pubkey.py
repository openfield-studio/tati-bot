# -*- coding: utf-8 -*-
# ============================================================
# 【tati-botプロジェクト注記・2026-08-08】
# このファイルは配置のみで、まだ一度も実行していない(未検証)。
# 実行前に必要な準備:
#   ・入金が完了していること
#   ・第2パスワードファイル(./.auth/file_pwd2.txt)の作成
#   ・本番環境への発注は取り消せないため、内容(銘柄コード・数量・価格・
#     執行条件)を必ず人間の目で確認してから実行すること
# trading_agents.pyへの正式な組み込みはまだ行っていない。
# ============================================================
#
# Copyright (c) 2021 Tachibana Securities Co., Ltd. All rights reserved.

# 2021.07.08,   yo.
# 2022.10.25 reviced,   yo.
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
# 機能: 現物買い注文を行ないます。
#
# 設定項目
# 10.銘柄コード。実際の銘柄コードを入れてください。
# 11.市場。  00:東証   現在(2021/07/01)、東証のみ可能。
# 13.執行条件。  0:指定なし、2:寄付、4:引け、6:不成。指し値は、0:指定なし。
# 14.注文値段。  *:指定なし、0:成行、上記以外は、注文値段。小数点については、関連資料:「立花証券・e支店・API、REQUEST I/F、マスタデータ利用方法」の「2-12. 呼値」参照。
# 15.注文数量。
# 
#
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
# コマンド用パラメーター -------------------    
# 現物 買い 注文パラメーターセット
S_ISSUE_CODE = '1306'  # 10.銘柄コード。実際の銘柄コードを入れてください。
S_SIZYOU_C = '00'      # 11.市場。  00:東証   現在(2021/07/01)、東証のみ可能。
S_CONDITION = '0'     # 13.執行条件。  0:指定なし、2:寄付、4:引け、6:不成。指し値は、0:指定なし。
S_ORDER_PRICE = '000'  # 14.注文値段。  *:指定なし、0:成行、上記以外は、注文値段。小数点については、関連資料:「立花証券・e支店・API、REQUEST I/F、マスタデータ利用方法」の「2-12. 呼値」参照。
S_ORDER_SURYOU = '100' # 15.注文数量。

# --- 以上設定項目 -------------------------------------------------------------------------

# --- 共通設定項目 ------------------------------------------------------------
FNAME_URL_INFO = "file_url_info.txt"                # API接続情報ファイル
FNAME_PASSWD2 = "./.auth/file_pwd2.txt"              # 第二パスワード保存ファイル
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



# 参考資料（必ず最新の資料を参照してください。）--------------------------
#マニュアル
#「立花証券・ｅ支店・ＡＰＩ（v4r2）、REQUEST I/F、機能毎引数項目仕様」
# (api_request_if_clumn_v4r2.pdf)
# p4-5/46 No.5 CLMKabuNewOrder を参照してください。
#
# 5 CLMKabuNewOrder
#  1   	sCLMID	メッセージＩＤ	char*	I/O	"CLMKabuNewOrder"
#  2   	sResultCode	結果コード	char[9]	O	業務処理．エラーコード 。0：正常、5桁数字：「結果テキスト」に対応するエラーコード 
#  3   	sResultText	結果テキスト	char[512]	O	ShiftJis  「結果コード」に対応するテキスト
#  4   	sWarningCode	警告コード	char[9]	O	業務処理．ワーニングコード。0：正常、5桁数字：「警告テキスト」に対応するワーニングコード
#  5   	sWarningText	警告テキスト	char[512]	O	ShiftJis  「警告コード」に対応するテキスト
#  6   	sOrderNumber	注文番号	char[8]	O	-
#  7   	sEigyouDay	営業日	char[8]	O	営業日（YYYYMMDD）
#  8   	sZyoutoekiKazeiC	譲渡益課税区分	char[1]	I	1：特定、3：一般、5：NISA
#  9   	sTategyokuZyoutoekiKazeiC	建玉譲渡益課税区分	char[1]	I	信用建玉における譲渡益課税区分（現引、現渡で使用）
#      					*：現引、現渡以外の取引
#      					1：特定
#      					3：一般
#      					5：NISA
# 10   	sIssueCode	銘柄コード	char[12]	I	銘柄コード（6501 等）
# 11   	sSizyouC	市場	char[2]	I	00：東証
# 12   	sBaibaiKubun	売買区分	char[1]	I	1：売、3：買、5：現渡、7：現引
# 13   	sCondition	執行条件	char[1]	I	0：指定なし、2：寄付、4：引け、6：不成
# 14   	sOrderPrice	注文値段	char[14]	I	*：指定なし
#      					0：成行
#      					上記以外は、注文値段
#      					小数点については、関連資料：「立花証券・ｅ支店・ＡＰＩ、REQUEST I/F、マスタデータ利用方法」の「２－１２． 呼値」参照
# 15   	sOrderSuryou	注文数量	char[13]	I	注文数量
# 16   	sGenkinShinyouKubun	現金信用区分	char[1]	I	0：現物
#      					2：新規(制度信用6ヶ月)
#      					4：返済(制度信用6ヶ月)
#      					6：新規(一般信用6ヶ月)
#      					8：返済(一般信用6ヶ月)
# 17   	sOrderExpireDay	注文期日	char[8]	I	0：当日、上記以外は、注文期日日(YYYYMMDD)[10営業日迄]
# 18   	sGyakusasiOrderType	逆指値注文種別	char[1]	I	0：通常
# 19   	sGyakusasiZyouken	逆指値条件	char[14]	I	0：指定なし
# 20   	sGyakusasiPrice	逆指値値段	char[14]	I	*：指定なし
# 21   	sTatebiType	建日種類	char[1]	I	*：指定なし（現物または新規） 
#      					1：個別指定
#      					2：建日順
#      					3：単価益順
#      					4：単価損順
# 22   	sSecondPassword	第二パスワード	char[48]	I	第二暗証番号
#      					''：第二暗証番号省略時
#      					関連資料：「立花証券・ｅ支店・ＡＰＩ、インターフェース概要」の「３－２．ログイン、ログアウト」参照
# 23   	sOrderUkewatasiKingaku	注文受渡金額	char[16]	O	注文受渡金額
# 24   	sOrderTesuryou	注文手数料	char[16]	O	注文手数料
# 25   	sOrderSyouhizei	注文消費税	char[16]	O	注文消費税
# 26   	sKinri	金利	char[9]	O	メモリ上のシステム市場弁済別取扱条件信用新規取引の場合
#      					0～999.99999：買方金利
#      					0～999.99999：売方金利
#      					0～999.99999：買方金利（翌営業日）
#      					0～999.99999：売方金利（翌営業日）
#      					-：信用新規取引でない場合
# 27   	sOrderDate	注文日時	char[14]	O	注文日時（YYYYMMDDHHMMSS）
# 28   	aCLMKabuHensaiData	返済リスト	char[17]	I	※返済で建日種類＝個別指定の場合必須、その他は不要
#      	※必要時は以下３項目を配列とし列挙する				
#   - 1	sTategyokuNumber		char[15]	I	新規建玉番号（CLMShinyouTategyokuListのsOrderTategyokuNumber）
#   - 2	sTatebiZyuni	建日順位	char[9]	I	建日順位
#   - 3	sOrderSuryou	注文数量	char[13]	I	注文数量
# --- 以上資料 --------------------------------------------------------

def func_set_sZyoutoekiKazeiC(str_sGenkinShinyouKubun, dic_login_property):
    """ 
    税区分: sZyoutoekiKazeiC
      ログインレスポンスの特定口座区分で設定を変える。
      現物: sTokuteiKouzaKubunGenbutu
      信用: sTokuteiKouzaKubunSinyou

    特定口座区分            →   譲渡益課税区分
      0：一般               →   3：一般
      1：特定源泉徴収なし   →   1：特定
      2：特定源泉徴収あり   →   1：特定 
    """
    # 現物注文の場合
    # 16.現金信用区分  
    #   0:現物
    if str_sGenkinShinyouKubun == '0':
        if dic_login_property.get('sTokuteiKouzaKubunGenbutu') == '0':     
            # 「特定口座区分現物 0:一般口座」の場合
            # 譲渡益課税区分は 「3:一般」を設定する。
            flg_sZyoutoekiKazeiC = '3'
        else:                           
            # 「特定口座区分現物  源泉徴収 1:あり、2:無し」の場合
            # 譲渡益課税区分は 「1:特定」を設定する。
            flg_sZyoutoekiKazeiC = '1'             
    
    # 信用注文の場合    
    # 16.現金信用区分  
    #   2:新規(制度信用6ヶ月)
    #   4:返済(制度信用6ヶ月)、
    #   6:新規(一般信用6ヶ月)
    #   8:返済(一般信用6ヶ月)。
    else:
        if dic_login_property.get('sTokuteiKouzaKubunSinyou') == '0':     
            # 「特定口座区分現物 0:一般口座」の場合
            # 譲渡益課税区分は 「3:一般」を設定する。
            flg_sZyoutoekiKazeiC = '3'
        else:                           
            # 「特定口座区分現物  源泉徴収 1:あり、2:無し」の場合
            # 譲渡益課税区分は 「1:特定」を設定する。
            flg_sZyoutoekiKazeiC = '1'             
        
    return flg_sZyoutoekiKazeiC


def func_order_genbutsu_buy(
                                int_p_no,
                                str_sIssueCode,
                                str_sSizyouC,
                                str_sCondition,
                                str_sOrderPrice,
                                str_sOrderSuryou,
                                str_sSecondPassword,
                                dic_login_property, 
                                str_sJsonOfmt
                            ):
    """ 機能: 現物 買い注文
    返値： 辞書型データ（APIからのjson形式返信データをshift-jisのstring型に変換し、更に辞書型に変換）
    引数1: p_no
    引数2: 銘柄コード
    引数3: 市場（現在、東証'00'のみ）
    引数4: 執行条件
    引数5: 価格
    引数6: 株数
    引数7: 第２パスワード
    引数8: ログインレスポンス
    引数9: sJsonOfmt
    """
    # 売買区分
    #   3:買 を指定
    str_sBaibaiKubun = '3'          # 12.売買区分  
                                    #   1:売
                                    #   3:買
                                    #   5:現渡
                                    #   7:現引

    # 現金信用区分 
    #   0:現物 を指定
    str_sGenkinShinyouKubun = '0'   # 16.現金信用区分   0:現物、
                                    #                   2:新規(制度信用6ヶ月)、
                                    #                   4:返済(制度信用6ヶ月)、
                                    #                   6:新規(一般信用6ヶ月)、
                                    #                   8:返済(一般信用6ヶ月)。
    
    # 8.譲渡益課税区分    1：特定  3：一般  5：NISA     ログインの返信データで設定する。
    str_sZyoutoekiKazeiC = func_set_sZyoutoekiKazeiC(str_sGenkinShinyouKubun, dic_login_property)


    dic_req_item = {
        'p_no': str(int_p_no),
        'p_sd_date': func_p_sd_date(),

        'sCLMID': 'CLMKabuNewOrder',                        # 新規注文を指示。
        'sGenkinShinyouKubun': str_sGenkinShinyouKubun,     # 現金信用区分
        'sIssueCode': str_sIssueCode,               # 銘柄コード
        'sSizyouC': str_sSizyouC,                   # 市場C
        'sBaibaiKubun': str_sBaibaiKubun,           # 売買区分
        'sCondition': str_sCondition,               # 執行条件
        'sOrderPrice': str_sOrderPrice,             # 注文値段
        'sOrderSuryou': str_sOrderSuryou,           # 注文数量

        # 固定パラメーターセット
        'sZyoutoekiKazeiC': str_sZyoutoekiKazeiC,   # 8.譲渡益課税区分    1：特定  3：一般  5：NISA     ログインの返信データで設定。 
        'sOrderExpireDay': '0',                     # 17.注文期日  0:当日、上記以外は、注文期日日(YYYYMMDD)[10営業日迄]。
        'sGyakusasiOrderType': '0',                 # 18.逆指値注文種別  0:通常、1:_gen逆指値、2:通常+逆指値
        'sGyakusasiZyouken': '0',                   # 19.逆指値条件  0:指定なし、条件値段(トリガー価格)
        'sGyakusasiPrice': '*',                     # 20.逆指値値段  *:指定なし、0:成行、*,0以外は逆指値値段。
        'sTatebiType': '*',                         # 21.建日種類  *:指定なし(現物または新規) 、1:個別指定、2:建日順、3:単価益順、4:単価損順。
        'sTategyokuZyoutoekiKazeiC': '*',           # 9.建玉譲渡益課税区分  信用建玉における譲渡益課税区分(現引、現渡で使用)。  *:現引、現渡以外の取引、1:特定、3:一般、5:NISA
        'sSecondPassword': str_sSecondPassword,     # 22.第二パスワード    APIでは第２暗証番号を省略できない。 関連資料:「立花証券・e支店・API、インターフェース概要」の「3-2.ログイン、ログアウト」参照     ログインの返信データで設定済み。
        'sJsonOfmt': str_sJsonOfmt                  # サポートへの問い合わせは、sJsonOfmt:'5'を指定した送信電文と受信電文でお願いします。
    }

    # URL文字列の作成
    str_url = func_make_url_request_from_dic(
                                                False, \
                                                dic_login_property.get('sUrlRequest'), \
                                                dic_req_item
                                            )

    # リクエストメソッドの指定('GET'、'POST'どちらでも動作します。)
    str_api_response = func_api_req('POST', str_url)

    # apiの返り値（JSON形式の文字列）を辞書型で取り出す
    dic_api_response = json.loads(str_api_response)
    
    return dic_api_response

    
# ======================================================================================================
# ==== プログラム始点 =================================================================================
# ======================================================================================================

if __name__ == "__main__":
    """ 
    必要な設定項目
    銘柄コード: my_sIssueCode （実際の銘柄コードを入れてください。）
    市場: my_sSizyouC （00:東証   現在(2021/07/01)、東証のみ可能。）
    執行条件: my_sCondition   （0:指定なし、2:寄付、4:引け、6:不成。指し値は、0:指定なし。）
    注文値段: my_sOrderPrice  （*:指定なし、0:成行、上記以外は、注文値段。小数点については、関連資料:「立花証券・e支店・API、REQUEST I/F、マスタデータ利用方法」の「2-12. 呼値」参照。）
    注文数量: my_sOrderSuryou
    """    
    # 接続情報をファイルから読み込む。
    dic_url_info = func_get_url_info(FNAME_URL_INFO)
    
    # 22.第二パスワード
    # APIでは第２暗証番号を省略できない。 関連資料:「立花証券・e支店・API、インターフェース概要」の「3-2.ログイン、ログアウト」参照
    # URLに「#」「+」「/」「:」「=」などの記号を利用した場合エラーとなるため、URLエンコーディングを行う。
    # APIへの入力文字列（特にパスワードで記号を利用している場合）で注意が必要。
    #   '#' →   '%23'
    #   '+' →   '%2B'
    #   '/' →   '%2F'
    #   ':' →   '%3A'
    #   '=' →   '%3D'
    my_sSecondPassword = func_read_from_file(FNAME_PASSWD2).strip()
    my_sSecondPassword = func_replace_urlencode(my_sSecondPassword)        # urlエンコーディング
    
    # ログイン応答を保存した「file_login_response.txt」から、仮想URLと課税flgを取得
    dic_login_property = func_get_login_response(FNAME_LOGIN_RESPONSE)

    # 現在（前回利用した）のp_noをファイルから取得する
    my_p_no = func_get_p_no(FNAME_INFO_P_NO)
    my_p_no = my_p_no + 1
    # 更新した"p_no"を保存する。
    func_save_p_no(FNAME_INFO_P_NO, my_p_no)
    
    print()
    print('-- 現物 買い注文  -------------------------------------------------------------')
    # 当日の現物注文（逆指値等は使わない）でパラメーターを減らした簡単な関数例

    # 送信項目の解説は、マニュアル「立花証券・ｅ支店・ＡＰＩ（ｖ〇）、REQUEST I/F、機能毎引数項目仕様」
    # p4-5/46 No.5 CLMKabuNewOrder を参照してください。
    
    # 送信項目の実例は、マニュアル「立花証券・ｅ支店・ＡＰＩ（ｖ４）、REQUEST I/F、注文入力機能引数項目仕様」
    # p5/40 以降にrequest電文と応答電文を記載
    # 「現物×買×成行×特定口座」のrequest電文例
    # {
    #   "sCLMID":"CLMKabuNewOrder",
    #   "sZyoutoekiKazeiC":"1",
    #   "sIssueCode":"6658",
    #   "sSizyouC":"00",
    #   "sBaibaiKubun":"3",
    #   "sCondition":"0",
    #   "sOrderPrice":"0",
    #   "sOrderSuryou":"100",
    #   "sGenkinShinyouKubun":"0",
    #   "sOrderExpireDay":"0",
    #   "sGyakusasiOrderType":"0",
    #   "sGyakusasiZyouken":"0",
    #   "sGyakusasiPrice":"*",
    #   "sTatebiType":"*",
    #   "sTategyokuZyoutoekiKazeiC":"*",
    #   "sSecondPassword":"",
    #   "sJsonOfmt":"1"
    # }
    # この注文例を基にrequest電文を作成してみる

    # 現物 買い注文    引数：p_no、銘柄コード、市場（現在、東証'00'のみ）、執行条件、価格、株数、口座属性クラス
    dic_return = func_order_genbutsu_buy(
                                            my_p_no,
                                            S_ISSUE_CODE,       # 10.銘柄コード。実際の銘柄コードを入れてください。
                                            S_SIZYOU_C,         # 11.市場。  00:東証   現在(2021/07/01)、東証のみ可能。
                                            S_CONDITION,        # 13.執行条件。  0:指定なし、2:寄付、4:引け、6:不成。指し値は、0:指定なし。
                                            S_ORDER_PRICE,      # 14.注文値段。  *:指定なし、0:成行、上記以外は、注文値段。小数点については、関連資料:「立花証券・e支店・API、REQUEST I/F、マスタデータ利用方法」の「2-12. 呼値」参照。
                                            S_ORDER_SURYOU,     # 15.注文数量。
                                            my_sSecondPassword, # 第2パスワード（URLエンコード済み）。
                                            dic_login_property,
                                            dic_url_info.get("sJsonOfmt")
                                        )
    # 戻り値の解説は、マニュアル「立花証券・ｅ支店・ＡＰＩ（ｖ〇）、REQUEST I/F、機能毎引数項目仕様」(api_request_if_clumn_v4.pdf)
    # p4-5/46 No.5 引数名:CLMKabuNewOrder 項目1-28 を参照してください。

    if dic_return is not None:
        print('結果コード:\t', dic_return.get('sResultCode'))
        print('結果テキスト:\t', dic_return.get('sResultText'))
        print('警告コード:\t', dic_return.get('sWarningCode'))
        print('警告テキスト:\t', dic_return.get('sWarningText'))
        print('注文番号:\t', dic_return.get('sOrderNumber'))
        print('営業日:\t', dic_return.get('sEigyouDay'))
        print('注文受渡金額:\t', dic_return.get('sOrderUkewatasiKingaku'))
        print('注文手数料:\t', dic_return.get('sOrderTesuryou'))
        print('注文消費税:\t', dic_return.get('sOrderSyouhizei'))
        print('金利:\t', dic_return.get('sKinri'))
        print('注文日時:\t', dic_return.get('sOrderDate'))
    
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
       
