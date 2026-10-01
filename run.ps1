$env:OLLAMA_MAX_LOADED_MODELS = "1"
Set-Location $PSScriptRoot
docker compose up -d

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = Join-Path $env:USERPROFILE ".local\academico-rag\venv\Scripts\python.exe"
}
if (-not (Test-Path $python)) {
    $python = "python"
}
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
