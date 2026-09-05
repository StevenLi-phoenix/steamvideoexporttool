param([string]$DistPath = "$PSScriptRoot\dist-simple")
$ErrorActionPreference = 'Stop'
$previousPath = $env:PATH
try {
    # Prevent unrelated tools' ICU/OpenSSL libraries from entering the Qt bundle.
    $env:PATH = "$PSScriptRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & uv run python -m PyInstaller --clean --noconfirm --windowed --onedir --contents-directory . --name SteamQuickExport --icon "$PSScriptRoot\assets\app-icon.ico" --add-data "$PSScriptRoot\assets\app-icon.ico;assets" --distpath $DistPath --workpath "$PSScriptRoot\build-simple" --add-binary "$PSScriptRoot\dist\ffmpeg.exe;." --add-binary "$PSScriptRoot\dist\ffprobe.exe;." "$PSScriptRoot\steam_quick_export.py"
    if ($LASTEXITCODE -ne 0) { throw 'Quick exporter build failed' }
} finally {
    $env:PATH = $previousPath
}
