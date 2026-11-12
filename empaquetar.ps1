# Genera un ZIP limpio de JarvisIA para entregas.
# Uso: powershell -ExecutionPolicy Bypass -File .\empaquetar.ps1
$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$destino = Join-Path $raiz "JarvisIA.zip"
$temporal = Join-Path ([System.IO.Path]::GetTempPath()) ("jarvis_" + [guid]::NewGuid().ToString("N"))
$paquete = Join-Path $temporal "JarvisIA"

$excluir = @(
    ".git", ".venv", "venv", "env",
    "__pycache__", "archivos.db", "archivos.db-shm", "archivos.db-wal",
    "inventario.json", "jarvis.log", "logs", "models", ".cache",
    ".env", ".vscode", ".idea", "JarvisIA.zip"
)

New-Item -ItemType Directory -Path $paquete -Force | Out-Null
try {
    Get-ChildItem -LiteralPath $raiz -Force | ForEach-Object {
        if ($excluir -notcontains $_.Name) {
            Copy-Item -LiteralPath $_.FullName -Destination $paquete -Recurse -Force
        }
    }
    Get-ChildItem -LiteralPath $paquete -Recurse -Force -Directory |
        Where-Object { $excluir -contains $_.Name } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $paquete -Recurse -Force -File |
        Where-Object { $excluir -contains $_.Name } |
        Remove-Item -Force -ErrorAction SilentlyContinue

    if (Test-Path -LiteralPath $destino) {
        Remove-Item -LiteralPath $destino -Force
    }
    Compress-Archive -Path $paquete -DestinationPath $destino -CompressionLevel Optimal
    Write-Output "ZIP creado: $destino"
} finally {
    Remove-Item -LiteralPath $temporal -Recurse -Force -ErrorAction SilentlyContinue
}
