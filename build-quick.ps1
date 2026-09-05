# Local personal builds default to relying on PATH ffmpeg to save ~170 MB;
# pass -BundleFFmpeg (CI/release) to embed the pinned dist\ binaries.
param([string]$DistPath = "$PSScriptRoot\dist-simple", [switch]$BundleFFmpeg)
$ErrorActionPreference = 'Stop'
# Resolve uv's location before the PATH is restricted below, since uv itself
# usually lives outside .venv\Scripts (e.g. a runner tool dir in CI).
$uv = (Get-Command uv -ErrorAction Stop).Source
$ffmpegArgs = @()
if ($BundleFFmpeg) {
    foreach ($tool in @("ffmpeg.exe", "ffprobe.exe")) {
        if (-not (Test-Path "$PSScriptRoot\dist\$tool")) { throw "dist\$tool missing - run .\scripts\get-ffmpeg.ps1 first" }
    }
    $ffmpegArgs = @("--add-binary", "$PSScriptRoot\dist\ffmpeg.exe;.", "--add-binary", "$PSScriptRoot\dist\ffprobe.exe;.")
}
$previousPath = $env:PATH
# PySide6 ships many modules this raster-only Widgets app never imports
# (QML/Quick, PDF, Network, SVG, OpenGL, VirtualKeyboard); excluding them by
# name keeps PyInstaller from bundling their Qt DLLs and Python bindings.
$excludedModules = @(
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQmlModels", "PySide6.QtQmlMeta",
    "PySide6.QtQmlWorkerScript", "PySide6.QtPdf", "PySide6.QtNetwork", "PySide6.QtSvg",
    "PySide6.QtOpenGL", "PySide6.QtVirtualKeyboard"
)
$excludeArguments = $excludedModules | ForEach-Object { "--exclude-module", $_ }
try {
    # Prevent unrelated tools' ICU/OpenSSL libraries from entering the Qt bundle.
    $env:PATH = "$PSScriptRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & $uv run python -m PyInstaller --clean --noconfirm --windowed --onedir --contents-directory . --name SteamQuickExport --icon "$PSScriptRoot\assets\app-icon.ico" --add-data "$PSScriptRoot\assets\app-icon.ico;assets" --distpath $DistPath --workpath "$PSScriptRoot\build-simple" @ffmpegArgs @excludeArguments "$PSScriptRoot\steam_quick_export.py"
    if ($LASTEXITCODE -ne 0) { throw 'Quick exporter build failed' }
    # --exclude-module only stops Python imports; PyInstaller's Qt hook still
    # bundles the matching Qt6 DLLs and plugins as binary dependencies. The
    # app is a raster-only Widgets app (ICO/JPEG images, no QML/PDF/network),
    # so drop them from the onedir bundle explicitly.
    $bundle = Join-Path $DistPath "SteamQuickExport"
    $pyside = Join-Path $bundle "PySide6"
    $removable = @(
        "opengl32sw.dll",
        "Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlMeta.dll", "Qt6QmlModels.dll", "Qt6QmlWorkerScript.dll",
        "Qt6Pdf.dll", "Qt6Network.dll", "Qt6Svg.dll", "Qt6OpenGL.dll", "Qt6VirtualKeyboard.dll",
        "plugins\iconengines\qsvgicon.dll",
        "plugins\imageformats\qpdf.dll", "plugins\imageformats\qsvg.dll"
    )
    foreach ($relative in $removable) {
        $file = Join-Path $pyside $relative
        if (Test-Path $file) { Remove-Item $file -Force }
    }
    foreach ($pluginDir in @("plugins\networkinformation", "plugins\tls")) {
        $dir = Join-Path $pyside $pluginDir
        if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    }
} finally {
    $env:PATH = $previousPath
}
