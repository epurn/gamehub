param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

function Assert-StatusCode([string]$Name, [int]$Expected, [int]$Actual) {
    if ($Expected -ne $Actual) {
        throw "$Name failed. Expected status $Expected but got $Actual."
    }
}

Write-Host "Verifying GAMEHUB server at $BaseUrl"

$healthResponse = Invoke-WebRequest -Uri "$BaseUrl/health" -Method GET -UseBasicParsing
Assert-StatusCode -Name "Health endpoint" -Expected 200 -Actual $healthResponse.StatusCode
Write-Host "PASS /health"

$index = Invoke-RestMethod -Uri "$BaseUrl/v1/index" -Method GET
if ($null -eq $index -or $null -eq $index.index_version) {
    throw "/v1/index did not return an index payload."
}
Write-Host "PASS /v1/index (index_version=$($index.index_version), titles=$($index.titles.Count))"

if ($index.titles.Count -gt 0) {
    $fileId = $index.titles[0].rom.file_id
    if ([string]::IsNullOrWhiteSpace($fileId)) {
        throw "Index title ROM file_id is empty."
    }
    $fileResponse = Invoke-WebRequest -Uri "$BaseUrl/v1/files/$fileId" -Method GET -UseBasicParsing
    Assert-StatusCode -Name "/v1/files/$fileId" -Expected 200 -Actual $fileResponse.StatusCode
    Write-Host "PASS /v1/files/$fileId"
} else {
    Write-Host "SKIP /v1/files/{file_id} (no titles in index)"
}

Write-Host "GAMEHUB deployment verification passed."
