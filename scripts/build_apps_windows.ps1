param(
    [string]$Python = "python",
    [string]$Target = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ReleaseDir = Join-Path $RootDir "release-windows"
$BuildDir = Join-Path $RootDir "build\windows"
$VenvDir = Join-Path $RootDir ".venv-win"

function Invoke-InRoot {
    param([scriptblock]$Script)
    Push-Location $RootDir
    try { & $Script }
    finally { Pop-Location }
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required on PATH."
    }
}

function New-SidecarBinary {
    param(
        [string]$AppName,
        [string]$EntryPoint,
        [string]$TauriApp
    )

    $distPath = Join-Path $BuildDir "dist"
    $workPath = Join-Path $BuildDir "work-$AppName"
    $specPath = Join-Path $BuildDir "spec"
    $binaryDir = Join-Path $RootDir "apps\$TauriApp\src-tauri\binaries"
    $pyInstallerOutput = Join-Path $distPath "$AppName.exe"
    $tauriBinary = Join-Path $binaryDir "$AppName-$Target.exe"

    if (Test-Path (Join-Path $distPath $AppName)) {
        Remove-Item -Recurse -Force (Join-Path $distPath $AppName)
    }
    if (Test-Path (Join-Path $distPath "$AppName.exe")) {
        Remove-Item -Force (Join-Path $distPath "$AppName.exe")
    }
    New-Item -ItemType Directory -Force $binaryDir | Out-Null

    & $VenvDir\Scripts\python.exe -m PyInstaller `
        --clean `
        --onefile `
        --name $AppName `
        --paths (Join-Path $RootDir "python") `
        --distpath $distPath `
        --workpath $workPath `
        --specpath $specPath `
        (Join-Path $RootDir $EntryPoint)

    if (-not (Test-Path $pyInstallerOutput)) {
        throw "PyInstaller did not produce $pyInstallerOutput"
    }
    Copy-Item -Force $pyInstallerOutput $tauriBinary
    Write-Host "Prepared sidecar: $tauriBinary"
}

Require-Command npm
Require-Command cargo
Require-Command rustc

New-Item -ItemType Directory -Force $BuildDir | Out-Null
New-Item -ItemType Directory -Force $ReleaseDir | Out-Null

if (-not (Test-Path $VenvDir)) {
    & $Python -m venv $VenvDir
}

& $VenvDir\Scripts\python.exe -m pip install --upgrade pip
& $VenvDir\Scripts\python.exe -m pip install pyinstaller

New-SidecarBinary -AppName "ship-sender-backend" -EntryPoint "python\ship_sender_app.py" -TauriApp "sender"
New-SidecarBinary -AppName "ship-manager-backend" -EntryPoint "python\ship_manager_app.py" -TauriApp "manager"

foreach ($app in @("sender", "manager", "log-viewer")) {
    $appDir = Join-Path $RootDir "apps\$app"
    if (Test-Path (Join-Path $appDir "package-lock.json")) {
        npm --prefix $appDir ci
    } else {
        npm --prefix $appDir install
    }
    npm --prefix $appDir run build
    npm --prefix $appDir run tauri -- build --bundles nsis --target $Target
}

$artifactPatterns = @(
    "apps\sender\src-tauri\target\$Target\release\bundle\nsis\*.exe",
    "apps\manager\src-tauri\target\$Target\release\bundle\nsis\*.exe",
    "apps\log-viewer\src-tauri\target\$Target\release\bundle\nsis\*.exe"
)

foreach ($pattern in $artifactPatterns) {
    Get-ChildItem (Join-Path $RootDir $pattern) | ForEach-Object {
        Copy-Item -Force $_.FullName $ReleaseDir
        Write-Host "Copied Windows installer: $($_.Name)"
    }
}

$produced = Get-ChildItem $ReleaseDir -Filter "*.exe"
if ($produced.Count -eq 0) {
    throw "No Windows installers were produced in $ReleaseDir"
}

Write-Host "Windows build complete: $ReleaseDir"
