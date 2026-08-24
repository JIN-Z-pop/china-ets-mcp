@echo off
@REM [RETIRED 2026-08-24 R-002] superseded by the unified morning pipeline (see repo history)
cd /d C:\Users\jin_z\Desktop\china-ets-mcp
python -m china_ets_mcp.scheduler.auto_fetch >> data\fetch_log.txt 2>&1
