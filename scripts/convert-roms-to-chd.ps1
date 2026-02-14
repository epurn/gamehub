# Convert PSX/PS2 ROM sets to CHD (dry-run by default).
# - Supports direct .cue/.iso files and .7z archives containing disc images.
# - Uses chdman for conversion.
# - Uses 7z or tar for archive extraction.
# - Moves original sources into roms/<system>/_source/<title>/ by default to avoid duplicate-stem indexing conflicts.
#
# Examples:
#   .\scripts\convert-roms-to-chd.ps1
#   .\scripts\convert-roms-to-chd.ps1 -Apply
#   .\scripts\convert-roms-to-chd.ps1 -Apply -Systems PSX
#   .\scripts\convert-roms-to-chd.ps1 -Apply -KeepSources
#
[CmdletBinding()]
param(
  [string]$DataRoot = $(if ($env:GAMEHUB_DATA_DIR) { $env:GAMEHUB_DATA_DIR } else { "..\data" }),
  [string[]]$Systems = @("PSX", "PS2"),
  [switch]$Apply,
  [switch]$Overwrite,
  [switch]$KeepSources,
  [string]$ChdmanPath = "",
  [string]$ArchiveToolPath = "",
  [string]$SourceSubdir = "_source"
)

$ErrorActionPreference = "Stop"

function Resolve-Executable {
  param(
    [string]$ExplicitPath,
    [string[]]$Candidates
  )

  if ($ExplicitPath) {
    if (-not (Test-Path -LiteralPath $ExplicitPath)) {
      throw "Executable not found: $ExplicitPath"
    }
    return (Resolve-Path -LiteralPath $ExplicitPath).Path
  }

  foreach ($candidate in $Candidates) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) {
      return $cmd.Source
    }
  }
  return $null
}

function Get-CueReferencedFiles {
  param([string]$CuePath)
  $dir = Split-Path -Parent $CuePath
  $result = New-Object System.Collections.Generic.List[string]
  foreach ($line in Get-Content -LiteralPath $CuePath -Encoding UTF8) {
    if ($line -match '^\s*FILE\s+"([^"]+)"') {
      $candidate = Join-Path $dir $matches[1]
      if (Test-Path -LiteralPath $candidate) {
        $result.Add((Resolve-Path -LiteralPath $candidate).Path)
      }
    }
  }
  return $result | Sort-Object -Unique
}

function Get-DiscSourceFromFolder {
  param(
    [string]$SystemName,
    [string]$FolderPath
  )

  $files = Get-ChildItem -LiteralPath $FolderPath -File -Recurse -ErrorAction SilentlyContinue
  $cues = $files | Where-Object { $_.Extension.ToLowerInvariant() -eq ".cue" } | Sort-Object FullName
  if ($cues.Count -gt 0) {
    return $cues[0].FullName
  }
  $isos = $files | Where-Object { $_.Extension.ToLowerInvariant() -eq ".iso" } | Sort-Object FullName
  if ($isos.Count -gt 0) {
    return $isos[0].FullName
  }
  return $null
}

function Get-ChdMode {
  param(
    [string]$SystemName,
    [string]$SourcePath
  )

  $ext = [IO.Path]::GetExtension($SourcePath).ToLowerInvariant()
  if ($ext -eq ".cue") {
    return "createcd"
  }
  if ($ext -eq ".iso") {
    if ($SystemName -eq "PS2") {
      return "createdvd"
    }
    return "createcd"
  }
  throw "Unsupported source extension for chd conversion: $SourcePath"
}

function Extract-ArchiveToFolder {
  param(
    [string]$ToolPath,
    [string]$ArchivePath,
    [string]$DestinationPath
  )

  New-Item -ItemType Directory -Force -Path $DestinationPath | Out-Null
  $toolLeaf = [IO.Path]::GetFileName($ToolPath).ToLowerInvariant()
  if ($toolLeaf.StartsWith("7z")) {
    & $ToolPath x -y "-o$DestinationPath" $ArchivePath | Out-Null
    if ($LASTEXITCODE -ne 0) {
      throw "7z extraction failed for $ArchivePath (exit $LASTEXITCODE)"
    }
    return
  }

  # tar fallback (bsdtar on Windows can handle .7z in many setups)
  & $ToolPath -xf $ArchivePath -C $DestinationPath | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "tar extraction failed for $ArchivePath (exit $LASTEXITCODE)"
  }
}

