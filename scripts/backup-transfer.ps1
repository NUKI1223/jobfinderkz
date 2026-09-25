$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-DockerChecked {
    param([string[]]$DockerArgs)
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker operation failed: $($DockerArgs[0])" }
}

$backupFolder = Join-Path (Get-Location) ('backups/transfer-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backupFolder | Out-Null
# Stop writers so the SQL dump and files describe the same application checkpoint.
$runningServices = @(& docker compose ps --services --status running)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect services' }
$writers = @($runningServices | Where-Object { $_ -in @('api', 'worker') })
$dbContainer = (& docker compose ps -q db).Trim()
if ($LASTEXITCODE -ne 0 -or -not $dbContainer) { throw 'Start the db service first' }
$apiContainer = (& docker compose ps -a -q api).Trim()
if ($LASTEXITCODE -ne 0 -or -not $apiContainer) { throw 'An API container with the storage volume is required' }
$dumpName = '/tmp/jobfinder-transfer-' + [guid]::NewGuid().ToString('N') + '.dump'
try {
    if ($writers.Count) { Invoke-DockerChecked -DockerArgs (@('compose', 'stop') + $writers) }
    Invoke-DockerChecked -DockerArgs @('exec', $dbContainer, 'pg_dump', '-U', 'jobfinder', '-d', 'jobfinder', '-Fc', '-f', $dumpName)
    Invoke-DockerChecked -DockerArgs @('exec', $dbContainer, 'pg_restore', '--list', $dumpName) | Out-Null
    Invoke-DockerChecked -DockerArgs @('cp', "${dbContainer}:$dumpName", (Join-Path $backupFolder 'jobfinder.dump'))
    Invoke-DockerChecked -DockerArgs @('cp', "${apiContainer}:/storage", (Join-Path $backupFolder 'storage'))
    Copy-Item -LiteralPath '.env' -Destination (Join-Path $backupFolder '.env')
    Copy-Item -LiteralPath 'docs/DEVICE_TRANSFER.md' -Destination $backupFolder
    $files = Get-ChildItem -LiteralPath $backupFolder -File -Recurse -Force
    $manifest = foreach ($file in $files) {
        [pscustomobject]@{
            path = $file.FullName.Substring($backupFolder.Length + 1)
            bytes = $file.Length
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        }
    }
    $manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $backupFolder 'SHA256.json') -Encoding UTF8
    Write-Output "Private backup completed: $backupFolder"
} finally {
    & docker exec $dbContainer rm -f $dumpName
    if ($writers.Count) { Invoke-DockerChecked -DockerArgs (@('compose', 'start') + $writers) }
}
