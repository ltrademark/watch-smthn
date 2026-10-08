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

if ((Test-Path ".venv") -and -not (Test-Path ".\.venv\Scripts\python.exe")) {
    # A checkout shared with WSL carries a venv whose pyvenv.cfg points at
    # /usr/bin, so Windows cannot run it and pip dies with a bare path error.
    # A venv is entirely derived, so rebuild it rather than explain it.
    Say "rebuilding .venv: the existing one was created outside Windows (no .venv\Scripts\python.exe)"
    try {
        Remove-Item -Recurse -Force .venv -ErrorAction Stop
    } catch {
        throw "could not remove the old .venv: $($_.Exception.Message)"
    }
}

if (-not (Test-Path ".venv")) {
    Say "creating .venv"
    & $python @pythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "could not create .venv"
    }
}

Say "installing watch-smthn and its dependencies"
& ".\.venv\Scripts\python.exe" -m pip install --quiet -e .
if ($LASTEXITCODE -ne 0) {
    throw "pip install -e . failed"
}

# Put .venv\Scripts on the user PATH so the command works from any directory.
# Only new terminals see it, so the report below still warns until then.
$venvScripts = Join-Path $PSScriptRoot ".venv\Scripts"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$entries = @()
if ($userPath) {
    $entries = @($userPath -split ';' | Where-Object { $_ })
}
if ($entries -notcontains $venvScripts) {
    try {
        [Environment]::SetEnvironmentVariable("Path", (($entries + $venvScripts) -join ';'), "User")
        Say "added $venvScripts to your user PATH (new terminals only)"
    } catch {
        Say "could not update your user PATH: $($_.Exception.Message)"
        Say "  run it with: $venvScripts\watch-smthn.exe"
    }
}

$report = (& ".\.venv\Scripts\python.exe" -m watch_smthn --doctor 2>&1 | Out-String)
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
    Say "  PATH:         open a new terminal so .venv\Scripts is picked up"
    Say "                until then, run .\.venv\Scripts\watch-smthn.exe"
}

if ($doctorStatus -eq 0) {
    if (Get-Command watch-smthn -ErrorAction SilentlyContinue) {
        Say "Ready. Run it with:  watch-smthn"
    } else {
        Say "Ready. Run it with:  .\.venv\Scripts\watch-smthn.exe"
    }
}

exit $doctorStatus
