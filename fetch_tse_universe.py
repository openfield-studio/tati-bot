#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東証プライム市場 全銘柄リストの取得
=====================================================================
JPX「東証上場銘柄一覧」(data_j.xlsx、月次更新)から、市場・商品区分が
「プライム（内国株式）」の銘柄だけを抽出する(ETF/REIT/外国株式等は除外)。
individual_value_backtest.pyのユニバースを日経225から東証プライム全銘柄
(約1,556社)に拡張するための下準備。

使い方: python fetch_tse_universe.py
出力: tse_prime_universe.csv (code, name)
"""
from __future__ import annotations
import csv
import io
import re
import urllib.request

import openpyxl

BASE = "https://www.jpx.co.jp"
INDEX_URL = f"{BASE}/markets/statistics-equities/misc/01.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TARGET_SEGMENT = "プライム（内国株式）"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def find_data_j_url() -> str:
    html = fetch(INDEX_URL).decode("utf-8", errors="ignore")
    m = re.search(r'href="(/markets/statistics-equities/misc/[^"]+data_j\.xlsx)"', html)
    if not m:
        raise RuntimeError("data_j.xlsxへのリンクが見つかりませんでした")
    return BASE + m.group(1)


def main() -> None:
    url = find_data_j_url()
    print(f"取得中: {url}")
    data = fetch(url)
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = wb[wb.sheetnames[0]]

    prime = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[1] is None:
            continue
        code, name, segment = row[1], row[2], row[3]
        if segment == TARGET_SEGMENT:
            prime.append((str(code), name))

    print(f"プライム市場(内国株式): {len(prime)}社")
    with open("tse_prime_universe.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["code", "name"])
        w.writerows(prime)
    print("tse_prime_universe.csv に出力しました。")


if __name__ == "__main__":
    main()
