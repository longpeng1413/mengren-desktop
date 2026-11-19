# Launch the packaged EXE and wait for the Qt event loop to confirm startup.
#
# The developer's own copy is usually running at the same time. The test copy
# therefore runs in smoke-test mode (MENGREN_SMOKE_TEST=1): it registers no
# shortcut, shows no tray icon and leaves the startup entry alone, so it never
# reports shortcut conflicts. It also gets a temporary settings folder, deleted
# afterwards, so it never shows the developer's desktop widgets twice or writes
# their settings and logs. As a safety net, every startup entry this product has
# ever used is still saved and restored exactly.
param(
    [int]$Seconds = 12,
    [string]$Executable = ""
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
$exe = if ($Executable) {
    Get-Item -LiteralPath $Executable
} else {
    Get-ChildItem -Path (Join-Path $projectRoot "dist\*\*v$version.exe") | Select-Object -First 1
}
if ($null -eq $exe -or $exe.PSIsContainer -or -not $exe.Name.EndsWith("v$version.exe")) {
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

$tempRoot = (Resolve-Path -LiteralPath ([System.IO.Path]::GetTempPath())).Path.TrimEnd("\")
$sandbox = Join-Path $tempRoot ("mengren-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $sandbox | Out-Null
$ready = Join-Path $sandbox "ready.txt"
$previousAppData = $env:APPDATA
$previousSmokeTest = $env:MENGREN_SMOKE_TEST
$previousReadyFile = $env:MENGREN_SMOKE_READY_FILE
$process = $null
try {
    try {
        $env:APPDATA = $sandbox
        $env:MENGREN_SMOKE_TEST = "1"
        $env:MENGREN_SMOKE_READY_FILE = $ready
        $process = Start-Process -FilePath $exe.FullName -WorkingDirectory $exe.DirectoryName -PassThru
    } finally {
        $env:APPDATA = $previousAppData
        $env:MENGREN_SMOKE_TEST = $previousSmokeTest
        $env:MENGREN_SMOKE_READY_FILE = $previousReadyFile
    }
    if ($process.WaitForExit($Seconds * 1000)) {
        throw "The EXE exited within $Seconds seconds (exit code $($process.ExitCode))."
    }
    if (-not (Test-Path -LiteralPath $ready -PathType Leaf) -or
        (Get-Content -LiteralPath $ready -Raw) -cne $version) {
        $process.Refresh()
        throw "Qt startup was not confirmed within $Seconds seconds. Active window: '$($process.MainWindowTitle)'."
    }
    Write-Host "Qt startup confirmed for v$version : $($exe.FullName)" -ForegroundColor Green
} finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        Start-Sleep -Milliseconds 500
    }
    $resolvedSandbox = (Resolve-Path -LiteralPath $sandbox).Path
    if ((Split-Path -Parent $resolvedSandbox) -ieq $tempRoot -and
        (Split-Path -Leaf $resolvedSandbox) -match '^mengren-smoke-[0-9a-f]{32}$') {
        Remove-Item -LiteralPath $resolvedSandbox -Recurse -Force -ErrorAction SilentlyContinue
    }
    foreach ($name in $names) {
        if ($saved.ContainsKey($name)) {
            Set-ItemProperty -Path $runKey -Name $name -Value $saved[$name]
        } else {
            Remove-ItemProperty -Path $runKey -Name $name -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "Startup entries restored: $($saved.Count) saved, others removed."
