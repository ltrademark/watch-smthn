# One-line installer for watch-smthn, no git required.
#
#   irm https://raw.githubusercontent.com/ltrademark/watch-smthn/master/watch-smthn.ps1 | iex
#
# Downloads the source archive from GitHub into a fixed directory and runs the
# project's own install.ps1 inside it, so the one-liner and a git checkout end
# in the same place. Re-running it refreshes the source and reinstalls.
#
# Overrides, mostly for testing:
#   WATCH_SMTHN_HOME         install directory (default: %LOCALAPPDATA%\watch-smthn)
#   WATCH_SMTHN_ARCHIVE_URL  source archive, .zip with a single top directory

$repo = 'ltrademark/watch-smthn'
$target = if ($env:WATCH_SMTHN_HOME) { $env:WATCH_SMTHN_HOME } else { Join-Path $env:LOCALAPPDATA 'watch-smthn' }
$target = $target.TrimEnd('\', '/')
$archive = if ($env:WATCH_SMTHN_ARCHIVE_URL) { $env:WATCH_SMTHN_ARCHIVE_URL } else { "https://github.com/$repo/archive/refs/heads/master.zip" }

# Saved and restored so an iex run leaves the caller's preference untouched.
$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'Stop'
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("watch-smthn-" + [System.IO.Path]::GetRandomFileName())
$code = 1
try {
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'source.zip'
    Invoke-WebRequest -Uri $archive -OutFile $zip -UseBasicParsing

    $unpacked = Join-Path $tmp 'unpacked'
    New-Item -ItemType Directory -Path $unpacked | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $unpacked)

    $src = Get-ChildItem -Directory $unpacked | Select-Object -First 1
    if (-not $src -or -not (Test-Path (Join-Path $src.FullName 'install.ps1'))) {
        throw 'the download did not contain install.ps1'
    }

    if (Test-Path (Join-Path $target '.git')) {
        Write-Host "found a git checkout at $target; leaving its source alone"
        Write-Host "  refresh it with: git -C `"$target`" pull"
    } else {
        if (Test-Path $target) {
            Write-Host "refreshing $target"
            Remove-Item -Recurse -Force $target
        }
        $parent = Split-Path -Parent $target
        if ($parent -and -not (Test-Path $parent)) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Move-Item -Path $src.FullName -Destination $target
        Write-Host "downloaded to $target"
    }

    # A child process keeps install.ps1's Set-Location and exit out of this
    # session, which matters most when this script itself was piped in.
    $hostExe = (Get-Process -Id $PID).Path
    & $hostExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $target 'install.ps1')
    $code = $LASTEXITCODE
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    $ErrorActionPreference = $previousPreference
}

# exit would close a shell that piped this script in, so only a real -File run
# gets an exit code; an iex run reports failure by throwing instead.
if ($PSCommandPath) { exit $code }
if ($code -ne 0) { throw "install.ps1 exited with code $code" }
