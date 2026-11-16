# Instalador de JobRadar para Windows (PowerShell 5.1+). Es idempotente: puedes repetirlo sin miedo.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-NonInteractive] [-SkipAutostart]
[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [switch]$SkipAutostart
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Interactive = -not $NonInteractive
$script:Step = 0
$Total = 8

function Say([string]$Text, [string]$Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }
function Step([string]$Text) { $script:Step++; Say ""; Say ("[{0}/{1}] {2}" -f $script:Step, $Total, $Text) 'Cyan' }
function Ok([string]$Text) { Say "    OK  $Text" 'Green' }
function Warn([string]$Text) { Say "    !!  $Text" 'Yellow' }
function Fail([string]$Text) { Say "    ERROR: $Text" 'Red'; exit 1 }
function AskYesNo([string]$Question, [bool]$DefaultYes) {
    $hint = if ($DefaultYes) { 'S/n' } else { 's/N' }
    $a = (Read-Host "    $Question [$hint]").Trim().ToLower()
    if ($a -eq '') { return $DefaultYes }
    return ($a -eq 's' -or $a -eq 'si' -or $a -eq 'y' -or $a -eq 'yes')
}

Say "JobRadar - instalación" 'White'

# 1) Python >= 3.10
Step "Comprobando Python 3.10 o superior"
$PyCmd = $null
$candidates = @(@('py', '-3'), @('python'))
foreach ($c in $candidates) {
    if (-not (Get-Command $c[0] -ErrorAction SilentlyContinue)) { continue }
    $extra = @(); if ($c.Count -gt 1) { $extra = $c[1..($c.Count - 1)] }
    $out = & $c[0] @extra -c "import sys; print(int(sys.version_info >= (3, 10)))" 2>$null
    if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq '1') { $PyCmd = $c; break }
}
if (-not $PyCmd) {
    Fail "No encuentro Python 3.10 o superior. Instálalo desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH') y vuelve a ejecutar este script."
}
$PyExtra = @(); if ($PyCmd.Count -gt 1) { $PyExtra = $PyCmd[1..($PyCmd.Count - 1)] }
Ok ("Python encontrado: " + ((& $PyCmd[0] @PyExtra --version) -join ' '))

# 2) Entorno virtual e instalación
Step "Preparando el entorno virtual (.venv) e instalando JobRadar"
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    & $PyCmd[0] @PyExtra -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPy)) { Fail "No se pudo crear el entorno virtual." }
    Ok "Entorno virtual creado."
} else {
    Ok "El entorno virtual ya existía."
}
& $VenvPy -m pip install --disable-pip-version-check -q -e $Root
if ($LASTEXITCODE -ne 0) { Fail "Falló 'pip install -e .'. Revisa la conexión a Internet y vuelve a intentarlo." }
$JR = Join-Path $Root '.venv\Scripts\jobradar.exe'
if (-not (Test-Path $JR)) { Fail "No se encontró $JR tras la instalación." }
Ok "JobRadar instalado."

# 3) Archivos de configuración
Step "Creando los archivos de configuración si faltan"
foreach ($pair in @(@('config.example.yaml', 'config.yaml'), @('.env.example', '.env'))) {
    $src = Join-Path $Root $pair[0]; $dst = Join-Path $Root $pair[1]
    if (Test-Path $dst) { Ok "$($pair[1]) ya existe (no se toca)." }
    elseif (Test-Path $src) { Copy-Item $src $dst; Ok "$($pair[1]) creado a partir de $($pair[0])." }
    else { Warn "Falta $($pair[0])." }
}

function HasValue([string]$Key) {
    $envFile = Join-Path $Root '.env'
    if (-not (Test-Path $envFile)) { return $false }
    return [bool](Select-String -Path $envFile -Pattern ("^\s*" + $Key + "\s*=\s*\S") -Quiet)
}

