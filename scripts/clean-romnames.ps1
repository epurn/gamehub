# Clean ROM filenames recursively (dry-run by default). Add -Apply to actually rename.
param(
  [string]$Path=".",
  [switch]$Apply
)

$removeTokens = @(
  "USA","U","Europe","EUR","E","Japan","J","World","W","Asia","AUS","Australia","Canada","Korea","KOR","Brazil","BR",
  "En","English","Fr","French","De","German","Es","Spanish","It","Italian","Nl","Dutch","Pt","Portuguese","Sv","Swedish",
  "Rev","Rev.","Revision","Reprint","v","Ver","Version",
  "Beta","Proto","Prototype","Demo","Sample","Preview","Kiosk",
  "Unl","Unlicensed","Pirate","Hack","Trainer","Translation","Translated","Fixed","Patched","Bootleg",
  "NTSC","PAL","SECAM"
)

$tokenAlt = ($removeTokens | Sort-Object -Unique | ForEach-Object { [regex]::Escape($_) }) -join "|"
$groupPattern = "(?:\s*(\((?<g>[^)]*)\)|\[(?<g>[^\]]*)\]))\s*$"
$removeIfContains = "(?i)\b($tokenAlt)\b|(?i)\brev(?:ision)?\.?\s*\d+\b|(?i)\b(rev|ver|v)\.?\s*\d+(\.\d+)?\b|(?i)\b(proto(type)?|beta|demo|sample|kiosk)\b|(?i)^[!+].*"

function Get-CleanName([string]$nameNoExt) {
  $s = $nameNoExt
  while ($true) {
    $m = [regex]::Match($s, $groupPattern)
    if (-not $m.Success) { break }
    $g = $m.Groups["g"].Value.Trim()
    if ($g -match $removeIfContains) {
      $s = [regex]::Replace($s, $groupPattern, "", 1).Trim()
      continue
    }
    break
  }
  ($s -replace "\s{2,}", " ").Trim()
}

Get-ChildItem -LiteralPath $Path -File -Recurse | ForEach-Object {
  $dir  = $_.DirectoryName
  $base = [IO.Path]::GetFileNameWithoutExtension($_.Name)
  $ext  = $_.Extension
  $cleanBase = Get-CleanName $base
  if ([string]::IsNullOrWhiteSpace($cleanBase)) { return }

  $newName = "$cleanBase$ext"
  if ($newName -ceq $_.Name) { return }

  # De-dupe in folder
  $target = Join-Path -Path $dir -ChildPath $newName
  if (Test-Path -LiteralPath $target) {
    $i=2
    do {
      $newName2 = "$cleanBase ($i)$ext"
      $target = Join-Path -Path $dir -ChildPath $newName2
      $i++
    } while (Test-Path -LiteralPath $target)
    $newName = $newName2
  }

  if ($Apply) {
    Rename-Item -LiteralPath $_.FullName -NewName $newName
    "RENAMED: $($_.FullName) -> $(Join-Path $dir $newName)"
  } else {
    "DRYRUN : $($_.FullName) -> $(Join-Path $dir $newName)"
  }
}

if (-not $Apply) { "`nDry run only. Re-run with -Apply to rename." }