# Launch the packaged EXE for a few seconds and confirm it stays running.
#
# A packaged EXE re-points an existing Windows startup entry to itself on launch.
# This script saves every startup entry this product has ever used and restores
# them exactly afterwards, so testing never touches the developer's real setup.
param(
    [int]$Seconds = 12
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$exe = Get-ChildItem -Path (Join-Path $projectRoot "dist\*\*.exe") | Select-Object -First 1
if ($null -eq $exe) {
    throw "No packaged EXE found under dist\. Run build_windows.ps1 first."
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

$process = Start-Process -FilePath $exe.FullName -PassThru
try {
    $exited = $process.WaitForExit($Seconds * 1000)
} finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        Start-Sleep -Milliseconds 500
    }
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
