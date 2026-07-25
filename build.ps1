$ErrorActionPreference = "Stop"

python -m PyInstaller --noconfirm --clean --onefile --windowed --name SteamVideoExporter steam_video_exporter.py

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distRoot = Join-Path $projectRoot "dist"
foreach ($binary in @("ffmpeg.exe", "ffprobe.exe")) {
    $source = Join-Path $projectRoot $binary
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $distRoot $binary) -Force
    }
}

Write-Host "Built $distRoot\SteamVideoExporter.exe"
