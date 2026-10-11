# Build the MengRen Desktop (meng ren zhuo mian zhu shou) release from main.py.
#
# Output is one folder, dist\<product>v<version><official>\, holding only the EXE,
# the user guide, the release notes and .env.example. Runtime files live in its
# _internal folder. PyInstaller work files and the generated .spec stay in build\.
# With -Zip it also writes dist\mengren-desktop-v<version>-windows-x64.zip and
# SHA256SUMS.txt for a GitHub release.
param(
    [string]$Python = "",
    [string]$OutputRoot = "",
    [switch]$Zip
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = if ($Python) { $Python } else {
    Join-Path $projectRoot ".venv\Scripts\python.exe"
}
$icon = Join-Path $projectRoot "resources\icons\mengren.ico"
$distRoot = if ($OutputRoot) { $OutputRoot } else {
    Join-Path $projectRoot "dist"
}
$buildRoot = Join-Path $projectRoot "build"
$stagingRoot = Join-Path $buildRoot "pyinstaller-dist"
$bundleName = "MengRenDesktop"
$entryPoint = Join-Path $projectRoot "main.py"
$resourceData = (Join-Path $projectRoot "resources") + ";resources"

$brandingSource = Get-Content `
    -LiteralPath (Join-Path $projectRoot "app\branding.py") `
    -Raw `
    -Encoding UTF8
if ($brandingSource -notmatch '(?m)^APP_VERSION\s*=\s*"([^"]+)"') {
    throw "Unable to read APP_VERSION from app\branding.py."
}
$version = $Matches[1]
$productName = -join @(
    [char]0x731B, [char]0x4EBA, [char]0x684C, [char]0x9762, [char]0x52A9, [char]0x624B
)
$officialName = -join @([char]0x6B63, [char]0x5F0F, [char]0x7248)
$guideName = (-join @([char]0x4F7F, [char]0x7528, [char]0x8BF4, [char]0x660E)) + ".txt"
$notesName = (-join @([char]0x7248, [char]0x672C, [char]0x8BF4, [char]0x660E)) + ".txt"
$displayName = $productName + "v" + $version
$releaseRoot = Join-Path $distRoot ($displayName + $officialName)

# A test build that is still running locks its files and breaks the build half-way.
$running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and (
        $_.Path.StartsWith($distRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $_.Path.StartsWith($buildRoot, [StringComparison]::OrdinalIgnoreCase)
    )
})
if ($running.Count -gt 0) {
    throw "Close the running test build first: $($running[0].Path)"
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --distpath $stagingRoot `
    --workpath (Join-Path $buildRoot "pyinstaller-work") `
    --specpath $buildRoot `
    --name $bundleName `
    --icon $icon `
    --add-data $resourceData `
    --collect-data rapidocr `
    --collect-submodules rapidocr `
    --hidden-import mss `
    --exclude-module PIL._avif `
    --exclude-module PIL.AvifImagePlugin `
    $entryPoint

if ($LASTEXITCODE -ne 0) {
    throw "Release build failed."
}

$bundleRoot = Join-Path $stagingRoot $bundleName
Rename-Item `
    -LiteralPath (Join-Path $bundleRoot "$bundleName.exe") `
    -NewName "$displayName.exe"
Get-ChildItem -LiteralPath $bundleRoot -Recurse -Filter "opencv_videoio_ffmpeg*.dll" |
    Remove-Item -Force

# Qt parts the app never loads. Quick/QML/OpenGL are only pulled in by the virtual
# keyboard plugin and Qt6Pdf only by the PDF image plugin; Qt6Network must stay
# because Qt6Multimedia (reminder sounds) imports it.
$qtRoot = Join-Path $bundleRoot "_internal\PySide6"
$unusedQt = @(
    "opengl32sw.dll",
    "Qt6OpenGL.dll",
    "Qt6Pdf.dll",
    "Qt6Qml.dll",
    "Qt6QmlMeta.dll",
    "Qt6QmlModels.dll",
    "Qt6QmlWorkerScript.dll",
    "Qt6Quick.dll",
    "Qt6VirtualKeyboard.dll",
    "Qt6MultimediaWidgets.dll",
    "QtMultimediaWidgets.pyd",
    "translations",
    "plugins\generic",
    "plugins\networkinformation",
    "plugins\platforminputcontexts",
    "plugins\tls",
    "plugins\imageformats\qicns.dll",
    "plugins\imageformats\qpdf.dll",
    "plugins\imageformats\qtga.dll",
    "plugins\imageformats\qtiff.dll",
    "plugins\imageformats\qwbmp.dll",
    "plugins\platforms\qdirect2d.dll",
    "plugins\platforms\qminimal.dll",
    "plugins\platforms\qoffscreen.dll"
)
foreach ($item in $unusedQt) {
    $path = Join-Path $qtRoot $item
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
Copy-Item `
    -LiteralPath (Join-Path $projectRoot $guideName) `
    -Destination (Join-Path $bundleRoot ($displayName + $officialName + $guideName)) `
    -Force
Copy-Item `
    -LiteralPath (Join-Path $projectRoot $notesName) `
    -Destination $bundleRoot `
    -Force
Copy-Item `
    -LiteralPath (Join-Path $projectRoot ".env.example") `
    -Destination $bundleRoot `
    -Force

if (Test-Path -LiteralPath $releaseRoot) {
    Remove-Item -LiteralPath $releaseRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
Move-Item -LiteralPath $bundleRoot -Destination $releaseRoot
Write-Host "Release package created: $releaseRoot" -ForegroundColor Green

if ($Zip) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zipPath = Join-Path $distRoot "mengren-desktop-v$version-windows-x64.zip"
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    # includeBaseDirectory keeps one top folder, so unzipping never scatters files.
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $releaseRoot,
        $zipPath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $true
    )
    $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
    $sumsPath = Join-Path $distRoot "SHA256SUMS.txt"
    "$hash  $(Split-Path -Leaf $zipPath)" | Set-Content -LiteralPath $sumsPath -Encoding ASCII
    Write-Host "Release zip created: $zipPath" -ForegroundColor Green
    Write-Host "SHA-256: $hash"
}
