<#
.SYNOPSIS
    One-shot helper to push the Tauri updater signing secrets into the
    GitHub repo so CI can sign release artifacts.

.DESCRIPTION
    Reads .tauri-keys/drevalis-updater.key + the dev password and
    pushes both as GitHub Actions secrets via ``gh``. Run once from
    the repo root after ``gh auth login``.

.NOTES
    Safe to re-run -- ``gh secret set`` overwrites silently. The
    password is the dev placeholder; rotate before production.
#>
[CmdletBinding()]
param(
    [string]$Repo = "Various5/drevalis-desktop",
    [string]$Password = "drevalis-dev-placeholder"
)

$ErrorActionPreference = "Stop"

$KeyPath = Join-Path $PSScriptRoot "..\.tauri-keys\drevalis-updater.key"
if (-not (Test-Path $KeyPath)) {
    throw "Key file not found: $KeyPath"
}

Write-Host "Pushing TAURI_SIGNING_PRIVATE_KEY -> $Repo" -ForegroundColor Cyan
Get-Content $KeyPath -Raw | gh secret set TAURI_SIGNING_PRIVATE_KEY -R $Repo --body -
if ($LASTEXITCODE -ne 0) { throw "TAURI_SIGNING_PRIVATE_KEY upload failed" }

Write-Host "Pushing TAURI_SIGNING_PRIVATE_KEY_PASSWORD -> $Repo" -ForegroundColor Cyan
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD -R $Repo --body $Password
if ($LASTEXITCODE -ne 0) { throw "TAURI_SIGNING_PRIVATE_KEY_PASSWORD upload failed" }

Write-Host ""
Write-Host "Done. Verifying:" -ForegroundColor Green
gh secret list -R $Repo
