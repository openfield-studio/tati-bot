#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JPX(東証)公表の業種別PER・PBR 履歴データ取得・分析ラボ
=====================================================================
※本体には組み込まない。「試したらどうなるか」の記録。

value_screener.py(個別株の割安スコア)は、yfinanceが「今の」PER/PBRしか
返さないため過去に遡ったバックテストができない、という制約があった。
一方、JPX(東京証券取引所)は「規模別・業種別PER・PBR」を1999年11月から
毎月公表しており、東証33業種分類の月次PER/PBRが取得できる。
これを使えば「業種単位の割安判定」は過去データで検証できる。

このラボでは:
  1. JPXのページからExcelファイル(2020年〜現在、個別リンク)と
     2013-2019年分(ZIPアーカイブ)を取得・解析し、業種別PER/PBRの
     月次時系列を1本のCSVに統合する(jpx_sector_per_pbr_history.csv)。
  2. 各業種について、現在のPERが過去の分布の中でどのパーセンタイルに
     位置するか(=歴史的に見て今は割安か)を算出する。
  3. (発展) 業種PERパーセンタイルと、その後の株価騰落率(TOPIX-17業種別ETFで代替)
     の関係を見る簡易チェックを行う。

対象は「東証プライム(2022年4月以降)/東証一部(それ以前)」の主板のみ
(データの連続性のため。グロース市場・スタンダード市場は別集計)。
1999年11月〜2012年分はPDFのみでの提供のため、このラボでは対象外
(Excel提供の2013年以降、約13年分を対象とする)。

使い方: python sector_valuation_lab.py
出力: jpx_sector_per_pbr_history.csv(業種別PER/PBR月次時系列)
"""
from __future__ import annotations
import io
import re
import zipfile
import urllib.request
import csv

import openpyxl
import xlrd

BASE = "https://www.jpx.co.jp"
INDEX_URL = f"{BASE}/markets/statistics-equities/misc/04.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
MAIN_SEGMENTS = {"Prime", "1st Section"}  # 2022年4月の市場区分見直し前後の「主板」ラベル
LEGACY_SHEET_INDEX = 0  # 2013-2019年分(.xls)は連結一部(Consolidated 1st Section)が1枚目


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def find_monthly_links() -> list[str]:
    """トップページから2020年〜現在の個別月次Excelリンクを抽出する。"""
    html = fetch(INDEX_URL).decode("utf-8", errors="ignore")
    rels = re.findall(r'href="(/markets/statistics-equities/misc/[^"]+perpbr\d{6}\.xlsx)"', html)
    return sorted(set(BASE + r for r in rels))


def find_archive_zip_url() -> str | None:
    html = fetch(INDEX_URL).decode("utf-8", errors="ignore")
    m = re.search(r'href="(/markets/statistics-equities/misc/[^"]+2013-2019[^"]*\.zip)"', html)
    return BASE + m.group(1) if m else None


def normalize_jp(label: str) -> str:
    """全角スペース・連続空白を除去する。"""
    return re.sub(r"\s+", "", str(label or ""))


def canonical_industry_key(label: str) -> str | None:
    """業種名から統一キーを作る。新旧フォーマットで「倉庫・運輸関連」/「倉庫・運輸関連業」の
    ように末尾の「業」有無が食い違うケースがあるため、先頭の業種番号(1〜33)だけを
    キーにする(番号があれば一意に定まるため表記ゆれの影響を受けない)。総合はそのまま。"""
    norm = normalize_jp(label)
    if norm == "総合":
        return "総合"
    m = re.match(r"^(\d+)", norm)
    return m.group(1) if m else None


def cell_num(v) -> float | None:
    """一部の期間のファイルは数値が"=146"のような文字列の数式で保存されており、
    計算結果がキャッシュされていないとopenpyxl(data_only=True)ではNoneになる。
    "="を取り除いて数値化することで救う。"-"や"＊"等は評価不能としてNoneを返す。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.startswith("="):
        s = s[1:]
    try:
        return float(s)
    except ValueError:
        return None


