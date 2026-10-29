[CmdletBinding()]
param(
    [string]$ApiRepoPath,
    [string]$ExtractorRepoPath,
    [string]$DocumentsRepoPath,
    [switch]$RunIntegration,
    [switch]$SkipLoad,
    [switch]$CleanupOnly
)

$ErrorActionPreference = 'Stop'
$composePath = Join-Path $PSScriptRoot 'compose.yaml'
$runRoot = Join-Path $PSScriptRoot 'run'
$runPath = $runRoot
$metadataPath = Join-Path $runRoot 'last-run.json'
$environmentNames = @(
    'COMPOSE_PROJECT_NAME', 'API_REPO_PATH', 'EXTRACTOR_REPO_PATH', 'DOCUMENTS_REPO_PATH',
    'API_IMAGE', 'EXTRACTOR_IMAGE', 'DOCUMENTS_IMAGE', 'MONGO_DATABASE', 'RUN_DIRECTORY'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$projectStarted = $false
$composeBase = @()

function Set-ComposeEnvironment($metadata) {
    $env:COMPOSE_PROJECT_NAME = $metadata.project
    $env:API_REPO_PATH = $metadata.apiRepoPath
    $env:EXTRACTOR_REPO_PATH = $metadata.extractorRepoPath
    $env:DOCUMENTS_REPO_PATH = $metadata.documentsRepoPath
    $env:API_IMAGE = $metadata.apiImage
    $env:EXTRACTOR_IMAGE = $metadata.extractorImage
    $env:DOCUMENTS_IMAGE = $metadata.documentsImage
    $env:MONGO_DATABASE = $metadata.mongoDatabase
    $env:RUN_DIRECTORY = $metadata.runDirectory
}

function Invoke-LoggedDocker {
    param([string[]]$Arguments, [string]$LogPath)
    $output = & docker @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $output | Set-Content -LiteralPath $LogPath -Encoding utf8
    $output | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $exitCode. See $LogPath"
    }
}

function Wait-Healthy {
    param([string]$Service)
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $containerId = & docker @($composeBase + @('ps', '-q', $Service)) 2>$null
        if ($containerId) {
            $health = & docker inspect --format '{{.State.Health.Status}}' $containerId 2>$null
            if ($health -eq 'healthy') { return }
        }
        Start-Sleep -Seconds 2
    }
    Invoke-LoggedDocker -Arguments ($composeBase + @('logs', '--tail', '100', $Service)) -LogPath (Join-Path $runPath "$Service-health-failure.log")
    throw "$Service did not become healthy within 120 seconds"
}

