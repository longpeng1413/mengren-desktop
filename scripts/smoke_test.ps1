# Launch the packaged EXE for a few seconds and confirm it stays running.
#
# The developer's own copy is usually running at the same time. The test copy
# therefore runs in smoke-test mode (MENGREN_SMOKE_TEST=1): it registers no
# shortcut, shows no tray icon and leaves the startup entry alone, so it never
# reports shortcut conflicts. It also gets a temporary settings folder, deleted
# afterwards, so it never shows the developer's desktop widgets twice or writes
# their settings and logs. As a safety net, every startup entry this product has
# ever used is still saved and restored exactly.
param(
    [int]$Seconds = 12
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$brandingSource = Get-Content `
    -LiteralPath (Join-Path $projectRoot "app\branding.py") `
    -Raw `
    -Encoding UTF8
if ($brandingSource -notmatch '(?m)^APP_VERSION\s*=\s*"([^"]+)"') {
    throw "Unable to read APP_VERSION from app\branding.py."
}
$version = $Matches[1]
# Test the EXE of the current version only, never an older copy left in dist\.
$exe = Get-ChildItem -Path (Join-Path $projectRoot "dist\*\*v$version.exe") | Select-Object -First 1
if ($null -eq $exe) {
    throw "No packaged v$version EXE found under dist\. Run build_windows.ps1 first."
}

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$names = @(
    (-join @([char]0x731B, [char]0x4EBA, [char]0x684C, [char]0x9762, [char]0x52A9, [char]0x624B)),
    (-join @([char]0x731B, [char]0x4EBA, [char]0x8F6F, [char]0x4EF6)),
    (-join @([char]0x731B, [char]0x4EBA, [char]0x622A, [char]0x56FE))
)
$saved = @{}
$current = Get-ItemProperty -Path $runKey
foreach ($name in $names) {
    $property = $current.PSObject.Properties[$name]
    if ($null -ne $property) {
        $saved[$name] = [string]$property.Value
    }
}

$sandbox = Join-Path ([System.IO.Path]::GetTempPath()) ("mengren-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $sandbox | Out-Null
$previousAppData = $env:APPDATA
$env:APPDATA = $sandbox
$env:MENGREN_SMOKE_TEST = "1"
try {
    $process = Start-Process -FilePath $exe.FullName -PassThru
} finally {
    $env:APPDATA = $previousAppData
    Remove-Item Env:MENGREN_SMOKE_TEST -ErrorAction SilentlyContinue
}
try {
    $exited = $process.WaitForExit($Seconds * 1000)
} finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        Start-Sleep -Milliseconds 500
    }
    Remove-Item -LiteralPath $sandbox -Recurse -Force -ErrorAction SilentlyContinue
    foreach ($name in $names) {
        if ($saved.ContainsKey($name)) {
            Set-ItemProperty -Path $runKey -Name $name -Value $saved[$name]
        } else {
            Remove-ItemProperty -Path $runKey -Name $name -ErrorAction SilentlyContinue
        }
    }
}

if ($exited) {
    throw "The EXE exited within $Seconds seconds (exit code $($process.ExitCode))."
}
Write-Host "EXE stayed running for $Seconds seconds: $($exe.FullName)" -ForegroundColor Green
Write-Host "Startup entries restored: $($saved.Count) saved, others removed."
