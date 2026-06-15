#!/usr/bin/env python3
"""Audit whether the local market-price data is sufficient for the project."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


CORE_CROPS = [
    "甘藍-初秋",
    "小白菜-蚵仔白",
    "青江白菜-小梗",
    "花胡瓜",
    "番茄-牛番茄",
]
CORE_MARKET_CODE = "648"
CORE_MARKET_NAME = "西螺鎮"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="檢查 AgriFlow AI 資料充足度")
    parser.add_argument("--db", type=Path, default=Path("data/agri_prices.sqlite3"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/data_readiness_report.md")
    )
    return parser.parse_args()


def scalar(connection: sqlite3.Connection, sql: str, params: tuple = ()):
    return connection.execute(sql, params).fetchone()[0]


def status(value: int | float, minimum: int | float) -> str:
    return "PASS" if value >= minimum else "FAIL"


def main() -> None:
    args = parse_args()
    connection = sqlite3.connect(args.db)

    total_rows = scalar(connection, "SELECT COUNT(*) FROM market_prices")
    min_date, max_date, distinct_dates = connection.execute(
        """
        SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date)
        FROM market_prices
        """
    ).fetchone()
    date_span = scalar(
        connection,
        """
        SELECT CAST(julianday(MAX(trade_date)) - julianday(MIN(trade_date)) AS INTEGER) + 1
        FROM market_prices
        """,
    )
    market_count = scalar(
        connection, "SELECT COUNT(DISTINCT market_code) FROM market_prices"
    )
    valid_rows = scalar(
        connection,
        """
        SELECT COUNT(*) FROM market_prices
        WHERE crop_name != '休市'
          AND average_price > 0
          AND volume > 0
        """,
    )
    non_rest_rows = scalar(
        connection, "SELECT COUNT(*) FROM market_prices WHERE crop_name != '休市'"
    )
    valid_rate = valid_rows / non_rest_rows * 100 if non_rest_rows else 0

    crop_rows = []
    for crop in CORE_CROPS:
        values = connection.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT trade_date), COUNT(DISTINCT market_code),
                   MIN(trade_date), MAX(trade_date)
            FROM market_prices
            WHERE crop_name = ? AND average_price > 0 AND volume > 0
            """,
            (crop,),
        ).fetchone()
        fixed_market_dates = scalar(
            connection,
            """
            SELECT COUNT(DISTINCT trade_date)
            FROM market_prices
            WHERE crop_name = ?
              AND market_code = ?
              AND average_price > 0
              AND volume > 0
            """,
            (crop, CORE_MARKET_CODE),
        )
        crop_rows.append((crop, *values, fixed_market_dates))

    dashboard_ready = (
        date_span >= 30 and market_count >= 3 and valid_rate >= 95 and total_rows >= 1000
    )
    prediction_ready = all(
        row[2] >= 365 and row[3] >= 5 and row[6] >= 500 for row in crop_rows
    )

    lines = [
        "# AgriFlow AI 資料充足度報告",
        "",
        "## 結論",
        "",
        f"- Dashboard／資料流程展示：**{'足夠' if dashboard_ready else '不足'}**",
        f"- 核心品項價格預測：**{'足夠' if prediction_ready else '不足'}**",
        "- 天氣模型：需另外累積歷史氣象資料，並建立產地或合理地區對照後再使用。",
        "",
        "## 整體資料",
        "",
        "| 指標 | 目前數值 | 最低標準 | 結果 |",
        "| --- | ---: | ---: | --- |",
        f"| 總筆數 | {total_rows:,} | 1,000 | {status(total_rows, 1000)} |",
        f"| 日期範圍 | {min_date} 至 {max_date} | 至少 365 天 | {status(date_span, 365)} |",
        f"| 日曆跨度 | {date_span:,} 天 | 365 天 | {status(date_span, 365)} |",
        f"| 有資料日期 | {distinct_dates:,} 天 | 220 天 | {status(distinct_dates, 220)} |",
        f"| 市場數 | {market_count:,} | 5 | {status(market_count, 5)} |",
        f"| 非休市有效資料率 | {valid_rate:.2f}% | 95% | {status(valid_rate, 95)} |",
        "",
        "## 核心預測品項",
        "",
        f"固定市場模型建議使用：**{CORE_MARKET_NAME}（{CORE_MARKET_CODE}）**。",
        "",
        "| 作物 | 有效筆數 | 全市場交易日 | 市場數 | 西螺鎮交易日 | 最早日期 | 最新日期 | 預測資料標準 |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for crop, rows, dates, markets, first_date, last_date, fixed_dates in crop_rows:
        ready = (
            "PASS" if dates >= 365 and markets >= 5 and fixed_dates >= 500 else "FAIL"
        )
        lines.append(
            f"| {crop} | {rows:,} | {dates:,} | {markets:,} | {fixed_dates:,} | "
            f"{first_date or '-'} | {last_date or '-'} | {ready} |"
        )

    lines.extend(
        [
            "",
            "## 驗收標準",
            "",
            "- Dashboard：至少 30 天、3 個市場、1,000 筆有效行情。",
            "- 價格預測 MVP：每個核心品項至少 365 個有效交易日、涵蓋至少 5 個市場。",
            "- 固定市場模型：每個核心品項在指定市場至少 500 個有效交易日。",
            "- 穩健模型：建議每個核心品項累積 730 天以上，並使用時間序列切分驗證。",
            "- 模型應先與昨日價格、7 日移動平均等 baseline 比較。",
            "- `休市`、零價格、負價格及負交易量不可直接作為正常訓練資料。",
        ]
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    connection.close()
    print(f"完成：{args.output}")
    print(f"Dashboard ready: {dashboard_ready}")
    print(f"Prediction ready: {prediction_ready}")


if __name__ == "__main__":
    main()
