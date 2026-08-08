# -*- coding: utf-8 -*-
# Copyright (c) 2021 Tachibana Securities Co., Ltd. All rights reserved.

# 2021.06.24,   yo.
# 2022.10.20 reviced,   yo.
# 2025.07.27 reviced,   yo.
# 2026.05.16 reviced,   yo.
# 2026.05.30 reviced,   yo.
#
# 立花証券ｅ支店ＡＰＩ利用のサンプルコード
#
# 動作確認
# Python 3.13.5 / debian13
# API v4r9
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
# 機能: ログインして、仮想URL（1日券）を取得します。
#
# 利用方法: 
# 
# githubの同じレポジトリ内にある
# ・認証ID・秘密鍵等の取得方法.pdf
# で必要なファイルを取得してください。
# 
# 次に
# ・セットアップマニュアル.html
# をダウンロードし、ブラウザーで開き読んでいただき、設定を進めてください。
# 
# 
# ご注意
# ・本番環境とデモ環境では、各々別の認証ID、秘密鍵、公開鍵のセットになります。
# ・デモ環境でv4r9を利用する場合、デモ環境の標準web画面にログインしていただき、
#   デモ環境専用の認証ID、秘密鍵、公開鍵のセットを取得してください。
# 
# ------------------------------------------------------------------
# 
# 安全性の確保について
#
# 本APIの公開鍵認証では、
# AuthID と秘密鍵ファイルがあればログインできます。
#
# しかし秘密鍵を平文ファイルのまま保存すると
# 情報漏洩のリスクがあるため、
# 本サンプルでは Fernet を利用して
# 設定ファイルを暗号化しています。
#
# Fernet は公開鍵認証自体には必須ではありませんが、
# 認証情報の漏洩リスクを低減するための対策として実装しています。
# 
# 本サンプルで採用している方式は、認証情報を平文で保存する運用を
# 避けるための実装例です。
# 
# 利用環境や運用方針に応じて、
# 
#   ・OSの資格情報ストア
#   ・Windows DPAPI
#   ・Linux Secret Service
#   ・TPMやYubiKeyなどのHSM（ハードウェア・セキュリティ・モジュール） の採用
# 
# など、本サンプルと同等以上の安全性を確保できる方式を採用してください。
# 
# なお、本サンプルでは、認証情報を格納した暗号化ファイル （secure_config.enc）と、
# 復号に必要なキー（API_DECRYPT_KEY）を分離して管理しています。
# 
# 暗号化ファイルのみ、または復号キーのみが漏洩した場合には、
# 認証情報が直ちに利用されることがないよう配慮しています。
# しかし、両方が第三者に取得された場合には
# 認証情報が復元される可能性があります。
# 
# そのため、secure_config.enc および API_DECRYPT_KEY は適切な
# アクセス権限のもとで管理し、第三者へ開示しないよう十分注意してください。 
# 
# ------------------------------------------------------------------
#
# == ご注意: ========================================
#   本番環境にに接続した場合、実際に市場に注文が出ます。
#   市場で約定した場合取り消せません。
# ==================================================
#
#

"""
立花証券e支店API - API接続・自動実行メインプログラム（再起動対応版）

機能: 環境変数からセキュアに復号鍵を取得して秘密鍵をメモリ上に展開し、
      APIにログインして復号済みの仮想URL（1日券）を隠しフォルダに出力します。
"""


import base64
import datetime
import json
import os
import sys
import time
from zoneinfo import ZoneInfo
import urllib.parse
import urllib3
from urllib3.exceptions import MaxRetryError, TimeoutError

# 暗号化・復号用ライブラリ
from cryptography.fernet import Fernet
from Cryptodome.Cipher import PKCS1_OAEP
from Cryptodome.Hash import SHA256
from Cryptodome.PublicKey import RSA

# =========================================================================
# --- 設定項目（定数定義：セットアップマニュアルに完全準拠） ---
# =========================================================================
CONFIG_FILE = "./.auth/secure_config.enc"            # 暗号化設定ファイル
FNAME_URL_INFO = "file_url_info.txt"                # API接続情報ファイル
FNAME_LOGIN_RESPONSE = "./.auth/file_login_response.txt"  # ログイン応答保存先
FNAME_INFO_P_NO = "file_info_p_no.txt"              # p_no保存ファイル

# --- 通信堅牢化のための設定項目 ---
API_TIMEOUT_SECONDS = 15.0  # タイムアウト時間（秒）: 応答がない場合15秒で切り上げる
MAX_RETRY_COUNT = 3         # 最大リトライ回数: 通信エラー時に自動再試行する回数
RETRY_INTERVAL_SECONDS = 5  # リトライ間隔（秒）: 再試行する前に待機する時間
# =========================================================================


# --- 構造体・クラス定義 --------------------------------------------------

# class ClassDefAccountProperty:
#     """接続情報属性クラス"""
#     def __init__(self):
#         self.sAuthId = ''
#         self.sSecondPassword = ''   # 第2パスワード
#         self.sUrl = ''              # 接続先URL
#         self.sJsonOfmt = '5'        # 返り値の表示形式指定


