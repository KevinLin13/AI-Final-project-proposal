#!/usr/bin/env python3
"""Create daily, all-market weighted price series for the core crops."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

from audit_data_readiness import CORE_CROPS, CORE_MARKET_CODE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="建立核心品項每日模型資料集")
    parser.add_argument("--db", type=Path, default=Path("data/agri_prices.sqlite3"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/model/core_daily_prices.csv")
    )
    parser.add_argument(
        "--market-output",
        type=Path,
        default=Path("data/model/core_xiluo_prices.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(args.db)
    placeholders = ", ".join("?" for _ in CORE_CROPS)
    rows = connection.execute(
        f"""
        SELECT
            trade_date,
            crop_code,
            crop_name,
            ROUND(SUM(average_price * volume) / SUM(volume), 4)
                AS weighted_average_price,
            ROUND(SUM(volume), 2) AS total_volume,
            COUNT(DISTINCT market_code) AS market_count,
            ROUND(MIN(average_price), 2) AS minimum_market_price,
            ROUND(MAX(average_price), 2) AS maximum_market_price
        FROM market_prices
        WHERE crop_name IN ({placeholders})
          AND average_price > 0
          AND volume > 0
        GROUP BY trade_date, crop_code, crop_name
        ORDER BY crop_name, trade_date
        """,
        CORE_CROPS,
    ).fetchall()

    market_rows = connection.execute(
        f"""
        SELECT
            trade_date,
            crop_code,
            crop_name,
            market_code,
            market_name,
            average_price,
            volume,
            upper_price,
            middle_price,
            lower_price
        FROM market_prices
        WHERE crop_name IN ({placeholders})
          AND market_code = ?
          AND average_price > 0
          AND volume > 0
        ORDER BY crop_name, trade_date
        """,
        [*CORE_CROPS, CORE_MARKET_CODE],
    ).fetchall()
    connection.close()

    columns = [
        "trade_date",
        "crop_code",
        "crop_name",
        "weighted_average_price",
        "total_volume",
        "market_count",
        "minimum_market_price",
        "maximum_market_price",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"完成：{args.output}，共 {len(rows)} 筆每日品項資料")

    market_columns = [
        "trade_date",
        "crop_code",
        "crop_name",
        "market_code",
        "market_name",
        "average_price",
        "volume",
        "upper_price",
        "middle_price",
        "lower_price",
    ]
    args.market_output.parent.mkdir(parents=True, exist_ok=True)
    with args.market_output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(market_columns)
        writer.writerows(market_rows)
    print(f"完成：{args.market_output}，共 {len(market_rows)} 筆固定市場資料")


if __name__ == "__main__":
    main()
