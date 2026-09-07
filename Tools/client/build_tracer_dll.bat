@echo off
rem Build 32-bit tracing DLL for Vainglory PC (PE32 x86 WoW64)
call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x86
if errorlevel 1 exit /b 1

cd /d "%~dp0"
cl.exe /nologo /O2 /W3 /LD halcyon_tracer.cpp /Fe:halcyon_tracer32.dll /link /MACHINE:X86
if errorlevel 1 (
    echo [ERROR] Failed to compile halcyon_tracer32.dll
    exit /b 1
)
echo [SUCCESS] Compiled halcyon_tracer32.dll successfully
