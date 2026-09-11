@echo off
REM ---------------------------------------------------------------------------
REM Starts Arduino IDE with HTTP/2 turned off in its Go backend.
REM
REM Fixes this error when installing the esp32 board package:
REM   13 INTERNAL: Download failed: stream error: stream ID 7;
REM                PROTOCOL_ERROR; received from peer
REM
REM The Go HTTP client talks HTTP/2 to GitHub. On links that pass through a
REM proxy, corporate firewall or HTTPS-inspecting antivirus, long HTTP/2
REM transfers get reset mid-stream. GODEBUG=http2client=0 forces HTTP/1.1,
REM which has no multiplexed streams to reset.
REM
REM Arduino IDE must be fully closed before running this, otherwise the
REM environment variable is not picked up.
REM ---------------------------------------------------------------------------

set GODEBUG=http2client=0

if exist "%LOCALAPPDATA%\Programs\Arduino IDE\Arduino IDE.exe" (
    start "" "%LOCALAPPDATA%\Programs\Arduino IDE\Arduino IDE.exe"
) else if exist "C:\Program Files\Arduino IDE\Arduino IDE.exe" (
    start "" "C:\Program Files\Arduino IDE\Arduino IDE.exe"
) else (
    echo Arduino IDE not found in the usual locations.
    echo Edit this file and point it at your Arduino IDE.exe
    pause
)
