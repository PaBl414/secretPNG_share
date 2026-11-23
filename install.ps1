$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$helper = Join-Path $repo 'scripts\install_env.py'
$python = $null
$selector = @()

function Test-Interpreter($executable, [string[]]$prefix) {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $executable @prefix -I $helper --probe 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

$launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($launcher) {
    foreach ($minor in 14,13,12,11,10) {
        $flag = @("-3.$minor")
        if (Test-Interpreter -executable $launcher.Source -prefix $flag) {
            $python = $launcher.Source
            $selector = $flag
            break
        }
    }
}
if (-not $python) {
    $candidate = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($candidate -and (Test-Interpreter -executable $candidate.Source -prefix @())) {
        $python = $candidate.Source
    }
}
if (-not $python) {
    [Console]::Error.WriteLine('Install 64-bit CPython 3.10-3.14 and run the installer again.')
    exit 1
}

& $python @selector -I $helper $repo
if ($LASTEXITCODE -ne 0) { exit 1 }

try {
    $bin = Join-Path $env:LOCALAPPDATA 'secretpng-share\bin'
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $found = $false
    foreach ($entry in ($userPath -split ';')) {
        if ([string]::IsNullOrWhiteSpace($entry)) { continue }
        try {
            $expanded = [Environment]::ExpandEnvironmentVariables($entry.Trim().Trim('"'))
            $normalized = [IO.Path]::GetFullPath($expanded).TrimEnd('\', '/')
            if ($normalized -ieq $bin.TrimEnd('\', '/')) { $found = $true }
        } catch [System.ArgumentException] {}
    }
    if (-not $found) {
        $newPath = if ($userPath) { $userPath + ';' + $bin } else { $bin }
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    }
} catch {
    [Console]::Error.WriteLine('Cannot install into the user directory.')
    exit 1
}

Write-Output 'Open a new login session, then run:'
Write-Output 'secretpng --version'
exit 0
