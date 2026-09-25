# Mimick installer for Windows. Sets up everything Mimick needs and adds it to
# your Start Menu. Safe to run more than once.
#
# Run it with:
#     powershell -ExecutionPolicy Bypass -File install.ps1
#
# Nothing outside this folder, your Start Menu and %LOCALAPPDATA%\Mimick is
# changed, and nothing here needs administrator rights.

#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv    = Join-Path $Here '.venv'
$VenvPy  = Join-Path $Venv 'Scripts\python.exe'
$VenvPyw = Join-Path $Venv 'Scripts\pythonw.exe'
$LocalAppData = [Environment]::GetFolderPath('LocalApplicationData')
$AppRoot = Join-Path $LocalAppData 'Mimick'
$Cache   = Join-Path $AppRoot 'Cache'
$BinDir  = Join-Path $AppRoot 'bin'
$Icon    = Join-Path $Here 'assets\mimick.ico'
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mimick.lnk'

function Write-Bold($t) { Write-Host $t -ForegroundColor White }
function Write-Ok($t)   { Write-Host "  [ok] $t" -ForegroundColor Green }
function Write-Info($t) { Write-Host "  ->  $t" -ForegroundColor Cyan }
function Write-Fatal($t) {
    Write-Host ''
    Write-Host "  $t" -ForegroundColor Red
    Write-Host ''
    exit 1
}

Write-Host ''
Write-Bold 'Installing Mimick'
Write-Host '  Natural-sounding read-aloud for PDFs.'
Write-Host ''

# --- 1. Python ---------------------------------------------------------------
Write-Bold 'Step 1 of 5  .  Looking for Python'

# Newest first, but only versions Mimick's components are known to have
# Windows wheels for: every requirement resolves to a binary wheel on 3.10
# through 3.14, and 3.15 has no PySide6 yet. Picking a Python that is too new
# fails much later, in pip, with a message about PySide6 rather than Python.
$Known = @('-3.14', '-3.13', '-3.12', '-3.11', '-3.10')

# The "py" launcher is tried before "python" because it never resolves to the
# Microsoft Store stub -- a zero-byte python.exe on PATH that opens the Store
# instead of running anything, which is the usual reason a Windows install
# fails here.
$Python = $null
$pyLauncher = Get-Command 'py' -ErrorAction SilentlyContinue
if ($pyLauncher) {
    foreach ($want in ($Known + '-3')) {
        try {
            $found = & py $want -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { $Python = $found.Trim(); break }
        } catch { $Python = $null }   # not installed; try the next
    }
}
if (-not $Python) {
    $candidate = Get-Command 'python' -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Source -notlike '*WindowsApps*') {
        $Python = $candidate.Source
    }
}
if (-not $Python) {
    Write-Fatal @"
Python 3 was not found.

Install it from https://www.python.org/downloads/ -- tick
"Add python.exe to PATH" on the first screen -- then run this installer again.

(If you installed Python from the Microsoft Store, install it from python.org
instead. The Store copy cannot create the environment Mimick needs.)
"@
}

$verText = (& $Python -c 'import sys; print("%d.%d" % sys.version_info[:2])').Trim()
$ver = [version]$verText
if ($ver -lt [version]'3.10') {
    Write-Fatal "Mimick needs Python 3.10 or newer. Found $verText at $Python.`nInstall a current version from https://www.python.org/downloads/"
}
Write-Ok "Python $verText"
if ($ver -gt [version]'3.14') {
    # Not fatal -- wheels appear for a new Python over its first months, so
    # this may simply work. It just should not fail as a surprise in step 3.
    Write-Host "  [!] Python $verText is newer than anything Mimick has been checked against." -ForegroundColor Yellow
    Write-Host '      If step 3 fails to find a component, install Python 3.13 from' -ForegroundColor Yellow
    Write-Host '      python.org alongside it and run this installer again.' -ForegroundColor Yellow
}

# --- 2. the environment ------------------------------------------------------
Write-Host ''
Write-Bold "Step 2 of 5  .  Setting up Mimick's private environment"
Write-Info 'Nothing outside this folder is changed.'

if (-not (Test-Path $VenvPy)) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Write-Fatal 'Could not create the Python environment.' }
    Write-Ok 'Environment created'
} else {
    Write-Ok 'Environment already exists'
}
& $VenvPy -m pip install --quiet --upgrade pip 2>&1 | Out-Null

# Teach the environment where the package lives. This is the Windows answer to
# the PYTHONPATH launcher on Linux: "python -m mimick" otherwise finds the
# package through the *working directory*, so it works in a terminal opened
# here and fails from the Start Menu with "No module named mimick" and no
# window at all. A .pth file fixes it for every way of starting Mimick at once.
$SitePackages = (& $VenvPy -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])').Trim()
Set-Content -Path (Join-Path $SitePackages 'mimick.pth') -Value $Here -Encoding ASCII
Write-Ok 'Environment knows where Mimick lives'

# --- 3. components -----------------------------------------------------------
Write-Host ''
Write-Bold "Step 3 of 5  .  Downloading Mimick's components"
Write-Info 'This can take a few minutes the first time.'

