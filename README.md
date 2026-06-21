# ETF自動売買ボット — 運用メモ

50万円スタート / 対象ETF: 1306（TOPIX連動）/ 証券: 立花証券 e支店（API）

---

## このシステムは何か

「Claudeがリアルタイムで売買判断する」のではなく、
**過去データで検証して合格(GO)したルールを、コードが毎日機械的に実行する**仕組み。
一番大事なのは「ダメな戦略を本番前に弾く」こと。

```
fetch_yf.py        … 本物の過去株価(10年分)を取得 → prices_1306.csv
      ↓
research_agents.py … ルールを検証してGO/NO-GO判定（研究チーム）→ research_result.json
      ↓
trading_agents.py  … GO戦略で毎日売買判定（実行チーム・DRY-RUN）→ state.json
      ↓
dashboard.html     … スマホで今の状況を確認
```

---

## ファイルの役割（d:\tati に全部置く）

| ファイル | 役割 |
|---|---|
| `fetch_yf.py` | yfinanceで長期の調整後終値を取得し prices_1306.csv を作る |
| `jquants_data.py` | J-Quants(V2 API)から実データ取得する別ルート（APIキー方式） |
| `research_agents.py` | 戦略を検証しGO/NO-GO判定。research_result.json を出力 |
| `trading_agents.py` | GO戦略を読み毎日売買判定。state.json を出力（DRY-RUN既定） |
| `dashboard.html` | state.json を読んでスマホ表示（RSI潮位計） |
| `prices_1306.csv` | 株価キャッシュ（研究・DRY-RUN両方が読む） |
| `research_result.json` | GO戦略の設定（研究→実行の橋渡し） |
| `state.json` | ボットの現在状態（ダッシュボードが読む） |

---

## 採用した戦略（検証で GO が出たもの）

**純RSI逆張り（rsi_only）**
- 買い: RSI < 35（売られすぎ＝押し目）
- 売り: RSI ≧ 50 に回復で利確 / 取得値から −5% で損切り
- 10年データ(2462本)での検証で OOS 利益率+37%・最大DD11%・Sharpe0.83 → **GO**

### なぜこの結論になったか（7回試した記録）
- 押し目買い(MAフィルタ付き) → 取引少なすぎ NO-GO
- 順張り → だましで負け NO-GO
- 2年/5年/6年データ → OOS取引が少なく検証しきれない
- **10年データ + 純RSI逆張り → 初めて GO**
- 教訓: データを増やすほど検証が安定する。良すぎる数字(IS Calmar 20等)は過剰最適化の罠。

---

## 毎日の運用手順（DRY-RUN中）

コマンドプロンプトで `d:\tati` に移動してから:

```
cd /d d:\tati
python trading_agents.py        ← その日の判定。state.json更新
```

スマホ/PCで状況を見る:

```
python -m http.server 8000      ← 別ウィンドウで起動しっぱなしにする
```
- PC: ブラウザで http://localhost:8000/dashboard.html
- スマホ(同じWi-Fi): http://(PCのIPアドレス):8000/dashboard.html
  ※PCのIPは  ipconfig  の「IPv4 アドレス」

データを最新化したい時（無料yfinanceは数日遅れでも検証はOK）:
```
python fetch_yf.py 1306 10      ← 10年分を取り直し
python research_agents.py       ← 必要なら再検証
```

### 環境変数（J-Quantsを使う時だけ）
```
set JQUANTS_API_KEY=（ダッシュボードで発行したキー）
```
※yfinanceルートなら不要。

---

## 安全装置（既に組み込み済み）

- `dry_run=True` が既定。実弾発注は dry_run=False かつ enable_live_trading=True の両方が必要。
- 判定が GO 以外なら新規買いを自動で止める。
- 1ポジションのみ。1日1回の冪等ガード。
- `STOP` という名前のファイルを d:\tati に置くと全停止（キルスイッチ）。

---

## 口座開設が終わったら（立花API接続）

1. 立花 e支店の管理画面で API KEY を発行。
2. trading_agents.py の `# TODO(立花)` 2箇所に、立花公式サンプル(te_api_client)を差し込む:
   - `DataAgent._fetch_from_api` … ログイン→日足取得
   - `ExecutionAgent._place_order` … 新規注文の発注
3. Config の api_url / user_id / password を設定（まずデモ環境URLで）。
4. dry_run=True のままデモで動作確認。
5. 問題なければ実弾フラグを立てて、**少額から**本番開始。

---

## 絶対に忘れない原則

- バックテストは「過去がこうだった」であり、未来を保証しない。
- GO が出ても、必ず DRY-RUN（紙トレード）から始める。数週間〜数ヶ月、目で見て確認。
- 本番は少額から。一度に資金を全部入れない。
- 投資判断と責任は自分にある。Claudeはルールのコード化を手伝うだけ。
