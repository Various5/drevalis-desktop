<#
.SYNOPSIS
    Build a standalone Drevalis bundle for Windows.

.DESCRIPTION
    1. Cleans previous dist/ and build/ output.
    2. Verifies the FFmpeg sidecars are present (downloads them via
       scripts/fetch_sidecars.py if missing).
    3. Runs PyInstaller against drevalis-backend.spec.
    4. Copies resources/bin/win/* into the bundle so the bundled binary
       resolves the sidecars at runtime via core.binaries.

    Output: dist/drevalis/drevalis.exe (one-folder).

.NOTES
    Run from the repo root, with the .venv already populated:

        uv sync --extra dev
        scripts\build\win.ps1

    The .venv/Scripts/python.exe interpreter is invoked explicitly so
    the script doesn't depend on PATH activation.
#>
[CmdletBinding()]
param(
    [switch]$SkipClean,
    [switch]$SkipFetch
)

# NOTE: $ErrorActionPreference is intentionally NOT 'Stop'. PyInstaller
# writes its INFO log to stderr; with Stop set, PowerShell 5.1 halts on
# the first stderr line as if it were a real error. We check
# $LASTEXITCODE explicitly instead.
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$BundleDir = Join-Path $RepoRoot "dist\drevalis"
$SidecarSrc = Join-Path $RepoRoot "resources\bin\win"
$SidecarDst = Join-Path $BundleDir "_internal\resources\bin\win"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "[build-win] $msg" -ForegroundColor Cyan
}

if (-not (Test-Path $Python)) {
    throw "Expected venv Python at $Python -- run 'uv sync --extra dev' first."
}

# ── 1) Clean prior output ────────────────────────────────────────────────
if (-not $SkipClean) {
    Write-Step "Cleaning dist/ and build/"
    foreach ($d in @("dist", "build")) {
        $p = Join-Path $RepoRoot $d
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
}

# ── 2) Ensure sidecars are present ───────────────────────────────────────
if (-not $SkipFetch) {
    Write-Step "Ensuring FFmpeg sidecar present"
    & $Python (Join-Path $RepoRoot "scripts\fetch_sidecars.py")
    if ($LASTEXITCODE -ne 0) {
        throw "fetch_sidecars.py failed (exit $LASTEXITCODE)"
    }
}

if (-not (Test-Path (Join-Path $SidecarSrc "ffmpeg.exe"))) {
    throw "FFmpeg sidecar missing at $SidecarSrc -- run scripts\fetch_sidecars.py"
}

# ── 2b) Frontend build (optional) ────────────────────────────────────────
# Only runs when npm is on PATH. The spec + FastAPI lifespan both
# skip the SPA mount when frontend/dist is missing, so a dev install
# without Node still produces a working backend-only bundle.
$FrontendDir = Join-Path $RepoRoot "frontend"
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Step "Building frontend (npm run build)"
    Push-Location $FrontendDir
    try {
        if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
            & npm ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
        }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    } finally {
        Pop-Location
    }
} else {
    Write-Step "Skipping frontend build (npm not found) -- bundle will be backend-only"
}

# ── 3) PyInstaller build ─────────────────────────────────────────────────
Write-Step "Running PyInstaller"
$Spec = Join-Path $RepoRoot "drevalis-backend.spec"
& $Python -m PyInstaller $Spec --noconfirm --clean --log-level WARN
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (exit $LASTEXITCODE)"
}

if (-not (Test-Path (Join-Path $BundleDir "drevalis.exe"))) {
    throw "Expected dist\drevalis\drevalis.exe -- build did not produce it"
}

# ── 4) Copy sidecars into the bundle ─────────────────────────────────────
Write-Step "Copying sidecars into bundle"
New-Item -ItemType Directory -Force -Path $SidecarDst | Out-Null
foreach ($name in @("ffmpeg.exe", "ffprobe.exe", "redis-server.exe", "redis-cli.exe")) {
    $src = Join-Path $SidecarSrc $name
    if (Test-Path $src) {
        Copy-Item -Force $src $SidecarDst
    } else {
        Write-Host "  skip: $name not in $SidecarSrc"
    }
}

# ── 5) Report ────────────────────────────────────────────────────────────
$bundleSize = (Get-ChildItem -Recurse $BundleDir | Measure-Object -Property Length -Sum).Sum
$bundleMB = [math]::Round($bundleSize / 1MB, 1)

Write-Step "Done."
Write-Host "  Bundle:    $BundleDir"
Write-Host "  Entry:     $BundleDir\drevalis.exe"
Write-Host "  Size:      $bundleMB MB"
Write-Host ""
Write-Host "  Smoke:     $BundleDir\drevalis.exe smoke" -ForegroundColor Green
Write-Host "  Run:       $BundleDir\drevalis.exe run" -ForegroundColor Green