& $VenvPy -m pip install --quiet -r (Join-Path $Here 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    Write-Fatal 'Could not download the components. Check your internet connection and try again.'
}
Write-Ok 'Components installed'

# --- 4. ffmpeg ---------------------------------------------------------------
Write-Host ''
Write-Bold 'Step 4 of 5  .  Checking for ffmpeg'
Write-Info 'Mimick uses it to decode voices and to save MP3s.'

$FfmpegDir = Join-Path $Cache 'ffmpeg'
$FfmpegExe = Join-Path $FfmpegDir 'ffmpeg.exe'

if (Get-Command 'ffmpeg' -ErrorAction SilentlyContinue) {
    Write-Ok 'ffmpeg is already installed'
} elseif (Test-Path $FfmpegExe) {
    Write-Ok 'ffmpeg already downloaded'
} else {
    Write-Info 'Downloading ffmpeg (about 40 MB)...'
    $zip = Join-Path $env:TEMP 'mimick-ffmpeg.zip'
    $unpack = Join-Path $env:TEMP 'mimick-ffmpeg'
    try {
        # TLS 1.2 is not the default on older Windows PowerShell.
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'   # the progress bar makes this ~10x slower
        Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' `
                          -OutFile $zip -UseBasicParsing
        if (Test-Path $unpack) { Remove-Item $unpack -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $unpack -Force
        $found = Get-ChildItem -Path $unpack -Filter 'ffmpeg.exe' -Recurse |
                 Select-Object -First 1
        if (-not $found) { throw 'ffmpeg.exe was not in the download' }
        New-Item -ItemType Directory -Force -Path $FfmpegDir | Out-Null
        Copy-Item $found.FullName $FfmpegExe -Force
        Write-Ok 'ffmpeg downloaded'
    } catch {
        # Not fatal: Mimick opens and displays PDFs without it, and says so
        # clearly the moment you press play.
        Write-Host "  [!] Could not download ffmpeg: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host '      Mimick will still open, but cannot speak or save MP3s until' -ForegroundColor Yellow
        Write-Host '      ffmpeg is present. Install it yourself with:' -ForegroundColor Yellow
        Write-Host '          winget install Gyan.FFmpeg' -ForegroundColor Yellow
        Write-Host '      then run this installer again.' -ForegroundColor Yellow
    } finally {
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        Remove-Item $unpack -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# --- 5. launchers ------------------------------------------------------------
Write-Host ''
Write-Bold 'Step 5 of 5  .  Adding Mimick to your Start Menu'

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

# pythonw.exe, not python.exe: the "w" build has no console, so no black
# window sits behind Mimick for as long as it is open.
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($StartMenu)
$lnk.TargetPath       = $VenvPyw
$lnk.Arguments        = '-m mimick'
$lnk.WorkingDirectory = [Environment]::GetFolderPath('UserProfile')
$lnk.Description      = 'Listen to PDFs in natural, human-sounding voices'
if (Test-Path $Icon) { $lnk.IconLocation = $Icon }
$lnk.Save()
Write-Ok 'Added to your Start Menu'

# A terminal launcher, for opening a particular file by name.
@"
@echo off
rem Mimick, from a terminal:  mimick "some paper.pdf"
"$VenvPy" -m mimick %*
"@ | Set-Content -Path (Join-Path $BinDir 'mimick.cmd') -Encoding ASCII

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable(
        'Path', (($userPath.TrimEnd(';')) + ';' + $BinDir), 'User')
    Write-Ok 'Added the "mimick" command to your PATH (new terminals only)'
} else {
    Write-Ok 'The "mimick" command is already on your PATH'
}

# Offer Mimick in the "Open with" menu for PDFs, without taking the default
# away from whatever opens them now.
try {
    $progId = 'Software\Classes\Mimick.Document'
    New-Item -Path "HKCU:\$progId\shell\open\command" -Force | Out-Null
    Set-ItemProperty -Path "HKCU:\$progId" -Name '(default)' -Value 'PDF document (Mimick)'
    Set-ItemProperty -Path "HKCU:\$progId\shell\open\command" -Name '(default)' `
                     -Value "`"$VenvPyw`" -m mimick `"%1`""
    if (Test-Path $Icon) {
        New-Item -Path "HKCU:\$progId\DefaultIcon" -Force | Out-Null
        Set-ItemProperty -Path "HKCU:\$progId\DefaultIcon" -Name '(default)' -Value "$Icon,0"
    }
    New-Item -Path 'HKCU:\Software\Classes\.pdf\OpenWithProgids' -Force | Out-Null
    Set-ItemProperty -Path 'HKCU:\Software\Classes\.pdf\OpenWithProgids' `
                     -Name 'Mimick.Document' -Value ([byte[]]@()) -Type Binary
    Write-Ok 'Listed under "Open with" for PDFs'
} catch {
    Write-Host "  [!] Could not add Mimick to the Open with menu: $($_.Exception.Message)" `
               -ForegroundColor Yellow
}

# --- done --------------------------------------------------------------------
Write-Host ''
Write-Bold 'Mimick is ready.'
Write-Host ''
Write-Host '  Open it from the Start Menu - search for "Mimick".'
Write-Host '  Or right-click any PDF and choose  Open with > PDF document (Mimick).'
Write-Host ''
