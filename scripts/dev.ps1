#!/usr/bin/env pwsh
<#
.SYNOPSIS
    PowerShell equivalent of the Makefile targets, for machines without GNU Make.

.DESCRIPTION
    The Makefile remains the canonical description of the commands. This script
    mirrors it target for target so the same names work on Windows:

        .\scripts\dev.ps1 migrate
        .\scripts\dev.ps1 generate -Seed 42 -N 500

    Keep the two in step. If you add a target here, add it to the Makefile too.

.EXAMPLE
    .\scripts\dev.ps1 test
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'api', 'web', 'check', 'demo', 'demo-local', 'eval', 'migrate',
                 'generate', 'test', 'lint', 'typecheck', 'client', 'help')]
    [string]$Target = 'help',

    [int]$Seed = 42,
    [int]$N = 500,
    [string]$LocalDatabaseUrl = 'postgresql+asyncpg://postgres:postgres@localhost:5432/fc'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

function Invoke-Step {
    <#
      Run a native command and stop on a non-zero exit code. PowerShell does not
      do this on its own, so without it a failing step would be reported as a
      success by whatever runs next.
    #>
    param(
        [Parameter(Mandatory)][string]$Exe,
        [Parameter(ValueFromRemainingArguments)][string[]]$Arguments
    )
    Write-Host "> $Exe $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "$Exe exited with $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

function Show-Help {
    Write-Host ''
    Write-Host 'Usage: .\scripts\dev.ps1 <target>' -ForegroundColor Cyan
    Write-Host ''
    $targets = [ordered]@{
        'setup'      = 'uv sync + npm install'
        'api'        = 'uvicorn, reload'
        'web'        = 'next dev'
        'demo'       = 'seed + full reconciliation'
        'demo-local' = 'same, local Postgres, LLM_MODE=cache_only, no network'
        'check'      = 'lint + typecheck + test + eval; run this before every commit'
        'eval'       = 'accuracy suite; exits non-zero when a PRD 12.5 gate fails'
        'migrate'    = 'alembic upgrade head'
        'generate'   = 'synthetic corpus (-Seed 42 -N 500)'
        'test'       = 'pytest'
        'lint'       = 'ruff check + ruff format --check'
        'typecheck'  = 'mypy --strict engine/src'
        'client'     = 'regenerate web/lib/api.ts from the OpenAPI schema'
    }
    foreach ($name in $targets.Keys) {
        Write-Host ('  {0,-12} {1}' -f $name, $targets[$name])
    }
    Write-Host ''
}

function Invoke-Setup {
    Invoke-Step uv sync
    Push-Location (Join-Path $Root 'web')
    try { Invoke-Step npm install } finally { Pop-Location }
}

function Invoke-Api {
    Invoke-Step uv run uvicorn api.main:app --reload --port 8000
}

function Invoke-Web {
    Push-Location (Join-Path $Root 'web')
    try { Invoke-Step npm run dev } finally { Pop-Location }
}

function Invoke-Generate {
    $env:SEED = "$Seed"
    $env:N = "$N"
    try { Invoke-Step uv run python -m fc.generator.seed } finally {
        Remove-Item Env:SEED, Env:N -ErrorAction SilentlyContinue
    }
}

function Invoke-Demo {
    Invoke-Generate
    Invoke-Step uv run python -m fc.pipeline --demo
}

function Invoke-DemoLocal {
    # Local Postgres, LLM pinned to its disk cache: nothing leaves the machine.
    $savedUrl = $env:DATABASE_URL
    $savedMode = $env:LLM_MODE
    $env:DATABASE_URL = $LocalDatabaseUrl
    $env:LLM_MODE = 'cache_only'
    try { Invoke-Demo } finally {
        $env:DATABASE_URL = $savedUrl
        $env:LLM_MODE = $savedMode
    }
}

function Invoke-Eval {
    # Runs with no database and no network (PRD §3.7). Exits non-zero when a
    # §12.5 gate fails, so it can actually block a merge rather than printing a
    # number nobody compares to anything.
    Invoke-Step uv run python -m fc.eval.report
}

function Invoke-Check {
    <#
      Everything that gates a commit. `test` deliberately excludes the eval suite
      (it needs the generated corpus and is slow), which meant the
      false_auto_resolutions gate - the merge blocker this whole submission rests
      on - ran only when somebody typed `pytest -m eval` by hand. Run this, not
      `test`.
    #>
    Invoke-Lint
    Invoke-Typecheck
    Invoke-Test
    Invoke-Eval
}

function Invoke-Migrate {
    Invoke-Step uv run alembic upgrade head
}

function Invoke-Test {
    Invoke-Step uv run pytest
}

function Invoke-Lint {
    Invoke-Step uv run ruff check .
    Invoke-Step uv run ruff format --check .
}

function Invoke-Typecheck {
    Invoke-Step uv run mypy --strict engine/src
}

function Invoke-Client {
    # Regenerate the TypeScript client after any Pydantic change.
    $schema = Join-Path $Root 'web/lib/openapi.json'
    & uv run python -m api.main --openapi | Set-Content -Path $schema -Encoding utf8
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Push-Location (Join-Path $Root 'web')
    try { Invoke-Step npx openapi-typescript lib/openapi.json -o lib/api.ts } finally { Pop-Location }
}

Push-Location $Root
try {
    switch ($Target) {
        'setup'      { Invoke-Setup }
        'api'        { Invoke-Api }
        'web'        { Invoke-Web }
        'demo'       { Invoke-Demo }
        'demo-local' { Invoke-DemoLocal }
        'check'      { Invoke-Check }
        'eval'       { Invoke-Eval }
        'migrate'    { Invoke-Migrate }
        'generate'   { Invoke-Generate }
        'test'       { Invoke-Test }
        'lint'       { Invoke-Lint }
        'typecheck'  { Invoke-Typecheck }
        'client'     { Invoke-Client }
        default      { Show-Help }
    }
} finally {
    Pop-Location
}
