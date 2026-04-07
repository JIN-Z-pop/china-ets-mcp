@echo off
cd /d C:\Users\jin_z\Desktop\china-ets-mcp
python -m china_ets_mcp.scheduler.auto_fetch >> data\fetch_log.txt 2>&1
