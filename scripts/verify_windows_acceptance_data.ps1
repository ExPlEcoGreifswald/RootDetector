[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,

    [string]$DerivedRoot = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$source = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd('\')
if ([string]::IsNullOrWhiteSpace($DerivedRoot)) {
    $DerivedRoot = Join-Path $source 'test-derived'
}
$derived = (Resolve-Path -LiteralPath $DerivedRoot).Path.TrimEnd('\')
$inventoryPath = Join-Path $derived 'source-inventory.csv'
$mappingPath = Join-Path $derived 'mapping.csv'

foreach ($requiredPath in @($inventoryPath, $mappingPath, (Join-Path $derived 'summary.json'))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required manifest is missing: $requiredPath"
    }
}

$inventory = @(Import-Csv -LiteralPath $inventoryPath)
$mapping = @(Import-Csv -LiteralPath $mappingPath)
if ($inventory.Count -ne 430) {
    throw "Expected 430 inventory entries, found $($inventory.Count)."
}
if ($mapping.Count -notin @(66, 77)) {
    throw "Expected 66 entries without HH conversion or 77 with conversion, found $($mapping.Count)."
}

Write-Host 'Verifying baseline files against the pre-copy SHA-256 inventory...'
$baselineErrors = New-Object System.Collections.Generic.List[string]
foreach ($item in $inventory) {
    $path = Join-Path $source $item.source_path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $baselineErrors.Add("missing: $($item.source_path)")
        continue
    }
    $file = Get-Item -LiteralPath $path
    if ([int64]$item.bytes -ne $file.Length) {
        $baselineErrors.Add("size changed: $($item.source_path)")
        continue
    }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $item.source_sha256) {
        $baselineErrors.Add("hash changed: $($item.source_path)")
    }
}
if ($baselineErrors.Count -gt 0) {
    throw "Baseline verification failed:`n$($baselineErrors -join "`n")"
}

Write-Host 'Verifying every derived file against mapping.csv...'
$derivedErrors = New-Object System.Collections.Generic.List[string]
foreach ($item in $mapping) {
    if ($item.scientific_valid -ne 'False') {
        $derivedErrors.Add("not marked non-scientific: $($item.derived_path)")
    }
    $path = Join-Path $derived $item.derived_path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $derivedErrors.Add("missing: $($item.derived_path)")
        continue
    }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $item.output_sha256) {
        $derivedErrors.Add("hash changed: $($item.derived_path)")
    }
    if ($item.transformation -eq 'byte-for-byte copy with test-only filename' -and
        $item.source_sha256 -ne $item.output_sha256) {
        $derivedErrors.Add("copy differs from source: $($item.derived_path)")
    }
}
if ($derivedErrors.Count -gt 0) {
    throw "Derived verification failed:`n$($derivedErrors -join "`n")"
}

$expectedCounts = @{
    'stable-zero-change' = 3
    'tracking-stress' = 15
    'pairing-edge-cases' = 4
    'cross-site-smoke\good' = 16
    'cross-site-smoke\mixed' = 17
    'known-malformed-hh' = 11
}
foreach ($dataset in $expectedCounts.Keys) {
    $actual = @($mapping | Where-Object { $_.dataset -eq $dataset }).Count
    if ($actual -ne $expectedCounts[$dataset]) {
        throw "Dataset $dataset has $actual entries; expected $($expectedCounts[$dataset])."
    }
}

$converted = @($mapping | Where-Object { $_.dataset -eq 'converted-hh' })
if ($converted.Count -notin @(0, 11)) {
    throw "Converted HH dataset has $($converted.Count) entries; expected 0 or 11."
}
if ($converted.Count -gt 0) {
    Add-Type -AssemblyName System.Drawing
    foreach ($item in $converted) {
        $path = Join-Path $derived $item.derived_path
        $image = [System.Drawing.Image]::FromFile($path)
        try {
            if ($image.RawFormat.Guid -ne [System.Drawing.Imaging.ImageFormat]::Png.Guid -or
                $image.Width -lt 1 -or $image.Height -lt 1) {
                throw "Converted control is not a readable PNG: $($item.derived_path)"
            }
        }
        finally {
            $image.Dispose()
        }
    }
}

Write-Host 'Acceptance-data verification passed.'
Write-Host 'Baseline: 430 TIFF files unchanged.'
Write-Host "Derived: $($mapping.Count) files present with matching SHA-256 values."
Write-Host 'Expected tracking plan: 2 stable pairs + 10 stress pairs.'
Write-Host 'Scientific validity: false (test-only synthetic metadata).'