# class ClassDefLoginProperty:
#     """ログイン属性クラス（マニュアルの戻り値定義に準拠）"""
#     def __init__(self):
#         self.p_no = 1
#         self.sJsonOfmt = ''
#         self.sResultCode = ''
#         self.sResultText = ''
#         self.sZyoutoekiKazeiC = ''
#         self.sSecondPasswordOmit = ''
#         self.sLastLoginDate = ''
#         self.sSogoKouzaKubun = ''
#         self.sHogoAdukariKouzaKubun = ''
#         self.sFurikaeKouzaKubun = ''
#         self.sGaikokuKouzaKubun = ''
#         self.sMRFKouzaKubun = ''
#         self.sTokuteiKouzaKubunGenbutu = ''
#         self.sTokuteiKouzaKubunSinyou = ''
#         self.sTokuteiKouzaKubunTousin = ''
#         self.sTokuteiHaitouKouzaKubun = ''
#         self.sTokuteiKanriKouzaKubun = ''
#         self.sSinyouKouzaKubun = ''
#         self.sSakopKouzaKubun = ''
#         self.sMMFKouzaKubun = ''
#         self.sTyukokufKouzaKubun = ''
#         self.sKawaseKouzaKubun = ''
#         self.sHikazeiKouzaKubun = ''
#         self.sKinsyouhouMidokuFlg = ''
#         self.sUrlRequest = ''
#         self.sUrlMaster = ''
#         self.sUrlPrice = ''
#         self.sUrlEvent = ''
#         self.sUrlEventWebSocket = ''
#         self.sUpdateInformWebDocument = ''
#         self.sUpdateInformAPISpecFunction = ''


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
    本APIは一般的なREST APIとは異なり、
    JSONをHTTPボディではなくURLに付加して送信します。
    詳細はAPIマニュアル参照。
    備考：
        サポートへの問い合わせを考慮し、項目ごとの改行とタブを入れてあります。
    '''
    """API問合せ用完全URL（クエリパラメータ付）を作成"""
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


# --- 暗号・復号コアロジック -----------------------------------------------

def decrypt_sUrl(encoded_encrypted_sUrl, private_key_obj):
    """APIから返された暗号化仮想URLを秘密鍵（RSAオブジェクト）で復号"""
    # 規定書に基づき、OAEPパディングおよび内部ハッシュSHA-256を用いて復号器を初期化
    decryptor = PKCS1_OAEP.new(private_key_obj, hashAlgo=SHA256)

    # Base64文字列の前後の引用符や空白をクレンジングしてからデコード
    clean_b64data = encoded_encrypted_sUrl.strip().replace('"', '')
    decoded_b64data = base64.b64decode(clean_b64data)
    
    # 秘密鍵で復号し、BOM対応を考慮してutf-8-sigでデコード
    decrypted_bytes = decryptor.decrypt(decoded_b64data)
    return decrypted_bytes.decode("utf-8-sig").strip()


def func_login_auth(int_p_no, str_sAuthId, dic_url_info):
    """公開鍵認証（秘密鍵ログイン）リクエストの組み立てと実行"""
    str_p_sd_date = func_p_sd_date()
    # p_sd_dateを取得。 API規定書式 "YYYY.MM.DD-hh:mm:ss.sss" の文字列。

    # ログインリクエストに必要なパラメータをマッピング
    dic_req_item = {
        "p_no": str(int_p_no),
        "p_sd_date": str_p_sd_date,
        "sCLMID": "CLMAuthLoginRequest",
        "sAuthId": str_sAuthId,
        "sJsonOfmt": dic_url_info.get("sJsonOfmt")
    }
    
    # 本APIは一般的なREST APIとは異なり、
    # JSONをHTTPボディではなくURLに付加して送信します。
    # 詳細はAPIリファレンス参照。
    str_url = func_make_url_request_from_dic(
                                                True, 
                                                dic_url_info.get("sUrl"), 
                                                dic_req_item
                                            )
    # リクエストメソッドの指定('GET'、'POST'どちらでも動作します。)
    str_request_method = 'POST'
    str_api_response = func_api_req(str_request_method, str_url)
    return json.loads(str_api_response)


# --- メイン処理シーケンス ------------------------------------------------

def func_login(auth_id, private_key_obj, fname_url_info):
    """ログインシーケンス全体の制御と応答の復号化保存"""
    # 接続情報をファイルから読み込む。
    dic_my_url_info = func_get_url_info(fname_url_info)
    
    # p_noの初期化とファイル保存（ログイン時は 1 固定）
    my_p_no = 1
    func_save_p_no(FNAME_INFO_P_NO, my_p_no)
    
    print('\n== 立花証券API ログイン処理開始 ========================')
    dic_return = func_login_auth(my_p_no, auth_id, dic_my_url_info)
    
    # 応答結果のステータスコードを判定
    int_p_errno = int(dic_return.get('p_errno', -1))
    int_sResultCode = int(dic_return.get('sResultCode', -1))
    
    if int_p_errno == 0 and int_sResultCode == 0:
        url_request_raw = dic_return.get('sUrlRequest', '')
        if len(url_request_raw) > 0:
            print('-> ログイン成功。公開鍵暗号化された仮想URLの復号を行います...')
            
            # 各機能の暗号化された仮想URLを秘密鍵で1つずつ復号
            target_url_keys = ['sUrlRequest', 'sUrlMaster', 'sUrlPrice', 'sUrlEvent', 'sUrlEventWebSocket']
            for key in target_url_keys:
                if dic_return.get(key):
                    dic_return[key] = decrypt_sUrl(dic_return[key], private_key_obj)
            
            json_data = json.dumps(
                dic_return, 
                indent=4, 
                ensure_ascii=False
                )
            """
            JSONを整形してURLへ埋め込む。
            APIサポート時に利用者から送信URLを提出してもらうため、
            通信量よりも可読性を優先して indent=4 を指定する。 
            """
            # 復号済みの応答内容を隠しディレクトリへ保存
            func_write_to_file(FNAME_LOGIN_RESPONSE, json_data)
            print(f'【成功】復号したログインレスポンスを保存しました: {FNAME_LOGIN_RESPONSE}')
            print('========================================================')
            print(f"交付書面更新予定日 (sUpdateInformWebDocument): {dic_return.get('sUpdateInformWebDocument')}")
            print(f"APIリリース予定日  (sUpdateInformAPISpecFunction): {dic_return.get('sUpdateInformAPISpecFunction')}")
            print('========================================================')
        else:
            # 契約締結前書面が未読状態の場合は処理を中断
            print('\n[警告] 契約締結前書面が未読状態です。')
            print('APIは利用できません。ブラウザから標準Web画面を開き、書面を確認してください。')
            sys.exit(1)
    else:
        # ログインエラー発生時の情報を出力
        print('\n[エラー] ログインに失敗しました。')
        print(f"p_errno: {dic_return.get('p_errno')} ({dic_return.get('p_err')})")
        print(f"sResultCode: {dic_return.get('sResultCode')} ({dic_return.get('sResultText')})")
        sys.exit(1)


def load_api_credentials():
    """暗号化ファイルと復号キーファイルから認証に必要な情報をメモリ上に展開

    ※本家サンプルはLinux/systemd前提でAPI_DECRYPT_KEYを環境変数から読むが、
      このプロジェクトはWindows/タスクスケジューラ運用のため、
      同じ .auth/ フォルダ内のローカルファイル(decrypt_key.txt、gitignore対象)
      から読む方式に変更している。中身は "API_DECRYPT_KEY=..." の1行。
    """
    fname_decrypt_key = os.path.join(os.path.dirname(CONFIG_FILE), "decrypt_key.txt")
    try:
        with open(fname_decrypt_key, "r", encoding="utf-8-sig") as f:
            line = f.read().strip()
        fernet_key_str = line.split("=", 1)[1].strip() if "=" in line else line
    except FileNotFoundError:
        fernet_key_str = None

    if not fernet_key_str:
        raise RuntimeError(
            f"復号キーファイル '{fname_decrypt_key}' が見つかりません。\n"
            "e_api_encode_auth.py を実行して secure_config.enc と decrypt_key.txt を生成してください。"
        )
    
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"暗号化設定ファイルが見つかりません: {CONFIG_FILE}")
    
    # 暗号化設定ファイルをバイナリモードで一括ロード
    with open(CONFIG_FILE, 'rb') as f_in:
        encrypted_bytes = f_in.read()

    # 共通鍵を用いて暗号化設定ファイルを復号
    cipher = Fernet(fernet_key_str.encode())
    decrypted_bytes = cipher.decrypt(encrypted_bytes)
    
    # 復号されたJSON文字列から認証ID（e_api_authid.txt）をパース
    config = json.loads(decrypted_bytes.decode('utf-8'))
    auth_id = config["auth_id"]
    
    # 格納されているPEMテキスト（e_api_private_key.pem）から秘密鍵をメモリ上にロード
    private_key_obj = RSA.import_key(config["private_key"])
    
    return auth_id, private_key_obj


def main():
    """プログラムのエントリポイント"""
    try:
        # メモリ上へのセキュア展開を実行
        my_auth_id, my_private_key = load_api_credentials()
        print("【セキュリティ認証】秘密鍵のメモリ展開に成功しました。")
        
        # ログインメインシーケンスの実行
        func_login(my_auth_id, my_private_key, FNAME_URL_INFO)
        
        print(f"利用中のAuthID: {my_auth_id}")
        print("API自動ログイン処理がすべて正常に完了しました。")
        
    except ConnectionError as ce:
        # 規定回数リトライをオーバーした通信例外をトラップしてメッセージを表示
        print(f"\n【通信エラーを検知しました】\n{ce}", file=sys.stderr)
        print("時間を置いて再起動するか、サーバーの稼働スケジュールを確認してください。", file=sys.stderr)
        sys.exit(1)
        
    except Exception as e:
        # その他の実行時例外をまとめて捕捉
        print(f"\n【実行エラー】API自動ログイン処理の実行に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
