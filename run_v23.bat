@echo off
setlocal
set "PROJECT_DIR=%~dp0"
set "PYTHON_BIN=%PROJECT_DIR%.venv\Scripts\python.exe"
if "%~1"=="" (
  set "EVENT_PATH=%PROJECT_DIR%data\v23\events\valid_forecast_and_hydrology.json"
) else (
  set "EVENT_PATH=%~1"
)
if exist "%PYTHON_BIN%" (
  "%PYTHON_BIN%" "%PROJECT_DIR%agents\guidance_v23_workflow.py" --event "%EVENT_PATH%" --mode production
) else (
  py -3.11 "%PROJECT_DIR%agents\guidance_v23_workflow.py" --event "%EVENT_PATH%" --mode production
)
endlocal
