# Removes Mimick's launchers, environment and cached voices.
#
# Run it with:
#     powershell -ExecutionPolicy Bypass -File uninstall.ps1

#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalAppData = [Environment]::GetFolderPath('LocalApplicationData')
$AppRoot = Join-Path $LocalAppData 'Mimick'
$BinDir  = Join-Path $AppRoot 'bin'
$Settings = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'Mimick'
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mimick.lnk'

Write-Host ''
Write-Host "This removes Mimick's launchers, its private environment, the"
Write-Host 'downloaded offline voices and its copy of ffmpeg. Your PDFs are'
Write-Host 'not touched.'
Write-Host ''
$reply = Read-Host 'Continue? [y/N]'
if ($reply -notmatch '^[Yy]') { Write-Host 'Cancelled.'; exit 0 }

Remove-Item $StartMenu -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $Here '.venv') -Recurse -Force -ErrorAction SilentlyContinue
# Takes the cached voices, the preview clips and the downloaded ffmpeg with it.
Remove-Item $AppRoot -Recurse -Force -ErrorAction SilentlyContinue

Remove-Item 'HKCU:\Software\Classes\Mimick.Document' -Recurse -Force -ErrorAction SilentlyContinue
Remove-ItemProperty -Path 'HKCU:\Software\Classes\.pdf\OpenWithProgids' `
                    -Name 'Mimick.Document' -Force -ErrorAction SilentlyContinue

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -and $userPath -like "*$BinDir*") {
    $kept = ($userPath -split ';' | Where-Object { $_ -and $_ -ne $BinDir }) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $kept, 'User')
}

Write-Host ''
Write-Host "Mimick removed. Your settings are still in $Settings"
Write-Host '(delete that folder too if you want a clean slate).'
Write-Host ''