function Move-ToSourceStash {
  param(
    [string]$RomDir,
    [string]$TitleBase,
    [string[]]$SourcePaths,
    [string]$SubdirName
  )

  $stashRoot = Join-Path $RomDir $SubdirName
  $stashDir = Join-Path $stashRoot $TitleBase
  New-Item -ItemType Directory -Force -Path $stashDir | Out-Null
  foreach ($sourcePath in ($SourcePaths | Sort-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $sourcePath)) {
      continue
    }
    $targetPath = Join-Path $stashDir ([IO.Path]::GetFileName($sourcePath))
    Move-Item -LiteralPath $sourcePath -Destination $targetPath -Force
    Write-Output "MOVED  : $sourcePath -> $targetPath"
  }
}

function Invoke-ChdConversion {
  param(
    [string]$ChdmanExe,
    [string]$Mode,
    [string]$InputPath,
    [string]$OutputPath
  )

  & $ChdmanExe $Mode -i $InputPath -o $OutputPath | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "chdman $Mode failed for $InputPath (exit $LASTEXITCODE)"
  }
}

$resolvedDataRoot = (Resolve-Path -LiteralPath $DataRoot).Path
$romsRoot = Join-Path $resolvedDataRoot "roms"
if (-not (Test-Path -LiteralPath $romsRoot)) {
  throw "ROM root not found: $romsRoot"
}

$chdmanExe = Resolve-Executable -ExplicitPath $ChdmanPath -Candidates @("chdman.exe", "chdman")
if (-not $chdmanExe) {
  throw "chdman was not found. Install MAME/chdman and ensure it is on PATH, or pass -ChdmanPath."
}

$archiveTool = Resolve-Executable -ExplicitPath $ArchiveToolPath -Candidates @("7z.exe", "7z", "tar.exe", "tar")

$converted = 0
$skipped = 0
$failed = 0

Write-Output "GAMEHUB CHD normalize"
Write-Output "data_root: $resolvedDataRoot"
Write-Output "roms_root: $romsRoot"
Write-Output "systems: $($Systems -join ', ')"
Write-Output "mode: $(if ($Apply) { 'apply' } else { 'dry-run' })"
Write-Output "keep_sources: $KeepSources"
Write-Output "overwrite: $Overwrite"
Write-Output "chdman: $chdmanExe"
Write-Output "archive_tool: $(if ($archiveTool) { $archiveTool } else { '<none>' })"
Write-Output ""

