#!/usr/bin/env bash
# Instalador de JobRadar para Linux/macOS. Es idempotente.
#   bash scripts/setup.sh [--non-interactive] [--skip-autostart]
set -u

INTERACTIVE=1
SKIP_AUTOSTART=0
for arg in "$@"; do
  case "$arg" in
    --non-interactive) INTERACTIVE=0 ;;
    --skip-autostart) SKIP_AUTOSTART=1 ;;
    -h|--help) echo "Uso: bash scripts/setup.sh [--non-interactive] [--skip-autostart]"; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

if [ -t 1 ]; then C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_OFF=$'\033[0m'
else C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_OFF=""; fi
STEP=0; TOTAL=8
step() { STEP=$((STEP + 1)); printf '\n%s[%d/%d] %s%s\n' "$C_CYAN" "$STEP" "$TOTAL" "$1" "$C_OFF"; }
ok()   { printf '    %sOK%s  %s\n' "$C_GREEN" "$C_OFF" "$1"; }
warn() { printf '    %s!!%s  %s\n' "$C_YELLOW" "$C_OFF" "$1"; }
fail() { printf '    %sERROR:%s %s\n' "$C_RED" "$C_OFF" "$1" >&2; exit 1; }
ask_yes_no() {  # $1 pregunta, $2 = 1 si el valor por defecto es sí
  local hint="s/N" a; [ "$2" = "1" ] && hint="S/n"
  read -r -p "    $1 [$hint] " a
  a="$(printf '%s' "$a" | tr '[:upper:]' '[:lower:]')"
  [ -z "$a" ] && { [ "$2" = "1" ]; return; }
  [ "$a" = "s" ] || [ "$a" = "si" ] || [ "$a" = "y" ] || [ "$a" = "yes" ]
}
has_value() { [ -f .env ] && grep -Eq "^[[:space:]]*$1[[:space:]]*=[[:space:]]*[^[:space:]]" .env; }

echo "JobRadar - instalación"

# 1) Python >= 3.10
step "Comprobando Python 3.10 o superior"
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || fail "No encuentro Python 3.10 o superior. Instálalo (https://www.python.org/downloads/ o con tu gestor de paquetes) y repite."
ok "Python encontrado: $($PY --version)"

# 2) venv e instalación
step "Preparando el entorno virtual (.venv) e instalando JobRadar"
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv || fail "No se pudo crear el entorno virtual (en Debian/Ubuntu: sudo apt install python3-venv)."
  ok "Entorno virtual creado."
else
  ok "El entorno virtual ya existía."
fi
.venv/bin/python -m pip install --disable-pip-version-check -q -e . || fail "Falló 'pip install -e .'."
JR="$ROOT/.venv/bin/jobradar"
[ -x "$JR" ] || fail "No se encontró $JR tras la instalación."
ok "JobRadar instalado."

# 3) Configuración
step "Creando los archivos de configuración si faltan"
for pair in "config.example.yaml:config.yaml" ".env.example:.env"; do
  src="${pair%%:*}"; dst="${pair##*:}"
  if [ -f "$dst" ]; then ok "$dst ya existe (no se toca)."
  elif [ -f "$src" ]; then cp "$src" "$dst"; ok "$dst creado a partir de $src."
  else warn "Falta $src."; fi
done
[ -f .env ] && chmod 600 .env

# 4) Telegram
step "Configurando Telegram"
if [ "$INTERACTIVE" = 0 ]; then
  warn "Modo no interactivo: se omite. Más tarde: jobradar env set TELEGRAM_BOT_TOKEN"
elif has_value TELEGRAM_BOT_TOKEN; then
  ok "Ya hay un token de Telegram guardado."
else
  echo "    1. En Telegram abre @BotFather y escribe /newbot."
  echo "    2. Elige un nombre y un usuario (debe acabar en 'bot')."
  echo "    3. BotFather te dará un token largo: cópialo, te lo pido ahora (no se verá al pegarlo)."
  if "$JR" env set TELEGRAM_BOT_TOKEN; then
    read -r -p "    Abre tu bot en Telegram, escríbele /start y pulsa Enter aquí " _
    if "$JR" telegram chat-id --save; then "$JR" telegram test
    else warn "No se pudo guardar el chat. Repite: jobradar telegram chat-id --save"; fi
  else
    warn "No se guardó el token. Repite más tarde: jobradar env set TELEGRAM_BOT_TOKEN"
  fi
fi

# 5) Claves opcionales
step "Claves opcionales de APIs (InfoJobs, Adzuna, Jooble)"
if [ "$INTERACTIVE" = 0 ]; then
  warn "Modo no interactivo: se omite (ver docs/APIS.md)."
elif ask_yes_no "¿Quieres añadirlas ahora? (ver docs/APIS.md)" 0; then
  for k in INFOJOBS_CLIENT_ID INFOJOBS_CLIENT_SECRET ADZUNA_APP_ID ADZUNA_APP_KEY JOOBLE_API_KEY; do
    if ask_yes_no "Poner $k" 0; then "$JR" env set "$k"; fi
  done
else
  ok "Sin claves: se usan las fuentes públicas."
fi

# 6) Búsquedas
step "Configurando tus búsquedas"
has_searches() { [ -f busquedas.yaml ] && grep -Eq '^[[:space:]]*-[[:space:]]*id:' busquedas.yaml; }
if has_searches; then ok "Ya tienes búsquedas guardadas."
elif [ "$INTERACTIVE" = 0 ]; then warn "Modo no interactivo: se omite. Más tarde: jobradar configurar (o /busquedas en Telegram)"
else "$JR" configurar; fi

# 7) Base de datos
step "Preparando la base de datos"
if [ -f jobradar.db ]; then
  "$JR" init-db >/dev/null; ok "La base de datos ya existía (no se repite la línea base)."
elif ! has_searches; then
  "$JR" init-db >/dev/null
  warn "Aún no hay búsquedas: tras crearlas ejecuta 'jobradar init-db --baseline' para no recibir avisos de ofertas antiguas."
else
  echo "    Primera vez: marco como vistas las ofertas actuales (puede tardar un minuto)..."
  "$JR" init-db --baseline || warn "La línea base no terminó bien; no es grave."
fi

# 8) Autoarranque
step "Arranque automático al iniciar sesión"
if [ "$SKIP_AUTOSTART" = 1 ] || [ "$INTERACTIVE" = 0 ]; then
  warn "Omitido. Para activarlo: jobradar autostart on. A mano: jobradar run"
elif ask_yes_no "¿Arrancar JobRadar automáticamente al iniciar sesión?" 1; then
  "$JR" autostart on
else
  echo "    Para arrancarlo a mano: jobradar run (o jobradar autostart on más adelante)."
fi

printf '\n%sInstalación terminada.%s\n' "$C_GREEN" "$C_OFF"
echo "Comandos útiles (activa el entorno con: source .venv/bin/activate):"
echo "  jobradar run          arranca el bot y los escaneos"
echo "  jobradar status       estado actual"
echo "  jobradar scan --dry-run   prueba un escaneo sin guardar ni avisar"
echo "  jobradar configurar   crear una búsqueda (o /busquedas en Telegram)"
echo "  jobradar ats detect <url> --add   añadir la web de empleo de una empresa"
echo "  jobradar autostart on|off|status"
