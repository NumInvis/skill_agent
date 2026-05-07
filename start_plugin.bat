@echo off
cd /d D:\ai\skill_agent
set PYTHONUNBUFFERED=1
python -m main > plugin.log 2>&1
