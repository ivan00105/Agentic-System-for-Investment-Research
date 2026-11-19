$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Check-Exit([string] $step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit $LASTEXITCODE)." }
}

# Keep setup's temporary files inside the project on restricted Windows hosts.
$taskTemp = Join-Path $PSScriptRoot '.tmp'
New-Item -ItemType Directory -Force -Path $taskTemp | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv .venv
    Check-Exit 'Virtual environment setup'
}

$dependencyStamp = Join-Path $PSScriptRoot '.venv\fieldnote-dependencies.sha256'
$dependencyHash = (Get-FileHash requirements.lock).Hash + (Get-FileHash pyproject.toml).Hash
$previousHash = if (Test-Path $dependencyStamp) { Get-Content $dependencyStamp -Raw } else { '' }
if ($previousHash.Trim() -ne $dependencyHash) {
    & $python -m pip install -r requirements.lock
    Check-Exit 'Python dependency installation'
    & $python -m pip install --no-deps --no-build-isolation -e .
    Check-Exit 'Application installation'
    Set-Content -LiteralPath $dependencyStamp -Value $dependencyHash
}

$frontendStamp = Join-Path $PSScriptRoot 'frontend\node_modules\.fieldnote-lock.sha256'
$frontendHash = (Get-FileHash frontend/package-lock.json).Hash
$previousFrontendHash = if (Test-Path $frontendStamp) { Get-Content $frontendStamp -Raw } else { '' }
if ($previousFrontendHash.Trim() -ne $frontendHash) {
    npm.cmd --prefix frontend ci --no-audit --no-fund
    Check-Exit 'Frontend dependency installation'
    Set-Content -LiteralPath $frontendStamp -Value $frontendHash
}

$bundle = Join-Path $PSScriptRoot 'frontend\dist\index.html'
$sourcePaths = @('frontend/src', 'frontend/index.html', 'frontend/vite.config.ts', 'frontend/package.json', 'frontend/package-lock.json', 'frontend/tsconfig.json')
$newestSource = Get-ChildItem -LiteralPath $sourcePaths -Recurse -File | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if (-not (Test-Path $bundle) -or $newestSource.LastWriteTimeUtc -gt (Get-Item $bundle).LastWriteTimeUtc) {
    npm.cmd --prefix frontend run build
    Check-Exit 'Frontend build'
}

Write-Host 'Fieldnote is starting at http://127.0.0.1:8000. Press Ctrl+C to stop.'
& $python -m research_assistant.cli
Check-Exit 'Research server'
