# ビットコイン(暗号資産)のアノマリー文献メモ(2026-09-21、文献収集のみ・未検証)

ユーザーの「ビットコインのアノマリー探してきて」を受けて収集。**実証テストはまだしていない**。
株の調査待ちキューとは別管理(対象資産・データ源・税制が違うため)。出典はWeb検索結果に
出てきたもののみで、各論文の中身までは読んでいない(タイトル・要旨レベル)。

## 候補一覧

| # | 候補 | 出典(検索で確認できた範囲) | 必要データ | データ入手性 |
|---|---|---|---|---|
| 1 | 暗号資産の3ファクター(市場・サイズ・モメンタム)。価格・出来高・ボラ系の10特性でロング/ショート戦略が有意な超過リターン | Liu, Tsyvinski & Wu (2022) "Common Risk Factors in Cryptocurrency", Journal of Finance([Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13119)) | 複数銘柄(コイン)の日次〜週次価格・時価総額 | BTC単体は取得確認済み(yfinance、2014-09〜)。**複数コインの網羅性・上場廃止コインの扱い(生存バイアス)は未確認** |
| 2 | 時系列モメンタム(日次・週次) | Liu & Tsyvinski, "Risks and Returns of Cryptocurrency"([NBER w24877](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)) | BTC日足 | 確認済み(yfinance) |
| 3 | モメンタムの再検証 | "Cryptocurrency momentum has (not) its moments", Financial Markets and Portfolio Management (2025)([Springer](https://link.springer.com/article/10.1007/s11408-025-00474-9)) | 同上 | 論文の結論は**未確認**(タイトルのみ。頑健性に疑問を呈する内容の可能性) |
| 4 | 日中モメンタム(最初の30分が最後の30分を予測、流動性供給が要因、下げ相場で特に有効との報告) | "Bitcoin intraday time-series momentum"([Reading大学版](https://centaur.reading.ac.uk/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf)) | BTCの分足 | **未確認**(yfinanceの分足は株では過去8日/60日まで。BTCも同様の可能性、取引所APIは未調査) |
| 5 | 日中・夜間の季節性(UTC22〜23時のリターンが経済的に最大との報告)、日曜夜NY時間〜月曜のアジア時間オープン効果 | [Quantpedia](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/)、[Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)、"Turn-of-the-candle effect in bitcoin returns"([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/)) | BTCの1時間足以下 | 同上 **未確認**。曜日効果は日次では結果が混在(検索結果の記述) |
| 6 | 半減期サイクル(約4年周期) | 解説記事のみ([Bitcoin Suisse](https://bitcoinsuisse.com/learn/bitcoin-halving-market-cycle)等)。査読論文は確認できず | BTC日足 | 確認済みだが**独立な観測が3〜4サイクルしかなく、統計的検証には向かない**(株の「実質4年度」問題よりさらに少ない) |

## 注意(今日の教訓の適用)

- 株の検証と同じく、独立な観測数が少ない。BTCは約12年・相場サイクル3〜4回のみ。
- 4・5は日中データが要るため、データ入手性が確定するまで着手しない(ルール9)。
- 税制(現行は雑所得・総合課税、損益通算・繰越不可)と取引コスト(片道数〜数十bps以上)が
  株より不利なので、「効く」だけでなく「税・コスト後に残る」かを必ず見ること。

## 参考: 1306ルールをBTC日足にそのまま当てた結果(btc_rsi_lab.py、SESSION_LOG項目70)

RSI<40買い/>=50利確/損切り8%を無調整で適用: 全期間-64%(買い持ち+18,537%)、暦年でプラスは
6/12年、パイプライン(パラメータ探索+WF)判定はNO-GO(WF 2/4)。平均回帰型のRSI逆張りは
BTCに合わない。
