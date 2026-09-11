# Downloads the ESP32 Arduino core 3.3.11 toolchain files (17 files, 1803 MB)
# that the Arduino IDE Boards Manager fails to fetch on this network.
#
# What we already know about this machine:
#   - Steam++ / Watt Toolkit is installed (C:\Program Files\Steam++\).
#   - It sets HTTPS_PROXY=http://127.0.0.1:52817 for the whole user session.
#   - That local proxy normally works for everything (1.5 GB already
#     downloaded successfully) but resets some HTTPS streams, which the IDE
#     sees as "PROTOCOL_ERROR" or "aborted by the software in your host machine".
#   - HTTP/2 is the trigger. Forcing HTTP/1.1 (curl --http1.1) bypasses it.
#   - The IDE itself does not honor HTTPS_PROXY automatically in older
#     builds - this script does, so its output is fully cached.
#
# Usage (PowerShell):
#   .\download_esp32.ps1            -> only files the ESP32-S3 needs (~659 MB)
#   .\download_esp32.ps1 -All       -> every file the IDE asks for (~1803 MB)
#   .\download_esp32.ps1 -All -NoProxy
#       -> ignore HTTPS_PROXY; if Watt Toolkit's MITM is the cause, this route
#          goes straight to GitHub and usually finishes in one shot.
#
# Safe to run repeatedly. Finished files are skipped; partial ones resume.

param(
    [switch]$All,
    [switch]$NoProxy,
    [int]$Retries = 6
)

$dest = Join-Path $env:LOCALAPPDATA "Arduino15\staging\packages"
if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }

Write-Host ""
Write-Host "Staging folder : $dest" -ForegroundColor Cyan
if ($env:HTTPS_PROXY -and -not $NoProxy) {
    Write-Host "Proxy in use   : $env:HTTPS_PROXY  (HTTPS_PROXY)" -ForegroundColor Cyan
} elseif ($NoProxy) {
    Write-Host "Proxy          : disabled (NoProxy switch)" -ForegroundColor Cyan
} else {
    Write-Host "Proxy          : none set; using direct link" -ForegroundColor Cyan
}
Write-Host "HTTP/1.1 forced, resume on, $Retries retries per file" -ForegroundColor Cyan
Write-Host ""