# 4) Telegram
Step "Configurando Telegram"
if (-not $Interactive) {
    Warn "Modo no interactivo: se omite. Más tarde: jobradar env set TELEGRAM_BOT_TOKEN"
} elseif (HasValue 'TELEGRAM_BOT_TOKEN') {
    Ok "Ya hay un token de Telegram guardado."
} else {
    Say "    1. En Telegram abre @BotFather y escribe /newbot."
    Say "    2. Elige un nombre y un usuario (debe acabar en 'bot')."
    Say "    3. BotFather te dará un token largo: cópialo, te lo pido ahora (no se verá al pegarlo)."
    & $JR env set TELEGRAM_BOT_TOKEN
    if ($LASTEXITCODE -eq 0) {
        Say "    Ahora vincula tu Telegram: escanea el QR con el móvil y pulsa INICIAR."
        & $JR telegram link
        if ($LASTEXITCODE -ne 0) {
            Warn "No se pudo vincular por QR."
            if (AskYesNo "¿Probar el método manual (escribir /start a tu bot)?" $true) {
                Read-Host "    Abre tu bot en Telegram, escríbele /start y pulsa Enter aquí" | Out-Null
                & $JR telegram chat-id --save
                if ($LASTEXITCODE -eq 0) { & $JR telegram test } else { Warn "No se pudo guardar el chat. Repite: jobradar telegram link" }
            } else {
                Warn "Repite más tarde: jobradar telegram link"
            }
        }
    } else {
        Warn "No se guardó el token. Repite más tarde: jobradar env set TELEGRAM_BOT_TOKEN"
    }
}

# 5) Claves opcionales
Step "Claves opcionales de APIs (InfoJobs, Adzuna, Jooble)"
if (-not $Interactive) {
    Warn "Modo no interactivo: se omite (ver docs\APIS.md)."
} elseif (AskYesNo "¿Quieres añadirlas ahora? (ver docs\APIS.md)" $false) {
    foreach ($k in @('INFOJOBS_CLIENT_ID', 'INFOJOBS_CLIENT_SECRET', 'ADZUNA_APP_ID', 'ADZUNA_APP_KEY', 'JOOBLE_API_KEY')) {
        if (AskYesNo "Poner $k" $false) { & $JR env set $k }
    }
} else {
    Ok "Sin claves: se usan las fuentes públicas."
}

# 6) Búsquedas
Step "Configurando tus búsquedas"
$SearchFile = Join-Path $Root 'busquedas.yaml'
$HasSearches = (Test-Path $SearchFile) -and (Select-String -Path $SearchFile -Pattern '^\s*-\s*id:' -Quiet)
if ($HasSearches) {
    Ok "Ya tienes búsquedas guardadas."
} elseif (-not $Interactive) {
    Warn "Modo no interactivo: se omite. Más tarde: jobradar configurar (o /busquedas en Telegram)"
} else {
    & $JR configurar
    $HasSearches = (Test-Path $SearchFile) -and (Select-String -Path $SearchFile -Pattern '^\s*-\s*id:' -Quiet)
}

# 7) Base de datos y línea base
Step "Preparando la base de datos"
$Db = Join-Path $Root 'jobradar.db'
if (Test-Path $Db) {
    & $JR init-db | Out-Null
    Ok "La base de datos ya existía (no se repite la línea base)."
} elseif (-not $HasSearches) {
    & $JR init-db | Out-Null
    Warn "Aún no hay búsquedas: tras crearlas ejecuta 'jobradar init-db --baseline' para no recibir avisos de ofertas antiguas."
} else {
    Say "    Primera vez: marco como vistas las ofertas actuales (puede tardar un minuto)..."
    & $JR init-db --baseline
    if ($LASTEXITCODE -ne 0) { Warn "La línea base no terminó bien; no es grave." }
}

# 8) Autoarranque
Step "Arranque automático al iniciar sesión"
if ($SkipAutostart -or -not $Interactive) {
    Warn "Omitido. Para activarlo: jobradar autostart on. A mano: jobradar run"
} elseif (AskYesNo "¿Arrancar JobRadar automáticamente al iniciar sesión?" $true) {
    & $JR autostart on
} else {
    Say "    Para arrancarlo a mano: jobradar run (o jobradar autostart on más adelante)."
}

Say ""
Say "Instalación terminada." 'Green'
Say "Comandos útiles (desde $Root, con .venv\Scripts\jobradar.exe o activando el entorno):"
Say "  jobradar run          arranca el bot y los escaneos"
Say "  jobradar status       estado actual"
Say "  jobradar scan --dry-run   prueba un escaneo sin guardar ni avisar"
Say "  jobradar configurar   crear una búsqueda (o /busquedas en Telegram)"
Say "  jobradar ats detect <url> --add   añadir la web de empleo de una empresa"
Say "  jobradar autostart on|off|status"
exit 0
