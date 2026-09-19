# Jensen, Kelly & Pedersen (2023) 153ファクターカタログ

出典: Jensen, T. I., Kelly, B. T., & Pedersen, L. H. (2023). "Is There a Replication
Crisis in Finance?" *The Journal of Finance*, 78(5), 2465-2518.
公式ドキュメント: https://jkpfactors.com (Documentation.pdf, Table 9: Factor and Cluster
Details より全件転記。原著の個別引用も含む)。全406特性のうち、著者らが厳選した
コア153ファクター(13テーマにクラスタ分類)。

## 使い方

2026-09-19、ユーザーの「論文を100個ぐらい探して」を受けて発見。今まで場当たり的に
Web検索していたファクター探しの代わりに、査読済み論文(Journal of Finance)で
体系的に厳選・分類済みのカタログをまるごと取得した。**このセッションでは実証検証は
行わない**(FACTOR_RESEARCH_LOG.md「調査待ちキュー」の一括版という位置づけ)。

既に本プロジェクトで(概念的に)検証済みのものには「✅済」、まだのものには何も
付けていない。「済」でも計算方法の細部(会計変数の厳密な定義、サンプル期間区切り等)
は異なる可能性があるため、将来の再検証を妨げるものではない。

多くは年次のクロスセクション検証で足りるが、`seas_*_na`/`seas_*_an`系(2〜20年
ラグのリターン)は特に**長期データが要る**ため、J-Quants Premium(20年)を契約
した場合の優先候補にすること。

---

