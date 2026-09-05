param([string]$DistPath = "$PSScriptRoot\dist-simple")
$ErrorActionPreference = 'Stop'
$previousPath = $env:PATH
try {
    # Prevent unrelated tools' ICU/OpenSSL libraries from entering the Qt bundle.
    $env:PATH = "$PSScriptRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & "$PSScriptRoot\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --windowed --onedir --contents-directory . --name SteamQuickExport --distpath $DistPath --workpath "$PSScriptRoot\build-simple" --add-binary "$PSScriptRoot\dist\ffmpeg.exe;." --add-binary "$PSScriptRoot\dist\ffprobe.exe;." "$PSScriptRoot\steam_quick_export.py"
    if ($LASTEXITCODE -ne 0) { throw 'Quick exporter build failed' }
} finally {
    $env:PATH = $previousPath
}
