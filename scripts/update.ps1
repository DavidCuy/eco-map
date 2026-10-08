<#
.SYNOPSIS
    Actualiza una instalacion nativa de Eco-Map en Windows y la relanza.

.DESCRIPTION
    Para el equipo de pruebas: no hay contenedores ni servicios, los dos procesos
    corren en ventanas de consola. El script los baja, trae el codigo nuevo,
    sincroniza dependencias y los vuelve a levantar.

    Dos formas de traer el codigo, elegidas solas: si la carpeta es un clon de
    git se hace `git pull`, que solo baja lo que cambio; si no, se descarga el
    zip de la rama. El zip evita tener que instalar git en el equipo, a cambio
    de bajar el repo entero cada vez.

    El `.env`, la carpeta `data` y el `.venv` no estan en el repo, asi que
    sobreviven a la actualizacion. Lo demas se sobreescribe: si editaste un
    shader directamente en este equipo, se pierde. El equipo de pruebas es un
    espejo del repositorio, no un lugar donde trabajar.

.EXAMPLE
    .\scripts\update.ps1

.EXAMPLE
    .\scripts\update.ps1 -Branch feat/hito-5 -NoRestart
#>
[CmdletBinding()]
param(
    [string]$Repo = "DavidCuy/eco-map",
    [string]$Branch = "main",
    # Por defecto, la carpeta que contiene a scripts\: este archivo vive dentro
    # de la instalacion que actualiza.
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Paso { param([string]$Texto) Write-Host "==> $Texto" -ForegroundColor Cyan }
function Write-Nota { param([string]$Texto) Write-Host "    $Texto" -ForegroundColor DarkGray }

$procesos = @("ecomap-render", "ecomap-web")

# ------------------------------------------------------------------ parar ---
function Stop-Ecomap {
    $corriendo = @()
    foreach ($nombre in $procesos) {
        $p = Get-Process -Name $nombre -ErrorAction SilentlyContinue
        if ($p) {
            $corriendo += $nombre
            Write-Nota "deteniendo $nombre (pid $($p.Id -join ', '))"
            $p | Stop-Process -Force
        }
    }
    if (@($corriendo).Count -gt 0) {
        Write-Paso "Procesos detenidos"
        # Windows no suelta los archivos del venv al instante y uv sync falla
        # con "access denied" si se le adelanta.
        Start-Sleep -Seconds 2
    }
    return $corriendo
}

# ----------------------------------------------------------------- codigo ---
function Get-Sha {
    param([string]$Repo, [string]$Branch)
    try {
        $commit = Invoke-RestMethod -Headers @{ "User-Agent" = "ecomap-update" } `
            -Uri "https://api.github.com/repos/$Repo/commits/$Branch"
        return @{
            Sha     = $commit.sha.Substring(0, 7)
            Mensaje = ($commit.commit.message -split "`n")[0]
            Fecha   = $commit.commit.author.date
        }
    } catch {
        # Sin internet o repositorio privado: no es motivo para no actualizar
        # si se usa git, solo para no poder anunciar que trae.
        return $null
    }
}

function Update-Codigo {
    param([string]$Root, [string]$Repo, [string]$Branch)

    $esClon = (Test-Path (Join-Path $Root ".git")) -and (Get-Command git -ErrorAction SilentlyContinue)
    if ($esClon) {
        Write-Paso "Actualizando por git ($Branch)"
        Push-Location $Root
        try {
            & git fetch origin $Branch
            if ($LASTEXITCODE -ne 0) { throw "git fetch fallo" }
            & git checkout $Branch
            & git reset --hard "origin/$Branch"
            if ($LASTEXITCODE -ne 0) { throw "git reset fallo" }
        } finally {
            Pop-Location
        }
        return
    }

    Write-Paso "Descargando el zip de $Branch"
    $zip = Join-Path $env:TEMP "ecomap-update.zip"
    $tmp = Join-Path $env:TEMP ("ecomap-update-" + [guid]::NewGuid().ToString("N"))
    $url = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $tmp -Force

    # GitHub nombra la carpeta con la rama y cambia las barras por guiones, asi
    # que no se puede construir el nombre: se busca.
    $extraido = Get-ChildItem $tmp -Directory | Select-Object -First 1
    if (-not $extraido) { throw "el zip no trajo ninguna carpeta" }

    Write-Paso "Copiando sobre $Root"
    Copy-Item (Join-Path $extraido.FullName "*") $Root -Recurse -Force
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
}

# --------------------------------------------------------------- arrancar ---
function Start-Ecomap {
    param([string]$Root)

    Write-Paso "Arrancando"
    # Cada uno en su ventana: son procesos de primer plano con log en consola, y
    # el render ademas abre la ventana OpenGL. WorkingDirectory importa porque el
    # .env se lee del directorio actual.
    foreach ($comando in @("ecomap-render", "ecomap-web")) {
        Start-Process -FilePath "uv" -ArgumentList "run", $comando -WorkingDirectory $Root
        Write-Nota "$comando lanzado"
        # El web es cliente del bus; darle al render un momento para escuchar
        # evita un reintento de conexion en el arranque.
        if ($comando -eq "ecomap-render") { Start-Sleep -Seconds 3 }
    }
}

# ------------------------------------------------------------------- main ---
Write-Host ""
Write-Host "Eco-Map - actualizacion ($Branch)" -ForegroundColor Green
Write-Host ""

if (-not (Test-Path (Join-Path $Root "pyproject.toml"))) {
    throw "No parece una instalacion de Eco-Map: $Root"
}

$commit = Get-Sha -Repo $Repo -Branch $Branch
if ($commit) { Write-Nota "$($commit.Sha)  $($commit.Mensaje)" }

$corrian = Stop-Ecomap
Update-Codigo -Root $Root -Repo $Repo -Branch $Branch

Write-Paso "Sincronizando dependencias"
Push-Location $Root
try {
    # --python 3.12 fijo: con 3.14 no hay wheel de glcontext y uv intenta
    # compilarlo, que pide Visual C++ Build Tools.
    & uv sync --python 3.12 --extra web --extra render --extra window --extra vision
    if ($LASTEXITCODE -ne 0) { throw "uv sync fallo con codigo $LASTEXITCODE" }
} finally {
    Pop-Location
}

if ($commit) {
    Set-Content -Path (Join-Path $Root "VERSION.txt") -Encoding UTF8 `
        -Value "$($commit.Sha) $($commit.Fecha) $($commit.Mensaje)"
}

if (@($corrian).Count -gt 0) {
    Start-Ecomap -Root $Root
} else {
    Write-Nota "no habia nada corriendo, no se arranca nada"
    Write-Nota "para levantarlo: uv run ecomap-render  y  uv run ecomap-web"
}

Write-Host ""
Write-Host "Listo." -ForegroundColor Green
if ($commit) { Write-Host "  corriendo $($commit.Sha) - $($commit.Mensaje)" }
Write-Host ""
