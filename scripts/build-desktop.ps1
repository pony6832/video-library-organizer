param([ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$')][string]$BuildId = (Get-Date -Format 'yyyyMMdd-HHmmss'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$compiler = Join-Path $projectRoot '.tools\build\inno\ISCC.exe'
foreach ($toolPath in @($python, $compiler)) {
    if (-not (Test-Path -LiteralPath $toolPath -PathType Leaf)) { throw "Missing build tool: $toolPath" }
}
# Never clean or overwrite a previous build; validate every existing ancestor.
foreach ($relative in @('build', 'build\desktop', 'dist', "build\desktop\$BuildId", "dist\$BuildId")) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $projectRoot $relative))
    if (-not $candidate.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Output escaped project' }
    if (Test-Path -LiteralPath $candidate) {
        $item = Get-Item -LiteralPath $candidate -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse output directory refused' }
        if (-not $item.PSIsContainer) { throw 'Output is not a directory' }
        if ($relative -eq "build\desktop\$BuildId" -or $relative -eq "dist\$BuildId") { throw 'Build ID already exists; choose a new ID' }
    }
}
$work = Join-Path $projectRoot "build\desktop\$BuildId"
$release = Join-Path $projectRoot "dist\$BuildId"
New-Item -ItemType Directory -Path $work, $release | Out-Null
Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --workpath $work --distpath $release packaging/desktop.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    $bundle = Join-Path $release 'MediaCatalogVideoDesktop'
    Copy-Item -LiteralPath packaging/README-zh-TW.md, packaging/THIRD-PARTY-NOTICES.txt -Destination $bundle
    & $python packaging/audit_bundle.py $bundle --frozen-archive
    if ($LASTEXITCODE -ne 0) { throw 'Bundle audit failed' }
    # pyproject.toml is the single source of the release version.
    $appVersion = (& $python -c "import sys, tomllib; print(tomllib.load(open(sys.argv[1], 'rb'))['project']['version'])" (Join-Path $projectRoot 'pyproject.toml')).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $appVersion) { throw 'Cannot read version from pyproject.toml' }
    # The media library panel ships as the pinned VideoLibraryViewer release,
    # verified by SHA-256; it is installed beside the desktop app in viewer\.
    $viewerPin = Get-Content -LiteralPath packaging/viewer.json -Raw -Encoding UTF8 | ConvertFrom-Json
    $viewerDir = Join-Path $work 'viewer'
    New-Item -ItemType Directory -Path $viewerDir | Out-Null
    # The viewer repository may be private: download through the signed-in
    # GitHub CLI when present, otherwise anonymously (TLS 1.2 for PowerShell 5.1).
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    foreach ($asset in $viewerPin.assets.PSObject.Properties) {
        $target = Join-Path $viewerDir $asset.Name
        if ($gh) {
            & $gh.Source release download $viewerPin.tag --repo $viewerPin.repo --pattern $asset.Name --dir $viewerDir
            if ($LASTEXITCODE -ne 0) { throw "Cannot download $($asset.Name) from $($viewerPin.repo) $($viewerPin.tag)" }
        } else {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -OutFile $target `
                -Uri "https://github.com/$($viewerPin.repo)/releases/download/$($viewerPin.tag)/$($asset.Name)"
        }
        $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        if ($actual -ne $asset.Value.ToUpperInvariant()) { throw "SHA-256 mismatch for $($asset.Name): $actual" }
    }
    & $compiler /Q "/DBundleDir=$bundle" "/DReleaseDir=$release" "/DAppVersion=$appVersion" "/DViewerDir=$viewerDir" packaging/MediaCatalogVideoDesktop.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
    $files = @(Get-ChildItem -LiteralPath $release -Recurse -File)
    $receipt = @($files | ForEach-Object {
        [ordered]@{ path = $_.FullName.Substring($release.Length + 1); bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    })
    $receipt | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $release 'SHA256.json') -Encoding UTF8
    Write-Output "Release directory: $release"
} finally { Pop-Location }
