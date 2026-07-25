$ErrorActionPreference = "Stop"

$uvCommand = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uvCommand) {
    $uvCommand = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe"
}
if (-not (Test-Path -LiteralPath $uvCommand)) {
    throw "uv was not found. Install it with winget or add it to PATH."
}

& $uvCommand run pyinstaller --noconfirm --clean --onefile --windowed --name SteamVideoExporter steam_video_exporter.py

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distRoot = Join-Path $projectRoot "dist"
foreach ($binary in @("ffmpeg.exe", "ffprobe.exe")) {
    $source = Join-Path $projectRoot $binary
    if (-not (Test-Path -LiteralPath $source)) {
        $command = Get-Command ([IO.Path]::GetFileNameWithoutExtension($binary)) -ErrorAction SilentlyContinue
        if ($command) {
            $source = $command.Source
        }
    }
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $distRoot $binary) -Force
    }
}

Write-Host "Built $distRoot\SteamVideoExporter.exe"
