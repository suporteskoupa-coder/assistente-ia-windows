# Instalador do Ultron para Windows.
# Rode na pasta do projeto:  powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "== Instalando o Ultron em $Root ==" -ForegroundColor Red

# 1. Python 3.12+
$py = $null
$candidates = @(
    @{ exe = "py"; args = @("-3") },
    @{ exe = "python"; args = @() }
)
foreach ($c in $candidates) {
    try {
        $v = & $c.exe $c.args -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$v -ge [version]"3.12") { $py = $c; break }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3.12 ou mais novo nao encontrado." -ForegroundColor Yellow
    Write-Host "Instale com:  winget install Python.Python.3.12   e rode este script de novo."
    exit 1
}
Write-Host "Python $v encontrado."

# 2. Ambiente virtual e dependencias
if (-not (Test-Path ".venv")) { & $py.exe $py.args -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -e .
if ($LASTEXITCODE -ne 0) { Write-Host "Falha ao instalar dependencias." -ForegroundColor Red; exit 1 }

# 3. Configuracao
$Home2 = Join-Path $env:USERPROFILE "Ultron"
$Cfg = Join-Path $Home2 "ultron.toml"
New-Item -ItemType Directory -Force -Path $Home2 | Out-Null
if (-not (Test-Path $Cfg)) {
    Copy-Item "ultron\ultron.example.toml" $Cfg
    Write-Host "Configuracao criada em $Cfg  (edite apps, modos e canais do Discord)."
} else {
    Write-Host "Configuracao existente mantida: $Cfg"
}

# 4. Dependencias externas (avisa, nao falha)
if (Get-Command claude -ErrorAction SilentlyContinue) {
    Write-Host "Claude Code: OK ($(claude --version))"
} else {
    Write-Host "Claude Code NAO encontrado. Instale (veja o README) e rode 'claude' uma vez para fazer login." -ForegroundColor Yellow
}
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "Ollama: OK. Baixe o modelo com:  ollama pull qwen3:8b"
} else {
    Write-Host "Ollama NAO encontrado (opcional, so para o modo local). Baixe em https://ollama.com" -ForegroundColor Yellow
}

# 5. Atalho na area de trabalho
$Desktop = [Environment]::GetFolderPath("Desktop")
$Shell = New-Object -ComObject WScript.Shell
$Lnk = $Shell.CreateShortcut((Join-Path $Desktop "Ultron.lnk"))
$Lnk.TargetPath = (Join-Path $Root ".venv\Scripts\pythonw.exe")
$Lnk.Arguments = "-m ultron"
$Lnk.WorkingDirectory = $Root
$Lnk.Description = "Ultron"
$Lnk.Save()
Write-Host "Atalho 'Ultron' criado na area de trabalho." -ForegroundColor Green
Write-Host "Para ver erros, rode no terminal:  .\.venv\Scripts\python.exe -m ultron"