foreach ($systemName in $Systems) {
  $romDir = Join-Path $romsRoot $systemName
  if (-not (Test-Path -LiteralPath $romDir)) {
    Write-Output "SKIP   : system dir missing: $romDir"
    continue
  }

  Write-Output "SYSTEM : $systemName ($romDir)"
  $files = Get-ChildItem -LiteralPath $romDir -File -ErrorAction SilentlyContinue | Sort-Object Name
  $cueFiles = $files | Where-Object { $_.Extension.ToLowerInvariant() -eq ".cue" }
  $isoFiles = $files | Where-Object { $_.Extension.ToLowerInvariant() -eq ".iso" }
  $archiveFiles = $files | Where-Object { $_.Extension.ToLowerInvariant() -eq ".7z" }

  # Convert direct .cue files first.
  foreach ($cue in $cueFiles) {
    $titleBase = [IO.Path]::GetFileNameWithoutExtension($cue.Name)
    $outputPath = Join-Path $romDir "$titleBase.chd"
    if ((Test-Path -LiteralPath $outputPath) -and -not $Overwrite) {
      Write-Output "SKIP   : exists: $outputPath"
      $skipped++
      continue
    }
    Write-Output "PLAN   : cue -> chd ($systemName) '$($cue.Name)' -> '$([IO.Path]::GetFileName($outputPath))'"
    if (-not $Apply) {
      continue
    }

    try {
      if ((Test-Path -LiteralPath $outputPath) -and $Overwrite) {
        Remove-Item -LiteralPath $outputPath -Force
      }
      Invoke-ChdConversion -ChdmanExe $chdmanExe -Mode "createcd" -InputPath $cue.FullName -OutputPath $outputPath
      Write-Output "DONE   : $outputPath"
      if (-not $KeepSources) {
        $related = @($cue.FullName) + (Get-CueReferencedFiles -CuePath $cue.FullName)
        Move-ToSourceStash -RomDir $romDir -TitleBase $titleBase -SourcePaths $related -SubdirName $SourceSubdir
      }
      $converted++
    }
    catch {
      Write-Output "FAIL   : $($_.Exception.Message)"
      $failed++
    }
  }

  # Convert direct .iso files, skipping ones that share a stem with a cue file.
  $cueStemSet = @{}
  foreach ($cue in $cueFiles) {
    $cueStemSet[[IO.Path]::GetFileNameWithoutExtension($cue.Name).ToLowerInvariant()] = $true
  }
  foreach ($iso in $isoFiles) {
    $titleBase = [IO.Path]::GetFileNameWithoutExtension($iso.Name)
    if ($cueStemSet.ContainsKey($titleBase.ToLowerInvariant())) {
      Write-Output "SKIP   : matching cue exists for '$($iso.Name)'"
      $skipped++
      continue
    }
    $outputPath = Join-Path $romDir "$titleBase.chd"
    if ((Test-Path -LiteralPath $outputPath) -and -not $Overwrite) {
      Write-Output "SKIP   : exists: $outputPath"
      $skipped++
      continue
    }
    $mode = if ($systemName -eq "PS2") { "createdvd" } else { "createcd" }
    Write-Output "PLAN   : iso -> chd ($mode) '$($iso.Name)' -> '$([IO.Path]::GetFileName($outputPath))'"
    if (-not $Apply) {
      continue
    }

    try {
      if ((Test-Path -LiteralPath $outputPath) -and $Overwrite) {
        Remove-Item -LiteralPath $outputPath -Force
      }
      Invoke-ChdConversion -ChdmanExe $chdmanExe -Mode $mode -InputPath $iso.FullName -OutputPath $outputPath
      Write-Output "DONE   : $outputPath"
      if (-not $KeepSources) {
        Move-ToSourceStash -RomDir $romDir -TitleBase $titleBase -SourcePaths @($iso.FullName) -SubdirName $SourceSubdir
      }
      $converted++
    }
    catch {
      Write-Output "FAIL   : $($_.Exception.Message)"
      $failed++
    }
  }

  # Convert .7z archives.
  foreach ($archive in $archiveFiles) {
    $titleBase = [IO.Path]::GetFileNameWithoutExtension($archive.Name)
    $outputPath = Join-Path $romDir "$titleBase.chd"
    if ((Test-Path -LiteralPath $outputPath) -and -not $Overwrite) {
      Write-Output "SKIP   : exists: $outputPath"
      $skipped++
      continue
    }
    if (-not $archiveTool) {
      Write-Output "SKIP   : no archive extractor found for '$($archive.Name)' (install 7z/tar or pass -ArchiveToolPath)"
      $skipped++
      continue
    }

    Write-Output "PLAN   : 7z -> chd ($systemName) '$($archive.Name)' -> '$([IO.Path]::GetFileName($outputPath))'"
    if (-not $Apply) {
      continue
    }

    $tempExtract = Join-Path $romDir (".chd_extract_" + [Guid]::NewGuid().ToString("N"))
    try {
      if ((Test-Path -LiteralPath $outputPath) -and $Overwrite) {
        Remove-Item -LiteralPath $outputPath -Force
      }
      Extract-ArchiveToFolder -ToolPath $archiveTool -ArchivePath $archive.FullName -DestinationPath $tempExtract
      $discSource = Get-DiscSourceFromFolder -SystemName $systemName -FolderPath $tempExtract
      if (-not $discSource) {
        throw "archive did not contain .cue or .iso: $($archive.FullName)"
      }
      $mode = Get-ChdMode -SystemName $systemName -SourcePath $discSource
      Invoke-ChdConversion -ChdmanExe $chdmanExe -Mode $mode -InputPath $discSource -OutputPath $outputPath
      Write-Output "DONE   : $outputPath"
      if (-not $KeepSources) {
        Move-ToSourceStash -RomDir $romDir -TitleBase $titleBase -SourcePaths @($archive.FullName) -SubdirName $SourceSubdir
      }
      $converted++
    }
    catch {
      Write-Output "FAIL   : $($_.Exception.Message)"
      $failed++
    }
    finally {
      if (Test-Path -LiteralPath $tempExtract) {
        Remove-Item -LiteralPath $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
      }
    }
  }

  Write-Output ""
}

Write-Output "SUMMARY: converted=$converted skipped=$skipped failed=$failed"
if (-not $Apply) {
  Write-Output "Dry run only. Re-run with -Apply to perform conversion."
}