try {
    New-Item -ItemType Directory -Path $runPath -Force | Out-Null

    if ($CleanupOnly) {
        if ($RunIntegration) { throw 'Use only one of -RunIntegration or -CleanupOnly.' }
        if (-not (Test-Path -LiteralPath $metadataPath)) { throw "No saved run metadata at $metadataPath" }
        $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
        if ($metadata.runId -notmatch '^\d{14}-[a-f0-9]{8}$' -or $metadata.project -ne "pdf-api-real-$($metadata.runId)") {
            throw 'Saved metadata does not identify a harness-created project.'
        }
        $runPath = Join-Path $runRoot $metadata.runId
        if ([System.IO.Path]::GetFullPath($metadata.runDirectory) -ne [System.IO.Path]::GetFullPath($runPath)) {
            throw 'Saved run directory is outside its expected harness path.'
        }
        Set-ComposeEnvironment $metadata
        $composeBase = @('compose', '-p', $metadata.project, '--project-directory', $PSScriptRoot, '-f', $composePath)
        Invoke-LoggedDocker -Arguments ($composeBase + @('down')) -LogPath (Join-Path $runPath 'cleanup.log')
        return
    }

    if (-not $RunIntegration) { throw 'Pass -RunIntegration to create the isolated stack, or -CleanupOnly to remove the last run.' }
    if (-not $ApiRepoPath) { $ApiRepoPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path }
    if (-not $ExtractorRepoPath -or -not $DocumentsRepoPath) {
        throw 'Set -ExtractorRepoPath and -DocumentsRepoPath to the independent sibling clones.'
    }

    $apiRoot = (Resolve-Path -LiteralPath $ApiRepoPath).Path
    $extractorRoot = (Resolve-Path -LiteralPath $ExtractorRepoPath).Path
    $documentsRoot = (Resolve-Path -LiteralPath $DocumentsRepoPath).Path
    foreach ($root in @($apiRoot, $extractorRoot, $documentsRoot)) {
        if (-not (Test-Path -LiteralPath (Join-Path $root '.git'))) { throw "Not a Git checkout: $root" }
    }

    $apiRemote = (& git -C $apiRoot remote get-url origin).Trim()
    $extractorRemote = (& git -C $extractorRoot remote get-url origin).Trim()
    $documentsRemote = (& git -C $documentsRoot remote get-url origin).Trim()
    if ($apiRemote -ne 'https://github.com/Lourdesrizza/pdf-api-service.git') { throw "Unexpected API remote: $apiRemote" }
    if ($extractorRemote -ne 'https://github.com/MaitePuente/pdf-extractor-service.git') { throw "Unexpected Extractor remote: $extractorRemote" }
    if ($documentsRemote -ne 'https://github.com/angelina-magallanes/pdf-document-service.git') { throw "Unexpected Documents remote: $documentsRemote" }

    $extractorHead = (& git -C $extractorRoot rev-parse HEAD).Trim()
    $documentsHead = (& git -C $documentsRoot rev-parse HEAD).Trim()
    if ($extractorHead -ne '5f0de842ee1bcdcd23ce1383427f6b757d8882fa') { throw "Extractor must be at reviewed commit 5f0de842ee1bcdcd23ce1383427f6b757d8882fa; found $extractorHead" }
    if ($documentsHead -ne '8e1214d0ec82df3806c096840e3dea12defe69d5') { throw "Documents must be at reviewed commit 8e1214d0ec82df3806c096840e3dea12defe69d5; found $documentsHead" }
    foreach ($repo in @($extractorRoot, $documentsRoot)) {
        $dirty = @(& git -C $repo status --porcelain) -join "`n"
        if ($dirty) { throw "The pinned sibling checkout must be clean: $repo" }
    }

    $apiHead = (& git -C $apiRoot rev-parse HEAD).Trim()
    $runId = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $project = "pdf-api-real-$runId"
    $safeDatabase = 'pdf_api_' + $runId.Replace('-', '_')
    $runPath = Join-Path $runRoot $runId
    New-Item -ItemType Directory -Path $runPath -Force | Out-Null
    $loadCheck = if ($SkipLoad) { 'skipped' } else { 'run' }
    $metadata = [ordered]@{
        project = $project
        runDirectory = $runPath.Replace('\', '/')
        apiLoadCheck = $loadCheck
        runId = $runId
        apiRepoPath = $apiRoot.Replace('\', '/')
        apiRemote = $apiRemote
        apiHead = $apiHead
        apiWorkingTreeStatus = @(& git -C $apiRoot status --short)
        extractorRepoPath = $extractorRoot.Replace('\', '/')
        extractorRemote = $extractorRemote
        extractorHead = $extractorHead
        documentsRepoPath = $documentsRoot.Replace('\', '/')
        documentsRemote = $documentsRemote
        documentsHead = $documentsHead
        apiImage = "pdf-api-real:$runId"
        extractorImage = "pdf-extractor-real:$runId"
        documentsImage = "pdf-documents-real:$runId"
        mongoDatabase = $safeDatabase
    }
    $metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $metadataPath -Encoding utf8
    $metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runPath 'source-versions.json') -Encoding utf8
    Set-ComposeEnvironment $metadata
    $composeBase = @('compose', '-p', $project, '--project-directory', $PSScriptRoot, '-f', $composePath)
    $projectStarted = $true

    Invoke-LoggedDocker -Arguments @('compose', '--profile', 'client', '-p', $project, '--project-directory', $PSScriptRoot, '-f', $composePath, 'config', '--quiet') -LogPath (Join-Path $runPath 'compose-config.log')
    $expandedConfig = & docker @('compose', '--profile', 'client', '-p', $project, '--project-directory', $PSScriptRoot, '-f', $composePath, 'config', '--format', 'json') 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Could not render the dedicated Compose configuration' }
    $config = ($expandedConfig -join "`n") | ConvertFrom-Json
    $expectedServices = @('api', 'extractor', 'documents', 'mongodb', 'traefik', 'client')
    $actualServices = @($config.services.PSObject.Properties.Name | Sort-Object)
    if (Compare-Object ($expectedServices | Sort-Object) $actualServices) { throw "Unexpected services: $($actualServices -join ', ')" }
    if ($config.networks.isolated.internal -ne $true) { throw 'The test network must be isolated and internal.' }
    foreach ($serviceName in $expectedServices) {
        $service = $config.services.$serviceName
        if ($service.ports) { throw "Published ports are prohibited in this test stack: $serviceName" }
        if ($service.labels.'traefik.enable' -ne 'false') { throw "Traefik labels must stay disabled: $serviceName" }
        if ($serviceName -ne 'client' -and $service.deploy.replicas -ne 1) { throw "Expected one replica for $serviceName" }
    }
    if (Select-String -LiteralPath $composePath -Pattern 'pdf-network|container_name:|/var/run/docker.sock|(?m)^\s*redis\s*:' -Quiet) {
        throw 'The isolated Compose must not use shared network, named containers, Docker socket, or Redis.'
    }

    $fixtureOutput = & python (Join-Path $PSScriptRoot 'generate_fixtures.py') --output $runPath 2>&1
    $fixtureExitCode = $LASTEXITCODE
    $fixtureOutput | Set-Content -LiteralPath (Join-Path $runPath 'fixture-generation.json') -Encoding utf8
    $fixtureOutput | ForEach-Object { Write-Host $_ }
    if ($fixtureExitCode -ne 0) { throw "Fixture generation failed with exit code $fixtureExitCode" }
    Invoke-LoggedDocker -Arguments ($composeBase + @('up', '--build', '--detach', '--wait', '--wait-timeout', '240')) -LogPath (Join-Path $runPath 'up.log')
    Invoke-LoggedDocker -Arguments @('image', 'inspect', $metadata.apiImage, '--format', '{{.Id}} {{.Created}}') -LogPath (Join-Path $runPath 'api-image-inspect.txt')
    Invoke-LoggedDocker -Arguments ($composeBase + @('ps')) -LogPath (Join-Path $runPath 'ps-after-up.txt')

    Invoke-LoggedDocker -Arguments (@('compose', '--profile', 'client', '-p', $project, '--project-directory', $PSScriptRoot, '-f', $composePath, 'run', '--rm', '-T', 'client')) -LogPath (Join-Path $runPath 'functional-check.json')

    $mongoEval = 'const d=db.getSiblingDB("' + $safeDatabase + '"); printjson({version:d.adminCommand({buildInfo:1}).version,count:d.documents.countDocuments({}),indexes:d.documents.getIndexes()});'
    Invoke-LoggedDocker -Arguments ($composeBase + @('exec', '-T', 'mongodb', 'mongosh', '--quiet', '--eval', $mongoEval)) -LogPath (Join-Path $runPath 'mongo-before-restart.json')

    Invoke-LoggedDocker -Arguments ($composeBase + @('restart', 'documents')) -LogPath (Join-Path $runPath 'documents-restart.log')
    Wait-Healthy -Service 'documents'
    Invoke-LoggedDocker -Arguments (@('compose', '--profile', 'client', '-p', $project, '--project-directory', $PSScriptRoot, '-f', $composePath, 'run', '--rm', '-T', '--entrypoint', 'python', 'client', '/tmp/persistence_check.py')) -LogPath (Join-Path $runPath 'persistence-check.json')

    if ($SkipLoad) {
        @{ skipped = $true; reason = 'Load/benchmark omitted by request' } |
            ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runPath 'api-load.json') -Encoding utf8
    } else {
        Invoke-LoggedDocker -Arguments (@('compose', '--profile', 'client', '-p', $project, '--project-directory', $PSScriptRoot, '-f', $composePath, 'run', '--rm', '-T', '--entrypoint', 'python', 'client', '/tmp/check_api.py', 'load', '--url', 'http://api:8000/process', '--pdf', '/fixtures/proof.pdf', '--dedicated-test-environment', '--concurrency', '1', '--duration', '5')) -LogPath (Join-Path $runPath 'api-load.json')
    }

    Invoke-LoggedDocker -Arguments ($composeBase + @('stop', 'extractor')) -LogPath (Join-Path $runPath 'stop-extractor.log')
    Invoke-LoggedDocker -Arguments (@('compose', '--profile', 'client', '-p', $project, '--project-directory', $PSScriptRoot, '-f', $composePath, 'run', '--rm', '-T', '-e', 'CHECK_MODE=extractor-down', '--entrypoint', 'python', 'client', '/tmp/dependency_check.py')) -LogPath (Join-Path $runPath 'extractor-down.json')
    Invoke-LoggedDocker -Arguments ($composeBase + @('start', 'extractor')) -LogPath (Join-Path $runPath 'start-extractor.log')
    Wait-Healthy -Service 'extractor'

    Invoke-LoggedDocker -Arguments ($composeBase + @('stop', 'documents')) -LogPath (Join-Path $runPath 'stop-documents.log')
    Invoke-LoggedDocker -Arguments (@('compose', '--profile', 'client', '-p', $project, '--project-directory', $PSScriptRoot, '-f', $composePath, 'run', '--rm', '-T', '-e', 'CHECK_MODE=documents-down', '--entrypoint', 'python', 'client', '/tmp/dependency_check.py')) -LogPath (Join-Path $runPath 'documents-down.json')

    Invoke-LoggedDocker -Arguments ($composeBase + @('logs', '--no-color')) -LogPath (Join-Path $runPath 'service-logs.txt')
    Invoke-LoggedDocker -Arguments ($composeBase + @('logs', '--no-color', 'traefik')) -LogPath (Join-Path $runPath 'traefik-access.log')
    Write-Host "Integration checks passed. Run files retained under $runPath"
}
catch {
    Write-Error $_
    if ($composeBase.Count -gt 0 -and $projectStarted) {
        try { Invoke-LoggedDocker -Arguments ($composeBase + @('logs', '--tail', '150')) -LogPath (Join-Path $runPath 'failure-logs.txt') } catch { Write-Warning $_ }
    }
    throw
}
finally {
    if ($RunIntegration -and $projectStarted) {
        try { Invoke-LoggedDocker -Arguments ($composeBase + @('down')) -LogPath (Join-Path $runPath 'cleanup.log') } catch { Write-Warning "Compose cleanup failed: $_" }
    }
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
