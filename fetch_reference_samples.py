#!/usr/bin/env python3
"""Download small, analysis-ready samples from Taiwan MOA OpenAPI."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://data.moa.gov.tw/api/v1"
TRANSACTION_API = (
    "https://data.moa.gov.tw/Service/OpenData/FromM/FarmTransData.aspx"
)
OUTPUT_DIR = Path("data/reference_samples")
SAMPLE_SIZE = 20


def fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "AgriFlowAI-ClassProject/1.0"})
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def api_rows(dataset: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    query = urlencode(params or {})
    url = f"{API_BASE}/{dataset}/"
    if query:
        url = f"{url}?{query}"
    payload = fetch_json(url)
    if isinstance(payload, list):
        return payload
    if payload.get("RS") != "OK":
        raise RuntimeError(f"{dataset} API 回傳失敗：{payload!r}")
    return payload.get("Data") or []


def write_csv(filename: str, rows: list[dict[str, Any]]) -> None:
    path = OUTPUT_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        print(f"{filename}: API 未回傳資料")
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{filename}: {len(rows)} 筆")


def flatten_rest_days(rows: list[dict[str, Any]], roc_year: int = 115) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for market in rows:
        for market_type in market.get("MarketTypeList", []):
            for year in market_type.get("YearList", []):
                if year.get("Year") != roc_year:
                    continue
                for month in year.get("MonthList", []):
                    for day in str(month.get("Rest") or "").split("、"):
                        if not day:
                            continue
                        result.append(
                            {
                                "MarketCode": market.get("MarkerNo"),
                                "MarketName": market.get("MarkerName"),
                                "MarketType": market_type.get("MarketType"),
                                "RestDateROC": (
                                    f"{roc_year:03d}.{int(month['Month']):02d}.{int(day):02d}"
                                ),
                                "RestDate": (
                                    f"{roc_year + 1911:04d}-{int(month['Month']):02d}-{int(day):02d}"
                                ),
                            }
                        )
    return result


def market_fallback() -> list[dict[str, Any]]:
    params = {"$top": 1000, "$skip": 0}
    rows = fetch_json(f"{TRANSACTION_API}?{urlencode(params)}")
    markets = {
        (row.get("市場代號"), row.get("市場名稱"))
        for row in rows
        if row.get("市場代號") and row.get("市場名稱")
    }
    return [
        {
            "MarketCode": code,
            "MarketName": name,
            "SourceNote": "CropMarketType API 無資料，改由農產品交易行情整理",
        }
        for code, name in sorted(markets)
    ]


def main() -> None:
    crops = api_rows("CropType", {"Page": 1})
    markets = api_rows("CropMarketType", {"Page": 1})
    rest_days = flatten_rest_days(api_rows("MarketRestDayFarmWCF"))
    weather = api_rows("AutoWeatherStationType", {"Page": 1})
    rainfall = api_rows("AutoRainfallStationType", {"Page": 1})
    costs = api_rows("ProductCost")
    pork = api_rows("PorkTransType", {"Page": 1})
    poultry = api_rows("PoultryTransType_BoiledChicken_Eggs", {"Page": 1})

    if not markets:
        markets = market_fallback()

    datasets = {
        "crops_sample.csv": crops,
        "markets_sample.csv": markets,
        "market_rest_days_sample.csv": rest_days,
        "weather_sample.csv": weather,
        "rainfall_sample.csv": rainfall,
        "product_costs_sample.csv": costs,
        "pork_market_sample.csv": pork,
        "poultry_eggs_sample.csv": poultry,
    }
    for filename, rows in datasets.items():
        write_csv(filename, rows[:SAMPLE_SIZE])


if __name__ == "__main__":
    main()
