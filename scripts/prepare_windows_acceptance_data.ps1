[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,

    [string]$DestinationRoot = '',

    [switch]$SkipHhConversion
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$siteNames = @('BH', 'DE', 'FS', 'GR', 'HH', 'KA1', 'KA2', 'KA3', 'KO', 'NZ', 'WE')
$resolvedSource = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd('\')
if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $DestinationRoot = Join-Path $resolvedSource 'test-derived'
}
$destinationFullPath = [System.IO.Path]::GetFullPath($DestinationRoot).TrimEnd('\')

if ($destinationFullPath -eq $resolvedSource) {
    throw 'DestinationRoot must not be the source root.'
}
if (Test-Path -LiteralPath $destinationFullPath) {
    throw "Destination already exists: $destinationFullPath. Move or remove it explicitly before rebuilding."
}

foreach ($site in $siteNames) {
    $sitePath = Join-Path $resolvedSource $site
    if (-not (Test-Path -LiteralPath $sitePath -PathType Container)) {
        throw "Required source folder is missing: $sitePath"
    }
}

function Get-RelativeSourcePath {
    param([System.IO.FileInfo]$File)

    return $File.FullName.Substring($resolvedSource.Length + 1)
}

function Get-SourceFile {
    param([string]$RelativePath)

    $path = Join-Path $resolvedSource $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required source image is missing: $RelativePath"
    }
    return Get-Item -LiteralPath $path
}

$sourceFiles = foreach ($site in $siteNames) {
    Get-ChildItem -LiteralPath (Join-Path $resolvedSource $site) -File |
        Where-Object { $_.Extension -match '^\.(tif|tiff)$' }
}
$sourceFiles = @($sourceFiles | Sort-Object FullName)
if ($sourceFiles.Count -ne 430) {
    throw "Expected 430 baseline TIFF files, found $($sourceFiles.Count). Refusing to build from an unexpected corpus."
}

Write-Host 'Hashing the 430-file baseline inventory...'
$inventory = New-Object System.Collections.Generic.List[object]
$hashByRelativePath = @{}
foreach ($file in $sourceFiles) {
    $relativePath = Get-RelativeSourcePath $file
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashByRelativePath[$relativePath] = $hash
    $inventory.Add([pscustomobject]@{
        source_path = $relativePath
        source_sha256 = $hash
        bytes = $file.Length
        last_write_utc = $file.LastWriteTimeUtc.ToString('o')
    })
}

New-Item -ItemType Directory -Path $destinationFullPath | Out-Null
$mapping = New-Object System.Collections.Generic.List[object]

function Add-DerivedCopy {
    param(
        [string]$Dataset,
        [string]$SourceRelativePath,
        [string]$DerivedFilename,
        [string]$SyntheticSite,
        [string]$SyntheticDate,
        [string]$Purpose
    )

    $source = Get-SourceFile $SourceRelativePath
    $datasetPath = Join-Path $destinationFullPath $Dataset
    New-Item -ItemType Directory -Path $datasetPath -Force | Out-Null
    $derivedPath = Join-Path $datasetPath $DerivedFilename
    Copy-Item -LiteralPath $source.FullName -Destination $derivedPath
    $outputHash = (Get-FileHash -LiteralPath $derivedPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $sourceHash = $hashByRelativePath[$SourceRelativePath]
    if ($outputHash -ne $sourceHash) {
        throw "Hash mismatch after copying $SourceRelativePath"
    }

    $mapping.Add([pscustomobject]@{
        dataset = $Dataset
        source_path = $SourceRelativePath
        source_sha256 = $sourceHash
        derived_path = "$Dataset\$DerivedFilename"
        derived_filename = $DerivedFilename
        output_sha256 = $outputHash
        synthetic_site = $SyntheticSite
        synthetic_date = $SyntheticDate
        purpose = $Purpose
        transformation = 'byte-for-byte copy with test-only filename'
        scientific_valid = $false
    })
}

function Add-ConvertedHhImage {
    param([string]$SourceRelativePath)

    $source = Get-SourceFile $SourceRelativePath
    $dataset = 'converted-hh'
    $datasetPath = Join-Path $destinationFullPath $dataset
    New-Item -ItemType Directory -Path $datasetPath -Force | Out-Null
    $derivedFilename = "$($source.BaseName)_converted_for_testing.png"
    $derivedPath = Join-Path $datasetPath $derivedFilename

    $image = [System.Drawing.Image]::FromFile($source.FullName)
    try {
        $bitmap = New-Object System.Drawing.Bitmap $image
        try {
            $bitmap.Save($derivedPath, [System.Drawing.Imaging.ImageFormat]::Png)
        }
        finally {
            $bitmap.Dispose()
        }
    }
    finally {
        $image.Dispose()
    }

    $outputHash = (Get-FileHash -LiteralPath $derivedPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $mapping.Add([pscustomobject]@{
        dataset = $dataset
        source_path = $SourceRelativePath
        source_sha256 = $hashByRelativePath[$SourceRelativePath]
        derived_path = "$dataset\$derivedFilename"
        derived_filename = $derivedFilename
        output_sha256 = $outputHash
        synthetic_site = ''
        synthetic_date = '2026-03-30'
        purpose = 'Decode-control PNG generated from a TIFF rejected by the packaged Pillow decoder'
        transformation = 'Windows System.Drawing decode and lossless PNG encode'
        scientific_valid = $false
    })
}

$stableSource = 'BH\BH-R_T011_L001_02.04.26_105655_001_JP.tiff'
$stableDates = @('01.04.2026', '08.04.2026', '15.04.2026')
for ($index = 0; $index -lt $stableDates.Count; $index++) {
    $date = $stableDates[$index]
    Add-DerivedCopy 'stable-zero-change' $stableSource `
        "RDTEST_STABLE_S001_${date}_OBS$($index + 1).tiff" 'S001' $date `
        'Identical image repeated across synthetic dates; expected zero biological change'
}

$stressSources = @(
    @('BH\BH-R_T011_L001_02.04.26_105655_001_JP.tiff', 'BH\BH-R_T011_L002_02.04.26_105900_001_JP.tiff', 'BH\BH-R_T011_L003_02.04.26_110136_001_JP.tiff'),
    @('FS\Ref_T001_L001_14.04.26_113002_001_Untitled.tiff', 'FS\Ref_T001_L002_14.04.26_112801_001_Untitled.tiff', 'FS\Ref_T001_L003_14.04.26_112604_001_Untitled.tiff'),
    @('KA1\KA 1; Ref_T047_L001_10.04.26_111248_001_Untitled.tiff', 'KA2\KA 2; Ref_T049_L001_10.04.26_113303_001_Untitled.tiff', 'KA3\KA 3; RS_T071_L001_10.04.26_145936_001_Untitled.tiff'),
    @('GR\Ref_T028_L001_12.04.26_144748_001_Untitled.tiff', 'KO\Ref_T073_L001_09.04.26_130129_001_Untitled.tiff', 'WE\Ref_T091_L001_09.04.26_092409_001_Untitled.tiff'),
    @('NZ\Ref_T082_L001_31.03.26_112445_001_Untitled.tiff', 'NZ\Ref_T082_L002_31.03.26_111929_001_Untitled.tiff', 'NZ\Ref_T082_L003_31.03.26_111709_001_Untitled.tiff')
)
$stressDates = @('01.04.2026', '08.04.2026', '15.04.2026')
for ($siteIndex = 0; $siteIndex -lt $stressSources.Count; $siteIndex++) {
    $site = 'S{0:d3}' -f ($siteIndex + 1)
    for ($dateIndex = 0; $dateIndex -lt $stressDates.Count; $dateIndex++) {
        $date = $stressDates[$dateIndex]
        Add-DerivedCopy 'tracking-stress' $stressSources[$siteIndex][$dateIndex] `
            "RDTEST_STRESS_${site}_${date}_OBS$($dateIndex + 1).tiff" $site $date `
            'Mechanically validates grouping, chronological sorting, detection, tracking, and export'
    }
}

$duplicateSources = @(
    'DE\Ref_T019_L001_13.04.26_114918_001_Untitled.tiff',
    'DE\Ref_T019_L001_13.04.26_115454_001_Untitled.tiff',
    'DE\Ref_T019_L002_13.04.26_115220_001_Untitled.tiff'
)
$duplicateDates = @('08.04.2026', '08.04.2026', '15.04.2026')
for ($index = 0; $index -lt $duplicateSources.Count; $index++) {
    $date = $duplicateDates[$index]
    Add-DerivedCopy 'pairing-edge-cases' $duplicateSources[$index] `
        "RDTEST_DUPLICATE_S001_${date}_OBS$($index + 1).tiff" 'S001' $date `
        'Confirms that an entire group containing duplicate observation dates is rejected'
}
Add-DerivedCopy 'pairing-edge-cases' $stableSource `
    'RDTEST_INVALID_S001_31.02.2026_OBS1.tiff' 'S001' 'invalid' `
    'Confirms that impossible calendar dates are rejected'

$crossSiteSources = @(
    'BH\BH-R_T011_L001_02.04.26_105655_001_JP.tiff',
    'DE\Ref_T019_L001_13.04.26_114918_001_Untitled.tiff',
    'FS\Ref_T001_L001_14.04.26_113002_001_Untitled.tiff',
    'GR\Ref_T028_L001_12.04.26_144748_001_Untitled.tiff',
    'HH\066408_T043_L001_30.03.26_101641_001_AM.tiff',
    'KA1\KA 1; Ref_T047_L001_10.04.26_111248_001_Untitled.tiff',
    'KA2\KA 2; Ref_T049_L001_10.04.26_113303_001_Untitled.tiff',
    'KA3\KA 3; RS_T071_L001_10.04.26_145936_001_Untitled.tiff',
    'KO\Ref_T073_L001_09.04.26_130129_001_Untitled.tiff',
    'NZ\Ref_T082_L001_31.03.26_112445_001_Untitled.tiff',
    'WE\Ref_T091_L001_09.04.26_092409_001_Untitled.tiff',
    'BH\BH-R_T011_L002_02.04.26_105900_001_JP.tiff',
    'DE\Ref_T020_L001_13.04.26_112240_001_Untitled.tiff',
    'NZ\Ref_T082_L002_31.03.26_111929_001_Untitled.tiff',
    'NZ\Ref_T082_L003_31.03.26_111709_001_Untitled.tiff',
    'KA1\KA 1; Ref_T047_L002_10.04.26_111045_001_Untitled.tiff'
)
foreach ($sourceRelativePath in $crossSiteSources) {
    $source = Get-SourceFile $sourceRelativePath
    Add-DerivedCopy 'cross-site-smoke\good' $sourceRelativePath $source.Name '' '' `
        'Representative cross-site detection and upload test'
    Add-DerivedCopy 'cross-site-smoke\mixed' $sourceRelativePath $source.Name '' '' `
        'Representative cross-site test with one expected malformed input'
}
$knownBadFirst = 'HH\066408_T043_L002_30.03.26_101417_001_AM.tiff'
$knownBadFirstFile = Get-SourceFile $knownBadFirst
Add-DerivedCopy 'cross-site-smoke\mixed' $knownBadFirst $knownBadFirstFile.Name '' '' `
    'Expected malformed input; batch must continue after this item fails'

$malformedHh = @(
    'HH\066408_T043_L002_30.03.26_101417_001_AM.tiff',
    'HH\066408_T044_L003_30.03.26_102153_001_AM.tiff',
    'HH\066408_T144_L001_30.03.26_103455_001_AM.tiff',
    'HH\066421_T037_L001_30.03.26_125315_001_Untitled.tiff',
    'HH\066421_T038_L002_30.03.26_112554_001_AM.tiff',
    'HH\066421_T039_L002_30.03.26_114218_001_AM.tiff',
    'HH\066421_T040_L003_30.03.26_130936_001_Untitled.tiff',
    'HH\066421_T041_L003_30.03.26_131710_001_Untitled.tiff',
    'HH\066421_T139_L001_30.03.26_115322_001_AM.tiff',
    'HH\066425_T042_L002_30.03.26_133024_001_Untitled.tiff',
    'HH\066425_T142_L002_30.03.26_125915_001_Untitled.tiff'
)
foreach ($sourceRelativePath in $malformedHh) {
    $source = Get-SourceFile $sourceRelativePath
    Add-DerivedCopy 'known-malformed-hh' $sourceRelativePath $source.Name '' '' `
        'Expected TIFF decode failure; validates preflight rejection and batch isolation'
}

if (-not $SkipHhConversion) {
    Add-Type -AssemblyName System.Drawing
    foreach ($sourceRelativePath in $malformedHh) {
        Add-ConvertedHhImage $sourceRelativePath
    }
}

$inventory | Export-Csv -LiteralPath (Join-Path $destinationFullPath 'source-inventory.csv') -NoTypeInformation -Encoding UTF8
$mapping | Export-Csv -LiteralPath (Join-Path $destinationFullPath 'mapping.csv') -NoTypeInformation -Encoding UTF8

$expectedPairs = @(
    [pscustomobject]@{ dataset = 'stable-zero-change'; first = 'RDTEST_STABLE_S001_01.04.2026_OBS1.tiff'; second = 'RDTEST_STABLE_S001_08.04.2026_OBS2.tiff'; expectation = 'track' },
    [pscustomobject]@{ dataset = 'stable-zero-change'; first = 'RDTEST_STABLE_S001_08.04.2026_OBS2.tiff'; second = 'RDTEST_STABLE_S001_15.04.2026_OBS3.tiff'; expectation = 'track' }
)
for ($siteNumber = 1; $siteNumber -le 5; $siteNumber++) {
    $site = 'S{0:d3}' -f $siteNumber
    $expectedPairs += [pscustomobject]@{ dataset = 'tracking-stress'; first = "RDTEST_STRESS_${site}_01.04.2026_OBS1.tiff"; second = "RDTEST_STRESS_${site}_08.04.2026_OBS2.tiff"; expectation = 'track' }
    $expectedPairs += [pscustomobject]@{ dataset = 'tracking-stress'; first = "RDTEST_STRESS_${site}_08.04.2026_OBS2.tiff"; second = "RDTEST_STRESS_${site}_15.04.2026_OBS3.tiff"; expectation = 'track' }
}
$expectedPairs += [pscustomobject]@{ dataset = 'pairing-edge-cases'; first = ''; second = ''; expectation = 'zero pairs; one duplicate-date issue and one invalid-date issue' }
$expectedPairs | Export-Csv -LiteralPath (Join-Path $destinationFullPath 'expected-pairs.csv') -NoTypeInformation -Encoding UTF8

@(
    'RDTEST_STRESS_S004_15.04.2026_OBS3.tiff',
    'RDTEST_STRESS_S001_08.04.2026_OBS2.tiff',
    'RDTEST_STRESS_S005_01.04.2026_OBS1.tiff',
    'RDTEST_STRESS_S002_15.04.2026_OBS3.tiff',
    'RDTEST_STRESS_S003_08.04.2026_OBS2.tiff',
    'RDTEST_STRESS_S001_01.04.2026_OBS1.tiff',
    'RDTEST_STRESS_S004_01.04.2026_OBS1.tiff',
    'RDTEST_STRESS_S005_15.04.2026_OBS3.tiff',
    'RDTEST_STRESS_S002_08.04.2026_OBS2.tiff',
    'RDTEST_STRESS_S003_15.04.2026_OBS3.tiff',
    'RDTEST_STRESS_S005_08.04.2026_OBS2.tiff',
    'RDTEST_STRESS_S001_15.04.2026_OBS3.tiff',
    'RDTEST_STRESS_S003_01.04.2026_OBS1.tiff',
    'RDTEST_STRESS_S004_08.04.2026_OBS2.tiff',
    'RDTEST_STRESS_S002_01.04.2026_OBS1.tiff'
) | Set-Content -LiteralPath (Join-Path $destinationFullPath 'tracking-stress-upload-order.txt') -Encoding UTF8

$summary = [ordered]@{
    generated_utc = [DateTime]::UtcNow.ToString('o')
    baseline_source_root = $resolvedSource
    baseline_file_count = $sourceFiles.Count
    baseline_total_bytes = ($sourceFiles | Measure-Object Length -Sum).Sum
    derived_file_count = $mapping.Count
    stable_zero_change_files = 3
    stable_zero_change_expected_pairs = 2
    tracking_stress_files = 15
    tracking_stress_expected_pairs = 10
    pairing_edge_case_files = 4
    pairing_edge_case_expected_pairs = 0
    cross_site_good_files = 16
    cross_site_mixed_files = 17
    known_malformed_hh_files = 11
    converted_hh_files = $(if ($SkipHhConversion) { 0 } else { 11 })
    scientific_valid = $false
}
$summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destinationFullPath 'summary.json') -Encoding UTF8

$readme = @'
# RootDetector Derived Windows Acceptance Data

These are disposable, synthetic acceptance fixtures. They are not scientific observations and must not be used for ecological conclusions.

- `stable-zero-change`: one identical source image under three dates; expect 2 consecutive tracking pairs and no biological change.
- `tracking-stress`: five synthetic sites with three dates each; expect 10 consecutive pairs. Use the shuffled order in `tracking-stress-upload-order.txt` when selecting individual files.
- `pairing-edge-cases`: expect zero pairs, one duplicate-date warning, and one invalid-date warning.
- `cross-site-smoke/good`: 16 representative images for a successful detection batch.
- `cross-site-smoke/mixed`: the same 16 plus one known malformed TIFF; expect one isolated failure and continued processing.
- `known-malformed-hh`: all 11 TIFFs that failed in the 10 September diagnostics.
- `converted-hh`: lossless PNG controls decoded by Windows System.Drawing. Conversion proves an input-decoder compatibility issue; it does not repair the source TIFFs.

`source-inventory.csv` hashes all 430 baseline TIFFs. `mapping.csv` traces every derived file to its source and transformation. The original site folders are never modified.
'@
$readme | Set-Content -LiteralPath (Join-Path $destinationFullPath 'README.md') -Encoding UTF8

$postBuildCount = 0
foreach ($site in $siteNames) {
    $postBuildCount += @(Get-ChildItem -LiteralPath (Join-Path $resolvedSource $site) -File | Where-Object { $_.Extension -match '^\.(tif|tiff)$' }).Count
}
if ($postBuildCount -ne 430) {
    throw "Baseline file count changed during preparation: expected 430, found $postBuildCount"
}

Write-Host "Created $($mapping.Count) traceable derived files in:"
Write-Host $destinationFullPath
Write-Host 'Expected chronological pairs: 2 stable + 10 stress.'
Write-Host 'Scientific validity: false (test-only synthetic metadata).'
