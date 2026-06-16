@echo off
cd /d C:\Meus_projetos\Pulso_Eleitoral
C:\Users\stife\AppData\Local\Programs\Python\Python312\python.exe coletar.py
echo Coleta finalizada em %date% %time% >> logs\coleta_bat.log
