$ErrorActionPreference = "Stop"

$crops = @(
    "甘藍-初秋",
    "小白菜-蚵仔白",
    "青江白菜-小梗",
    "花胡瓜",
    "番茄-牛番茄"
)

foreach ($crop in $crops) {
    Write-Host "Backfilling $crop"
    python fetch_agri_prices.py `
        --start 2024-06-16 `
        --end 2026-06-15 `
        --crop $crop

    if ($LASTEXITCODE -ne 0) {
        throw "Backfill failed: $crop"
    }
}

python audit_data_readiness.py
python prepare_model_dataset.py