## Accruals(6件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Change in current operating working capital | cowc_gr1a | Richardson, Sloan, Soliman & Tuna (2005) | -1 |
| Operating accruals | oaccruals_at | Sloan (1996) | -1 ✅済(#16アクルーアル、NO-GO/逆転) |
| Percent operating accruals | oaccruals_ni | Hafzalla, Lundholm & Van Winkle (2011) | -1 |
| Years 16-20 lagged returns, nonannual | seas_16_20na | Heston & Sadka (2008) | +1 |
| Total accruals | taccruals_at | Richardson et al. (2005) | -1 |
| Percent total accruals | taccruals_ni | Hafzalla et al. (2011) | -1 |

## Debt Issuance(7件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Abnormal corporate investment | capex_abn | Titman, Wei & Xie (2004) | -1 ✅済(異常設備投資、NO-GO) |
| Growth in book debt (3 years) | debt_gr3 | Lyandres, Sun & Zhang (2008) | -1 |
| Change in financial liabilities | fnl_gr1a | Richardson et al. (2005) | -1 |
| Change in noncurrent operating liabilities | ncol_gr1a | Richardson et al. (2005) | -1 |
| Change in net financial assets | nfna_gr1a | Richardson et al. (2005) | +1 |
| Earnings persistence | ni_ar1 | Francis, LaFond, Olsson & Schipper (2004) | +1 |
| Net operating assets | noa_at | Hirshleifer, Hou, Teoh & Zhang (2004) | -1 ✅済(#56、NO-GO) |

## Investment(22件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Liquidity of book assets | aliq_at | Ortiz-Molina & Phillips (2014) | -1 |
| Asset Growth | at_gr1 | Cooper, Gulen & Schill (2008) | -1 ✅済(#17資産成長率、弱GO) |
| Change in common equity | be_gr1a | Richardson et al. (2005) | -1 |
| CAPEX growth (1 year) | capx_gr1 | Xie (2001) | -1 |
| CAPEX growth (2 years) | capx_gr2 | Anderson & Garcia-Feijoo (2006) | -1 |
| CAPEX growth (3 years) | capx_gr3 | Anderson & Garcia-Feijoo (2006) | -1 |
| Change in current operating assets | coa_gr1a | Richardson et al. (2005) | -1 |
| Change in current operating liabilities | col_gr1a | Richardson et al. (2005) | -1 |
| Hiring rate | emp_gr1 | Belo, Lin & Bazdresch (2014) | -1 (データ調達困難、調査待ちキュー#6と同じ) |
| Inventory growth | inv_gr1 | Belo & Lin (2012) | -1 |
| Inventory change | inv_gr1a | Thomas & Zhang (2002) | -1 |
| Change in long-term net operating assets | lnoa_gr1a | Fairfield, Whisenant & Yohn (2003) | -1 |
| Mispricing factor: Management | mispricing_mgmt | Stambaugh & Yuan (2017) | +1 |
| Change in noncurrent operating assets | ncoa_gr1a | Richardson et al. (2005) | -1 |
| Change in net noncurrent operating assets | nncoa_gr1a | Richardson et al. (2005) | -1 |
| Change in net operating assets | noa_gr1a | Hirshleifer et al. (2004) | -1 |
| Change PPE and Inventory | ppeinv_gr1a | Lyandres et al. (2008) | -1 |
| Long-term reversal | ret_60_12 | De Bondt & Thaler (1985) | -1 ✅済(#40長期リバーサル、弱GO) |
| Sales Growth (1 year) | sale_gr1 | Lakonishok, Shleifer & Vishny (1994) | -1 |
| Sales Growth (3 years) | sale_gr3 | Lakonishok et al. (1994) | -1 |
| Sales growth (1 quarter) | saleq_gr1 | — | -1 |
| Years 2-5 lagged returns, nonannual | seas_2_5na | Heston & Sadka (2008) | -1 |

## Low Leverage(11件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Firm age | age | Jiang, Lee & Zhang (2005) | -1 |
| Liquidity of market assets | aliq_mat | Ortiz-Molina & Phillips (2014) | -1 |
| Book leverage | at_be | Fama & French (1992) | -1 |
| The high-low bid-ask spread | bidaskhl_21d | Corwin & Schultz (2012) | +1 |
| Cash-to-assets | cash_at | Palazzo (2012) | +1 |
| Net debt-to-price | netdebt_me | Penman, Richardson & Tuna (2007) | -1 |
| Earnings volatility | ni_ivol | Francis et al. (2004) | +1 |
| R&D-to-sales | rd_sale | Chan, Lakonishok & Sougiannis (2001) | +1 ✅済(R&D集約度、弱GO) |
| R&D capital-to-book assets | rd5_at | Li (2011) | +1 |
| Asset tangibility | tangibility | Hahn & Lee (2009) | +1 |
| Altman Z-score | z_score | Dichev (1998) | +1 |

## Low Risk(18件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Market Beta | beta_60m | Fama & MacBeth (1973) | -1 ✅済(低β、上げ相場で逆転) |
| Dimson beta | beta_dimson_21d | Dimson (1979) | -1 |
| Frazzini-Pedersen market beta | betabab_1260d | Frazzini & Pedersen (2014) | -1 ✅済(BAB、NO-GO逆転) |
| Downside beta | betadown_252d | Ang, Chen & Xing (2006) | -1 |
| Earnings variability | earnings_variability | Francis et al. (2004) | -1 |
| Idiosyncratic volatility from CAPM (21d) | ivol_capm_21d | — | -1 |
| Idiosyncratic volatility from CAPM (252d) | ivol_capm_252d | Ali, Hwang & Trombley (2003) | -1 |
| Idiosyncratic volatility from FF3 (21d) | ivol_ff3_21d | Ang, Hodrick, Xing & Zhang (2006) | -1 (=調査待ちキュー#1 IVOLと同一文献) |
| Idiosyncratic volatility from q-factor | ivol_hxz4_21d | — | -1 |
| Cash flow volatility | ocfq_saleq_std | Huang (2009) | -1 |
| Maximum daily return | rmax1_21d | Bali, Cakici & Whitelaw (2011) | -1 |
| Highest 5 days of return | rmax5_21d | Bali, Brown & Tang (2017) | -1 |
| Return volatility | rvol_21d | Ang, Hodrick et al. (2006) | -1 ✅済(低ボラ、上げ相場で逆転) |
| Years 6-10 lagged returns, nonannual | seas_6_10na | Heston & Sadka (2008) | -1 |
| Share turnover | turnover_126d | Datar, Naik & Radcliffe (1998) | -1 |
| Zero trades, turnover tiebreak (1mo) | zero_trades_21d | Liu (2006) | +1 |
| Zero trades, turnover tiebreak (6mo) | zero_trades_126d | Liu (2006) | +1 |
| Zero trades, turnover tiebreak (12mo) | zero_trades_252d | Liu (2006) | +1 |

## Momentum(8件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Current price to high price over last year | prc_highprc_252d | George & Hwang (2004) | +1 ✅済(52週高値、連続版NO-GO/2値版GO) |
| Residual momentum t-6 to t-1 | resff3_6_1 | Blitz, Huij & Martens (2011) | +1 |
| Residual momentum t-12 to t-1 | resff3_12_1 | Blitz et al. (2011) | +1 |
| Price momentum t-3 to t-1 | ret_3_1 | Jegadeesh & Titman (1993) | +1 |
| Price momentum t-6 to t-1 | ret_6_1 | Jegadeesh & Titman (1993) | +1 |
| Price momentum t-9 to t-1 | ret_9_1 | Jegadeesh & Titman (1993) | +1 |
| Price momentum t-12 to t-1 | ret_12_1 | Jegadeesh & Titman (1993) | +1 ✅済(モメンタム12-1、NO-GO) |
| Year 1-lagged return, nonannual | seas_1_1na | Heston & Sadka (2008) | +1 |

## Profit Growth(12件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Change sales minus change Inventory | dsale_dinv | Abarbanell & Bushee (1998) | +1 |
| Change sales minus change receivables | dsale_drec | Abarbanell & Bushee (1998) | -1 |
| Change sales minus change SG&A | dsale_dsga | Abarbanell & Bushee (1998) | +1 |
| Change in quarterly ROA | niq_at_chg1 | — | +1 |
| Change in quarterly ROE | niq_be_chg1 | — | +1 |
| Standardized earnings surprise | niq_su | Foster, Olsen & Shevlin (1984) | +1 (=調査待ちキュー#2 SUEと同一系統) |
| Change in operating cash flow to assets | ocf_at_chg1 | Bouchaud, Krueger, Landier & Thesmar (2019) | +1 |
| Price momentum t-12 to t-7 | ret_12_7 | Novy-Marx (2012) | +1 |
| Labor force efficiency | sale_emp_gr1 | Abarbanell & Bushee (1998) | +1 |
| Standardized Revenue surprise | saleq_su | Jegadeesh & Livnat (2006) | +1 |
| Year 1-lagged return, annual | seas_1_1an | Heston & Sadka (2008) | +1 |
| Tax expense surprise | tax_gr1a | Thomas & Zhang (2011) | +1 |

## Profitability(11件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Coefficient of variation for dollar trading volume | dolvol_var_126d | Chordia, Subrahmanyam & Anshuman (2001) | -1 |
| Return on net operating assets | ebit_bev | Soliman (2008) | +1 |
| Profit margin | ebit_sale | Soliman (2008) | +1 |
| Piotroski F-score | f_score | Piotroski (2000) | +1 ✅済(#59、GO) |
| Return on equity | ni_be | Haugen & Baker (1996) | +1 ✅済(ROE、質スコアとして採用済み) |
| Quarterly return on equity | niq_be | Hou, Xue & Zhang (2015) | +1 |
| Ohlson O-score | o_score | Dichev (1998) | -1 ✅済(Oスコア簡易版、NO-GO) |
| Operating cash flow to assets | ocf_at | Bouchaud et al. (2019) | +1 ✅済(キャッシュベース収益性、NO-GO/逆転) |
| Operating profits-to-book equity | ope_be | Fama & French (2015) | +1 |
| Operating profits-to-lagged book equity | ope_bel1 | — | +1 |
| Coefficient of variation for share turnover | turnover_var_126d | Chordia et al. (2001) | -1 |

## Quality(17件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Capital turnover | at_turnover | Haugen & Baker (1996) | +1 |
| Cash-based operating profits-to-assets | cop_at | — | +1 |
| Cash-based operating profits-to-lagged assets | cop_atl1 | Ball, Gerakos, Linnainmaa & Nikolaev (2016) | +1 |
| Change gross margin minus change sales | dgp_dsale | Abarbanell & Bushee (1998) | +1 |
| Gross profits-to-assets | gp_at | Novy-Marx (2013) | +1 ✅済(#15粗利益収益性、NO-GO/逆転) |
| Gross profits-to-lagged assets | gp_atl1 | — | +1 |
| Mispricing factor: Performance | mispricing_perf | Stambaugh & Yuan (2017) | +1 |
| Consecutive quarters with earnings increases | ni_inc8q | Barth, Elliott & Finn (1999) | +1 |
| Quarterly return on assets | niq_at | Balakrishnan, Bartov & Faurel (2010) | +1 |
| Operating profits-to-book assets | op_at | — | +1 |
| Operating profits-to-lagged book assets | op_atl1 | Ball et al. (2016) | +1 |
| Operating leverage | opex_at | Novy-Marx (2011) | +1 |
| Quality minus Junk: Composite | qmj | Asness, Frazzini & Pedersen (2019) | +1 ✅済(QMJ簡易版、NO-GO単独/B/M統制後GO) |
| Quality minus Junk: Growth | qmj_growth | Asness et al. (2019) | +1 |
| Quality minus Junk: Profitability | qmj_prof | Asness et al. (2019) | +1 |
| Quality minus Junk: Safety | qmj_safety | Asness et al. (2019) | +1 |
| Assets turnover | sale_bev | Soliman (2008) | +1 |

## Seasonality(12件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Market correlation | corr_1260d | Asness, Frazzini, Gormsen & Pedersen (2020) | -1 |
| Coskewness | coskew_21d | Harvey & Siddique (2000) | -1 |
| Net debt issuance | dbnetis_at | Bradshaw, Richardson & Sloan (2006) | -1 |
| Kaplan-Zingales index | kz_index | Lamont, Polk & Saa-Requejo (2001) | +1 |
| Change in long-term investments | lti_gr1a | Richardson et al. (2005) | -1 |
| Taxable income-to-book income | pi_nix | Lev & Nissim (2004) | +1 |
| Years 2-5 lagged returns, annual | seas_2_5an | Heston & Sadka (2008) | +1 |
| Years 6-10 lagged returns, annual | seas_6_10an | Heston & Sadka (2008) | +1 |
| Years 11-15 lagged returns, annual | seas_11_15an | Heston & Sadka (2008) | +1 |
| Years 11-15 lagged returns, nonannual | seas_11_15na | Heston & Sadka (2008) | -1 |
| Years 16-20 lagged returns, annual | seas_16_20an | Heston & Sadka (2008) | -1 |
| Change in short-term investments | sti_gr1a | Richardson et al. (2005) | +1 |

## Size(5件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Amihud Measure | ami_126d | Amihud (2002) | +1 ✅済(#50、GO) |
| Dollar trading volume | dolvol_126d | Brennan, Chordia & Subrahmanyam (1998) | -1 |
| Market Equity | market_equity | Banz (1981) | -1 ✅済(#54サイズ、NO-GO/逆転) |
| Price per share | prc | Miller & Scholes (1982) | -1 |
| R&D-to-market | rd_me | Chan et al. (2001) | +1 |

## Short-Term Reversal(6件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Idiosyncratic skewness from CAPM | iskew_capm_21d | — | -1 |
| Idiosyncratic skewness from FF3 | iskew_ff3_21d | Bali, Engle & Murray (2016) | -1 |
| Idiosyncratic skewness from q-factor | iskew_hxz4_21d | — | -1 |
| Short-term reversal | ret_1_0 | Jegadeesh (1990) | -1 ✅済(#52、経済的に無意味) |
| Highest 5 days of return scaled by volatility | rmax5_rvol_21d | Asness et al. (2020) | -1 |
| Total skewness | rskew_21d | Bali et al. (2016) | -1 |

## Value(18件)

| 説明 | 変数名 | 原著 | 符号 |
|---|---|---|---|
| Assets-to-market | at_me | Fama & French (1992) | +1 |
| Book-to-market equity | be_me | Rosenberg, Reid & Lanstein (1985) | +1 ✅済(#70 B/M、強くGO) |
| Book-to-market enterprise value | bev_mev | Penman et al. (2007) | +1 |
| Net stock issues | chcsho_12m | Pontiff & Woodgate (2008) | -1 ✅済(純株式発行の裏返し) |
| Debt-to-market | debt_me | Bhandari (1988) | +1 |
| Dividend yield | div12m_me | Litzenberger & Ramaswamy (1979) | +1 ✅済(配当利回り、GO) |
| Ebitda-to-market enterprise value | ebitda_mev | Loughran & Wellman (2011) | +1 ✅済(EV/EBITDAの裏返し、GO) |
| Equity duration | eq_dur | Dechow, Sloan & Soliman (2004) | -1 |
| Net equity issuance | eqnetis_at | Bradshaw et al. (2006) | -1 |
| Equity net payout | eqnpo_12m | Daniel & Titman (2006) | +1 |
| Net payout yield | eqnpo_me | Boudoukh, Michaely, Richardson & Roberts (2007) | +1 |
| Payout yield | eqpo_me | Boudoukh et al. (2007) | +1 |
| Free cash flow-to-price | fcf_me | Lakonishok et al. (1994) | +1 |
| Intrinsic value-to-market | ival_me | Frankel & Lee (1998) | +1 |
| Net total issuance | netis_at | Bradshaw et al. (2006) | -1 ✅済(#25純株式発行) |
| Earnings-to-price | ni_me | Basu (1983) | +1 |
| Operating cash flow-to-market | ocf_me | Desai, Rajgopal & Venkatachalam (2004) | +1 ✅済(CF利回り、GO) |
| Sales-to-market | sale_me | Barbee Jr, Mukherji & Raines (1996) | +1 |

---

## 集計

153件中、概念的に既にテスト済み(✅)は約27件。残り約126件が未検証の新規候補。
テーマ別の未検証候補が多い順: Investment(22件中✅3)、Quality(17件中✅3)、
Low Risk(18件中✅3)、Value(18件中✅5)、Seasonality(12件中✅0)、
Profit Growth(12件中✅1)。

**次にこの話が出たら**: どのテーマから着手するか、またはJ-Quants Premium契約後に
長期データが要るseas_*系から着手するか、ユーザーに確認する。
