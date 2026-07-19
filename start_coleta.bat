@echo off
cd /d C:\Projetos\Pulso-eleitoral
C:\Projetos\Pulso-eleitoral\.venv\Scripts\python.exe coletar.py
echo Coleta finalizada em %date% %time% >> logs\coleta_bat.log
