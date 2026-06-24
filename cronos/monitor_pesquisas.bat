@echo off
cd /d C:\Meus_projetos\Pulso_Eleitoral
C:\Users\stife\AppData\Local\Programs\Python\Python312\python.exe cronos\tasks\monitor_pesquisas.py
echo Monitor finalizado em %date% %time% >> logs\monitor_bat.log
