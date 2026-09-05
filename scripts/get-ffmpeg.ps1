param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\dist"),
    [string]$Version = "7.1.1",
    [string]$ExpectedSha256 = "04861d3339c5ebe38b56c19a15cf2c0cc97f5de4fa8910e4d47e5e6404e4a2d4"
)
$ErrorActionPreference = 'Stop'
# Pinned FFmpeg essentials build verified by hash, so CI and local builds are
# reproducible and do not break when gyan.dev rotates its "release" alias.
$url = "https://github.com/GyanD/codexffmpeg/releases/download/$Version/ffmpeg-$Version-essentials_build.zip"
$archive = Join-Path ([System.IO.Path]::GetTempPath()) "ffmpeg-$Version-essentials_build.zip"

if ((Test-Path $archive) -and (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $ExpectedSha256) {
    Write-Output "Using cached ffmpeg-$Version archive."
} else {
    Invoke-WebRequest -Uri $url -OutFile $archive
}

$hash = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($hash -ne $ExpectedSha256) {
    throw "SHA256 mismatch for ffmpeg-$Version`: expected $ExpectedSha256, got $hash"
}

$extractRoot = Join-Path ([System.IO.Path]::GetTempPath()) "ffmpeg-$Version-essentials_build"
if (Test-Path $extractRoot) { Remove-Item $extractRoot -Recurse -Force }
Expand-Archive -LiteralPath $archive -DestinationPath $extractRoot
$bin = (Get-ChildItem $extractRoot -Recurse -Filter ffmpeg.exe | Select-Object -First 1).DirectoryName
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Copy-Item (Join-Path $bin "ffmpeg.exe") $Destination -Force
Copy-Item (Join-Path $bin "ffprobe.exe") $Destination -Force
Write-Output "FFmpeg $Version verified and installed into $Destination"