def parse_modern_xlsx(data: bytes, source: str) -> list[dict]:
    """2020年〜現在のExcel(.xlsx、複数月・全市場区分が1シートに縦持ち)を解析する。
    data_only=Falseで読む(一部の期間は数値が計算結果未キャッシュの"=146"形式の
    数式文字列で保存されており、data_only=Trueだと値が取れずNoneになるため)。"""
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    ws = wb[wb.sheetnames[0]]  # 1枚目=連結ベース
    out = []
    for row in ws.iter_rows(min_row=5, values_only=True):
        if not row or row[0] is None:
            continue
        yearmonth, seg_jp, seg_en, ind_jp, ind_en, n_cos = row[0:6]
        if seg_en not in MAIN_SEGMENTS:
            continue
        key = canonical_industry_key(ind_jp)
        if key is None:
            continue
        avg_per, avg_pbr = cell_num(row[6]), cell_num(row[7])
        n_cos = cell_num(n_cos)
        try:
            ym = str(yearmonth).replace("/", "-")[:7]
        except Exception:
            continue
        out.append({
            "yearmonth": ym, "industry_key": key,
            "industry_jp": str(ind_jp or "").strip(),
            "industry_en": (ind_en or "").strip(),
            "n_companies": n_cos, "per": avg_per, "pbr": avg_pbr,
            "source": source,
        })
    return out


def parse_legacy_xls(data: bytes, source: str) -> list[dict]:
    """2013-2019年分のExcel(.xls、1ファイル=1ヶ月、シート0枚目=連結一部)を解析する。
    列構成は新形式と異なり(列C=PER、列D=PBR)、業種名(日本語)のみで英語名は無い。"""
    m = re.search(r"(\d{4})(\d{2})\.xls$", source)
    if not m:
        return []
    ym = f"{m.group(1)}-{m.group(2)}"

    wb = xlrd.open_workbook(file_contents=data)
    ws = wb.sheet_by_index(LEGACY_SHEET_INDEX)
    out = []
    for r in range(ws.nrows):
        label = str(ws.cell_value(r, 0)).strip()
        key = canonical_industry_key(label)
        if key is None:
            continue
        try:
            n_cos = ws.cell_value(r, 2)
            per = ws.cell_value(r, 3)
            pbr = ws.cell_value(r, 4)
        except IndexError:
            continue
        if not isinstance(per, (int, float)) or not isinstance(pbr, (int, float)):
            continue  # "-"等の欠損値
        out.append({
            "yearmonth": ym, "industry_key": key,
            "industry_jp": label, "industry_en": "",
            "n_companies": n_cos, "per": per, "pbr": pbr,
            "source": source,
        })
    return out


def main() -> None:
    all_rows: list[dict] = []

    print("[1/2] 2020年〜現在の個別月次Excel(.xlsx)を取得中...")
    monthly_links = find_monthly_links()
    print(f"  {len(monthly_links)}ファイル見つかりました")
    for i, url in enumerate(monthly_links, 1):
        try:
            data = fetch(url)
            all_rows += parse_modern_xlsx(data, source=url.rsplit("/", 1)[-1])
        except Exception as e:
            print(f"  [警告] {url}: {e}")
        if i % 10 == 0:
            print(f"  {i}/{len(monthly_links)}件処理済み...")

    print("[2/2] 2013-2019年分のZIPアーカイブ(.xls、旧形式)を取得中...")
    zip_url = find_archive_zip_url()
    if zip_url:
        zdata = fetch(zip_url)
        with zipfile.ZipFile(io.BytesIO(zdata)) as zf:
            xls_names = [n for n in zf.namelist() if n.lower().endswith(".xls")]
            print(f"  ZIP内に{len(xls_names)}件のExcel(.xls)ファイル")
            for name in xls_names:
                try:
                    data = zf.read(name)
                    all_rows += parse_legacy_xls(data, source=name)
                except Exception as e:
                    print(f"  [警告] {name}: {e}")
    else:
        print("  [警告] 2013-2019年分のZIPリンクが見つかりませんでした")

    all_rows.sort(key=lambda r: (r["yearmonth"], r["industry_key"]))
    months = sorted(set(r["yearmonth"] for r in all_rows))
    print(f"\n合計{len(all_rows)}行 / {len(months)}ヶ月分({months[0] if months else '-'} 〜 "
          f"{months[-1] if months else '-'}) / {len(set(r['industry_key'] for r in all_rows))}業種")

    with open("jpx_sector_per_pbr_history.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["yearmonth", "industry_key", "industry_jp",
                                                "industry_en", "n_companies", "per", "pbr", "source"])
        writer.writeheader()
        writer.writerows(all_rows)
    print("jpx_sector_per_pbr_history.csv に出力しました。")


if __name__ == "__main__":
    main()
