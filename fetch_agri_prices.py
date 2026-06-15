#!/usr/bin/env python3
"""Fetch Taiwan MOA agricultural market prices into SQLite and CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://data.moa.gov.tw/Service/OpenData/FromM/FarmTransData.aspx"
SOURCE_PAGE = "https://data.moa.gov.tw/open_detail.aspx?id=037"

API_TO_DB = {
    "交易日期": "trade_date_roc",
    "種類代碼": "category_code",
    "作物代號": "crop_code",
    "作物名稱": "crop_name",
    "市場代號": "market_code",
    "市場名稱": "market_name",
    "上價": "upper_price",
    "中價": "middle_price",
    "下價": "lower_price",
    "平均價": "average_price",
    "交易量": "volume",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取農業部農產品交易行情，逐頁存入 SQLite，並可輸出 CSV。"
    )
    parser.add_argument("--start", help="起始日：YYYY-MM-DD 或民國 YYY.MM.DD")
    parser.add_argument("--end", help="結束日：YYYY-MM-DD 或民國 YYY.MM.DD")
    parser.add_argument("--crop", help="作物名稱，例如：甘藍-初秋")
    parser.add_argument("--market", help="市場名稱，例如：台北一")
    parser.add_argument("--page-size", type=int, default=1000, choices=range(1, 1001))
    parser.add_argument(
        "--max-pages",
        type=int,
        help="最多抓取頁數；測試時可設 1，正式抓取時省略。",
    )
    parser.add_argument("--db", type=Path, default=Path("data/agri_prices.sqlite3"))
    parser.add_argument("--csv", type=Path, dest="csv_path", help="另存本次抓取結果")
    return parser.parse_args()


def to_roc_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if "." in value:
        datetime.strptime(value, "%Y.%m.%d")
        return value
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return f"{parsed.year - 1911:03d}.{parsed.month:02d}.{parsed.day:02d}"


def roc_to_iso(value: str) -> str:
    year, month, day = (int(part) for part in value.split("."))
    return date(year + 1911, month, day).isoformat()


def build_url(args: argparse.Namespace, skip: int) -> str:
    params: dict[str, Any] = {
        "$top": args.page_size,
        "$skip": skip,
    }
    if args.start:
        params["StartDate"] = to_roc_date(args.start)
    if args.end:
        params["EndDate"] = to_roc_date(args.end)
    if args.crop:
        params["Crop"] = args.crop
    if args.market:
        params["Market"] = args.market
    return f"{API_URL}?{urlencode(params)}"


def fetch_page(url: str, retries: int = 3) -> list[dict[str, Any]]:
    request = Request(url, headers={"User-Agent": "AgriFlowAI-ClassProject/1.0"})
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8-sig"))
            if not isinstance(payload, list):
                raise RuntimeError(f"API 回傳格式異常：{payload!r}")
            return payload
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == retries:
                raise RuntimeError(f"API 呼叫失敗：{url}") from exc
            time.sleep(attempt * 2)
    return []


def open_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_prices (
            trade_date TEXT NOT NULL,
            trade_date_roc TEXT NOT NULL,
            category_code TEXT NOT NULL,
            crop_code TEXT NOT NULL,
            crop_name TEXT NOT NULL,
            market_code TEXT NOT NULL,
            market_name TEXT NOT NULL,
            upper_price REAL,
            middle_price REAL,
            lower_price REAL,
            average_price REAL,
            volume REAL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (
                trade_date, category_code, crop_code, market_code
            )
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_prices_crop_date
        ON market_prices (crop_name, trade_date)
        """
    )
    return connection


def normalize(row: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    normalized = {db_key: row.get(api_key) for api_key, db_key in API_TO_DB.items()}
    for key in (
        "category_code",
        "crop_code",
        "crop_name",
        "market_code",
        "market_name",
    ):
        normalized[key] = str(normalized[key] or "")
    normalized["trade_date"] = roc_to_iso(str(normalized["trade_date_roc"]))
    normalized["fetched_at"] = fetched_at
    return normalized


def upsert_rows(connection: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    columns = ["trade_date", *API_TO_DB.values(), "fetched_at"]
    placeholders = ", ".join(f":{column}" for column in columns)
    updates = ", ".join(
        f"{column} = excluded.{column}"
        for column in columns
        if column not in {"trade_date", "category_code", "crop_code", "market_code"}
    )
    connection.executemany(
        f"""
        INSERT INTO market_prices ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (trade_date, category_code, crop_code, market_code)
        DO UPDATE SET {updates}
        """,
        rows,
    )
    connection.commit()


def main() -> int:
    args = parse_args()
    if args.max_pages is not None and args.max_pages < 1:
        raise ValueError("--max-pages 必須大於 0")

    connection = open_database(args.db)
    csv_file = None
    writer = None
    if args.csv_path:
        args.csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_file = args.csv_path.open("w", encoding="utf-8-sig", newline="")
        writer = csv.DictWriter(csv_file, fieldnames=list(API_TO_DB))
        writer.writeheader()

    total = 0
    page = 0
    try:
        while args.max_pages is None or page < args.max_pages:
            url = build_url(args, skip=page * args.page_size)
            raw_rows = fetch_page(url)
            if not raw_rows:
                break

            fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
            normalized_rows = [normalize(row, fetched_at) for row in raw_rows]
            upsert_rows(connection, normalized_rows)
            if writer:
                writer.writerows(
                    {key: row.get(key) for key in API_TO_DB} for row in raw_rows
                )

            total += len(raw_rows)
            page += 1
            print(f"第 {page} 頁：取得 {len(raw_rows)} 筆，累計 {total} 筆")
            if len(raw_rows) < args.page_size:
                break
    finally:
        if csv_file:
            csv_file.close()
        connection.close()

    print(f"完成：本次取得 {total} 筆；SQLite：{args.db}")
    if args.csv_path:
        print(f"CSV：{args.csv_path}")
    print(f"資料來源：農業部農業資料開放平臺（{SOURCE_PAGE}）")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        raise SystemExit(1)
