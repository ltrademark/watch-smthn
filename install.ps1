# Install watch-smthn on Windows and report what is still missing.
#
# Idempotent: on a machine that already works it changes nothing and touches no
# config. It does not probe for tools itself, because the app resolves them
# through more than PATH (.exe names and the Program Files / LOCALAPPDATA
# roots). All discovery happens in `watch-smthn --doctor`.
#
# Run it with:  powershell -ExecutionPolicy Bypass -File .\install.ps1

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

function Say([string]$Message) {
    Write-Host $Message
}

$python = $null
$pythonArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
    $pythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} else {
    throw "python not found; install Python 3.10 or newer, e.g. winget install Python.Python.3.12"
}

& $python @pythonArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required"
}

# Windows keeps its own venv (.venv-win), so a clone shared with WSL serves a
# PowerShell tab and an Ubuntu tab at the same time. The PATH work sits up
# here because the old shared layout left an entry for .venv\Scripts behind
# and that directory belongs to the Linux side now. Only new terminals see
# these entries, which is why the report below still warns until then.
$venvScripts = Join-Path $PSScriptRoot ".venv-win\Scripts"
$legacyScripts = Join-Path $PSScriptRoot ".venv\Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$entries = @()
if ($userPath) {
    $entries = @($userPath -split ';' | Where-Object { $_ })
}
if ($entries -contains $legacyScripts) {
    $entries = @($entries | Where-Object { $_ -ne $legacyScripts })
    try {
        $joined = $entries -join ';'
        if (-not $entries) { $joined = $null }
        [Environment]::SetEnvironmentVariable("Path", $joined, "User")
        Say "removed the old PATH entry for .venv\Scripts (Windows now uses .venv-win)"
    } catch {
        Say "could not update your user PATH: $($_.Exception.Message)"
    }
}
if (($entries -contains $venvScripts) -and -not (Test-Path ".\.venv-win\Scripts\watch-smthn.exe")) {
    Say "note: watch-smthn.exe is missing from .venv-win\Scripts although it is on your PATH"
    Say "      the venv is rebuilt below"
}

# Prove the venv runs rather than trusting that its launcher file exists: a
# stray directory can hold a pyvenv.cfg pointing at an interpreter that is
# not there, so the file is present and useless. A venv is entirely derived,
# so rebuild it rather than fail later on a confusing missing-path error.
$venvOk = $false
if ((Test-Path ".\.venv-win\Scripts\python.exe") -and (Test-Path ".\.venv-win\pyvenv.cfg")) {
    & ".\.venv-win\Scripts\python.exe" -c "pass" 2>&1 | Out-String | Out-Null
    $venvOk = ($LASTEXITCODE -eq 0)
}
if ((Test-Path ".venv-win") -and -not $venvOk) {
    if (Test-Path ".\.venv-win\bin") {
        Say "rebuilding .venv-win: built for WSL/Linux (its bin\ is present)"
    } else {
        Say "rebuilding .venv-win: it exists but cannot run on Windows"
    }
    $cfg = ".\.venv-win\pyvenv.cfg"
    if (Test-Path $cfg) {
        $homeLine = Select-String -Path $cfg -Pattern '^\s*home\s*=' | Select-Object -First 1
        if ($homeLine) {
            Say "  $($homeLine.Line.Trim())"
        }
    }
    try {
        Remove-Item -Recurse -Force .venv-win -ErrorAction Stop
    } catch {
        throw "could not remove the old .venv-win: $($_.Exception.Message)"
    }
}

if (-not (Test-Path ".venv-win")) {
    Say "creating .venv-win"
    & $python @pythonArgs -m venv .venv-win
    if ($LASTEXITCODE -ne 0) {
        throw "could not create .venv-win"
    }
}

Say "installing watch-smthn and its dependencies"
& ".\.venv-win\Scripts\python.exe" -m pip install --quiet -e .
if ($LASTEXITCODE -ne 0) {
    throw "pip install -e . failed"
}

# Put .venv-win\Scripts on the user PATH so the command works from any directory.
# The entry itself is computed near the top of this script.
if ($entries -notcontains $venvScripts) {
    try {
        [Environment]::SetEnvironmentVariable("Path", (($entries + $venvScripts) -join ';'), "User")
        Say "added $venvScripts to your user PATH (new terminals only)"
    } catch {
        Say "could not update your user PATH: $($_.Exception.Message)"
        Say "  run it with: $venvScripts\watch-smthn.exe"
    }
}

$report = (& ".\.venv-win\Scripts\python.exe" -m watch_smthn --doctor 2>&1 | Out-String)
$doctorStatus = $LASTEXITCODE
Write-Host $report

if ($report -match "missing player") {
    Say ""
    Say "Not ready yet. Install a player, then run this script again:"
    Say "  media player: winget install mpv    (or vlc, or ffmpeg for ffplay)"
}
if ($report -match "warning .*streamlink") {
    Say "  optional:     winget install streamlink    (only for custom streamlink sources)"
}
if ($report -match "warning .*launcher") {
    Say ""
    Say "  PATH:         open a new terminal so .venv-win\Scripts is picked up"
    Say "                until then, run .\.venv-win\Scripts\watch-smthn.exe"
}

if ($doctorStatus -eq 0) {
    if (Get-Command watch-smthn -ErrorAction SilentlyContinue) {
        Say "Ready. Run it with:  watch-smthn"
    } else {
        Say "Ready. Run it with:  .\.venv-win\Scripts\watch-smthn.exe"
    }
}

exit $doctorStatus
