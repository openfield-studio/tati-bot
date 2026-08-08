# -*- coding: utf-8 -*-
# Copyright (c) 2026 Tachibana Securities Co., Ltd. All rights reserved.
# 
# 2026.05.30 reviced,   yo.
#
# 立花証券ｅ支店ＡＰＩ利用のサンプルコード
#
# 動作確認
# Python 3.13.5 / debian13
# API v4r9
#
# 機能: 公開鍵認証用の認証IDと秘密鍵を暗号化します。
#
# """
# 立花証券e支店API - API接続情報 暗号化ユーティリティ（初回設定用）
# 
# このスクリプトは、認証ID（AuthID）と秘密鍵（Private Key）を一つにまとめ、
# 共通鍵暗号（Fernet）を用いて強固に暗号化した設定ファイルを生成します。
# 生成された暗号化ファイルは、自動実行スクリプト側で環境変数経由で復号されます。
# """
# 
# 
# 認証IDと秘密鍵の取得手順と、本暗号化プログラムの実行については、
# 次の2つの説明書を参照してください。
# ・認証ID・秘密鍵等の取得方法.pdf
# ・セットアップマニュアル.html
# 
# 


import json
import os
import stat
from pathlib import Path
from cryptography.fernet import Fernet

# =========================================================================
# --- 設定項目（定数定義） ---
# =========================================================================
# 暗号化された設定ファイルの保存先
CONFIG_FILE = "./.auth/secure_config.enc"

# 元になる認証情報ファイルの配置先（セットアップマニュアル準拠）
FILE_AUTH_ID = "./.auth/e_api_authid.txt"
FILE_PRIVATE_KEY = "./.auth/e_api_private_key.pem"
# =========================================================================


def main():
    print("API接続情報の暗号化処理を開始します...")

    # 1. 元になる秘密鍵とAuthIDファイルの読み込み（BOMを自動排除）
    # (利用者は一時的にローカルに配置したファイルを指定します)
    try:
        # 認証IDの読み込み
        path_auth_id = Path(FILE_AUTH_ID)
        auth_id = path_auth_id.read_text(encoding="utf-8-sig").strip()
        
        # 秘密鍵の読み込み
        path_private_key = Path(FILE_PRIVATE_KEY)
        pem_text = path_private_key.read_text(encoding="utf-8-sig").strip()

    except FileNotFoundError as e:
        print("\n[エラー] 必要な元ファイルが見つかりません。配置を確認してください。")
        print(f"詳細: {e}")
        print("「セットアップマニュアル.html」の手順通りに正しく配置されているかご確認ください。")
        return
    except Exception as e:
        print(f"\n[エラー] ファイルの読み込み中に予期せぬエラーが発生しました: {e}")
        return

    # 2. データをJSON形式に構造化してバイト列に変換
    secret_data = {
        "auth_id": auth_id,
        "private_key": pem_text
    }
    plain_bytes = json.dumps(secret_data, ensure_ascii=False).encode("utf-8")

    # 3. データを暗号化するためのマスターキー（復号鍵）を自動生成
    fernet_key = Fernet.generate_key()
    cipher = Fernet(fernet_key)
    encrypted_bytes = cipher.encrypt(plain_bytes)

    # 4. 暗号化された設定ファイルを保存
    try:
        path_config = Path(CONFIG_FILE)
        # 保存先ディレクトリが存在しない場合は自動作成
        path_config.parent.mkdir(parents=True, exist_ok=True)
        path_config.write_bytes(encrypted_bytes)
        
        # Linux環境向けに、ファイル権限を「所有者のみ読み書き(600)」に制限
        os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # Windows環境でのテスト実行時など、権限変更不可の場合はスキップ
        pass
    except Exception as e:
        print(f"\n[エラー] 暗号化ファイルの保存に失敗しました: {e}")
        return

    # 5. 生成された鍵（環境変数用）を利用者に提示
    print("=" * 60)
    print("【重要】暗号化ファイルの作成に成功しました。")
    print(f"作成されたファイル: {path_config.resolve()}")
    print("-" * 60)
    print("以下の文字列を、自動実行環境の「環境変数 (API_DECRYPT_KEY)」に設定してください。")
    print("この鍵はファイルとしてディスクに保存せず、環境変数としてメモリから注入します。")
    print(f"\nAPI_DECRYPT_KEY={fernet_key.decode()}\n")
    print("上の行の内容は /etc/systemd/system/e_api_login.service ファイルに設定してください。")
    print('設定する場所は、Environment="API_DECRYPT_KEY=sample.......sample"の行の')
    print('""で囲まれた部分（値）に貼り付けます。')
    print("=" * 60)
    print("※セキュリティ注意:")
    print(f"暗号化の原本となった以下のファイルは、サーバー上から速やかに【安全に削除】してください。")
    print(f"  - {FILE_AUTH_ID}")
    print(f"  - {FILE_PRIVATE_KEY}")
    print("=" * 60)


if __name__ == "__main__":
    main()