@echo off
rem Altimetro no Windows: duplo clique. Na primeira vez prepara tudo (alguns minutos).
cd /d "%~dp0"
where py >nul 2>&1 && (py -3 iniciar.py %* & goto fim)
where python >nul 2>&1 && (python iniciar.py %* & goto fim)
echo Python nao encontrado. Instale o Python 3 em https://www.python.org (marque Add python.exe to PATH).
pause
:fim
if errorlevel 1 pause