$files = @(
    @{tag="S3";  name="core";                       file="esp32-core-3.3.11.zip";                         url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32-core-3.3.11.zip";                          sha="a18203f2429f5551ec929b80e8129e439df7a3a009b536b305f00b4a1f1bbb62"; size=46900611}
    @{tag="S3";  name="esp-x32";                    file="xtensa-esp-elf-14.2.0_20260121-x86_64-w64-mingw32.zip";       url="https://github.com/espressif/crosstool-NG/releases/download/esp-14.2.0_20260121/xtensa-esp-elf-14.2.0_20260121-x86_64-w64-mingw32.zip"; sha="82cbe0353c2e7c96acc8755c854aaa2d93d346c6a378fc692e60b3912c560108"; size=413859845}
    @{tag="S3";  name="xtensa-esp-elf-gdb";         file="xtensa-esp-elf-gdb-17.1_20260402-x86_64-w64-mingw32.zip";    url="https://github.com/espressif/binutils-gdb/releases/download/esp-gdb-v17.1_20260402/xtensa-esp-elf-gdb-17.1_20260402-x86_64-w64-mingw32.zip"; sha="7525ae46b39fc87568717d8f0cc3dfbcdb77b96435dd80acfce6918b0abc2b8a"; size=44820924}
    @{tag="ALL"; name="esp-rv32";                   file="riscv32-esp-elf-14.2.0_20260121-x86_64-w64-mingw32.zip";      url="https://github.com/espressif/crosstool-NG/releases/download/esp-14.2.0_20260121/riscv32-esp-elf-14.2.0_20260121-x86_64-w64-mingw32.zip"; sha="c2734714e59f684b74d1cb278f75b4ae9ec546aa1e55d73786ef039410e4a8f7"; size=705866147}
    @{tag="ALL"; name="riscv32-esp-elf-gdb";        file="riscv32-esp-elf-gdb-17.1_20260402-x86_64-w64-mingw32.zip"; url="https://github.com/espressif/binutils-gdb/releases/download/esp-gdb-v17.1_20260402/riscv32-esp-elf-gdb-17.1_20260402-x86_64-w64-mingw32.zip"; sha="f9e56a0d17414a30f7c457f7804173ecfb078b90d94a7b9f6318dc9652575d3f"; size=45474783}
    @{tag="S3";  name="openocd-esp32";              file="openocd-esp32-win64-0.12.0-esp32-20260424.zip";              url="https://github.com/espressif/openocd-esp32/releases/download/v0.12.0-esp32-20260424/openocd-esp32-win64-0.12.0-esp32-20260424.zip"; sha="d0005eea5b916df047afca7b777792050f8c6a6a502407180c8d839e9a841f75"; size=3203098}
    @{tag="S3";  name="esptool_py";                 file="esptool-v5.3.1-windows-amd64.zip";                            url="https://github.com/espressif/esptool/releases/download/v5.3.1/esptool-v5.3.1-windows-amd64.zip"; sha="2b4a73c45db27426685896f64ce3e557f63a64f43cc100cb65c0cc3486af96d3"; size=63962426}
    @{tag="S3";  name="mklittlefs";                 file="x86_64-w64-mingw32-mklittlefs-db0513a.zip";                  url="https://github.com/earlephilhower/mklittlefs/releases/download/4.0.2/x86_64-w64-mingw32-mklittlefs-db0513a.zip"; sha="e99dbfcf2b808a2020254764f06e336aa6a4d253ab09bcabe01399fcd95d9ab8"; size=452707}
    @{tag="S3";  name="esp32-libs";                 file="esp32-libs-3.3.11.zip";                                       url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32-libs-3.3.11.zip"; sha="f7d70b98d83482ef9065f13e9dbe21f8c1292f0dc6e6ee9f1970b3b2e5ea894f"; size=47525987}
    @{tag="ALL"; name="esp32c3-libs";               file="esp32c3-libs-3.3.11.zip";                                     url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32c3-libs-3.3.11.zip"; sha="887067748467a002d9354dc2a14cfd233528e6d89a0b5178db90ba4224e17e5d"; size=59969586}
    @{tag="ALL"; name="esp32c5-libs";               file="esp32c5-libs-3.3.11.zip";                                     url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32c5-libs-3.3.11.zip"; sha="9760dcb7a92306ce169025c74afae104a65c4221f6b1d92c69369748b9cb91f6"; size=70195267}
    @{tag="ALL"; name="esp32c6-libs";               file="esp32c6-libs-3.3.11.zip";                                     url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32c6-libs-3.3.11.zip"; sha="dd7374dabadeced8259ea67c331faa7588afbbed92c2727e7b8c5201f6762ee0"; size=68692102}
    @{tag="ALL"; name="esp32h2-libs";               file="esp32h2-libs-3.3.11.zip";                                     url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32h2-libs-3.3.11.zip"; sha="8a73008ee70bc5a9255798e7732208a533f7d931fa54a2289e5f2c7eed822126"; size=64559520}
    @{tag="ALL"; name="esp32p4-libs";               file="esp32p4-libs-3.3.11.zip";                                     url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32p4-libs-3.3.11.zip"; sha="315868de4dc8cd78fb1b77e07355c605a296abd40ac9d51e78d2b8bd1c61f737"; size=70114877}
    @{tag="ALL"; name="esp32p4_es-libs";            file="esp32p4_es-libs-3.3.11.zip";                                 url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32p4_es-libs-3.3.11.zip"; sha="e286516acfc346b9a465d9f11cfa2686ab3c38a88446f3e5f9de7d903eaeb3cd"; size=69687616}
    @{tag="ALL"; name="esp32s2-libs";               file="esp32s2-libs-3.3.11.zip";                                     url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32s2-libs-3.3.11.zip"; sha="584a2fa2d6e8d9de35233b506bdb60d1492b0fb6de8fa4e7560eb2a3b04aa74a"; size=45421252}
    @{tag="S3";  name="esp32s3-libs";               file="esp32s3-libs-3.3.11.zip";                                     url="https://github.com/espressif/arduino-esp32/releases/download/3.3.11/esp32s3-libs-3.3.11.zip"; sha="fec76794708694120c6ec803cdbfc7dcd36286ea22b7d38097b7909bbd19f7b5"; size=70074478}
)

# Common curl flags. --http1.1 is the single most important one on this
# network: HTTP/2 to GitHub resets mid-stream for unknown reasons, 1.1 doesn't.
$base = @(
    "--http1.1",
    "-L",
    "--retry", "3",
    "--retry-all-errors",
    "--retry-delay", "3",
    "--speed-limit", "1024",
    "--speed-time", "60",
    "--connect-timeout", "30",
    "--max-time", "5400"
)

# If the user did NOT pass -NoProxy and HTTPS_PROXY is set, drive every
# connection through the local proxy (so this looks exactly like the IDE's
# normal traffic, and we exercise the same code path Watt Toolkit is
# misbehaving on).
if (-not $NoProxy -and $env:HTTPS_PROXY) {
    $proxy = $env:HTTPS_PROXY
    Write-Host "Routing all requests through proxy: $proxy" -ForegroundColor DarkGray
    Write-Host "If you keep failing, run again with -NoProxy" -ForegroundColor DarkGray
    Write-Host ""
    $proxyFlag = @("-x", $proxy)
} else {
    $proxyFlag = @()
}

$total = 0; $got = 0; $failed = @()

foreach ($f in $files) {
    if (-not $All -and $f.tag -ne "S3") { continue }
    $total += $f.size
    $path = Join-Path $dest $f.file
    $have = if (Test-Path $path) { (Get-Item $path).Length } else { 0 }

    if ($have -eq $f.size) {
        Write-Host ("[skip] {0,-22} complete ({1,6:N1} MB)" -f $f.name, ($f.size/1MB)) -ForegroundColor DarkGray
        $got += $f.size; continue
    }
    if ($have -gt 0) {
        Write-Host ("[resume] {0,-22} have {1,6:N1} / {2,6:N1} MB" -f $f.name, ($have/1MB), ($f.size/1MB)) -ForegroundColor Cyan
    } else {
        Write-Host ("[get  ] {0,-22} {1,6:N1} MB" -f $f.name, ($f.size/1MB)) -ForegroundColor Yellow
    }

    $ok = $false
    for ($i = 1; $i -le $Retries; $i++) {
        & curl.exe @base $proxyFlag -C - -o "$path" "$($f.url)"
        if ((Test-Path $path) -and ((Get-Item $path).Length -eq $f.size)) {
            $ok = $true; break
        }
        $nowHave = if (Test-Path $path) { (Get-Item $path).Length } else { 0 }
        Write-Host ("         attempt {0}/{1} incomplete ({2:N1} MB on disk), retrying..." -f $i, $Retries, ($nowHave/1MB)) -ForegroundColor DarkYellow
        Start-Sleep -Seconds 3
    }

    # If resume kept failing the partial file is likely garbage - clean retry.
    if (-not $ok -and (Test-Path $path)) {
        Write-Host "         resume stuck, restarting from scratch..." -ForegroundColor DarkYellow
        Remove-Item "$path" -Force
        for ($i = 1; $i -le 2; $i++) {
            & curl.exe @base $proxyFlag -o "$path" "$($f.url)"
            if ((Test-Path $path) -and ((Get-Item $path).Length -eq $f.size)) { $ok = $true; break }
            Start-Sleep -Seconds 3
        }
    }

    if (-not $ok) {
        Write-Host "         FAILED - rerun the script, it resumes" -ForegroundColor Red
        $failed += $f.name; continue
    }

    $h = (Get-FileHash -Algorithm SHA256 "$path").Hash.ToLower()
    if ($h -ne $f.sha.ToLower()) {
        Write-Host "         FAILED (sha256 mismatch) - deleted, retry next run" -ForegroundColor Red
        Remove-Item "$path" -Force
        $failed += $f.name
    } else {
        Write-Host "         ok + sha256 verified" -ForegroundColor Green
        $got += $f.size
    }
}

Write-Host ""
Write-Host ("Progress: {0:N0} MB of {1:N0} MB" -f ($got/1MB), ($total/1MB)) -ForegroundColor Cyan
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "Still missing:" -ForegroundColor Red
    foreach ($n in $failed) { Write-Host "  - $n" -ForegroundColor Red }
    Write-Host ""
    Write-Host "What to try next:" -ForegroundColor Yellow
    Write-Host "  1. Re-run this same command (resumes all unfinished files)" -ForegroundColor Yellow
    Write-Host "  2. If still failing, re-run with -NoProxy  (bypasses Watt Toolkit)" -ForegroundColor Yellow
    Write-Host "  3. If still failing, temporarily turn off Watt Toolkit's proxy, re-run." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "All files staged. Go back to Arduino IDE -> Boards Manager -> install esp32 3.3.11." -ForegroundColor Green
    Write-Host "The IDE will reuse this cache and skip the network entirely." -ForegroundColor Green
    if (-not $All) {
        Write-Host ""
        Write-Host "Note: S3-only set done. If the IDE still asks for files (esp32s2 libs etc.), run with -All." -ForegroundColor Yellow
    }
}
