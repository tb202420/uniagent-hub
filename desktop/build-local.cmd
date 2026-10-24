@echo off
rem 绕过 vswhere（winget 安装未注册实例）：直接注入 MSVC + Win SDK 环境后编译 Tauri 外壳
set "MSVC=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207"
set "SDK=C:\Program Files (x86)\Windows Kits\10"
set "SDKVER=10.0.26100.0"
set "PATH=%MSVC%\bin\Hostx64\x64;%PATH%"
set "INCLUDE=%MSVC%\include;%SDK%\Include\%SDKVER%\ucrt;%SDK%\Include\%SDKVER%\um;%SDK%\Include\%SDKVER%\shared"
set "LIB=%MSVC%\lib\x64;%SDK%\Lib\%SDKVER%\ucrt\x64;%SDK%\Lib\%SDKVER%\um\x64"
cd /d "D:\projec_UniAgent Hub\desktop\src-tauri"
"%USERPROFILE%\.cargo\bin\cargo.exe" build --release
exit /b %ERRORLEVEL%
