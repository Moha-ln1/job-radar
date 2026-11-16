"""Punto de entrada de la línea de comandos."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from jobradar import __version__
from jobradar.config import ConfigError
from jobradar.paths import Paths


def _p(text: str = "") -> None:
    print(text)


def _creds_or_explain(paths: Paths, need_chat: bool = True):
    from jobradar import telegram_io
    token, chat = telegram_io.credentials(paths)
    if not token or (need_chat and not chat):
        _p("Error: " + telegram_io.MISSING_CREDENTIALS)
        return None
    return token, chat


def _store(paths: Paths):
    from jobradar.store import Store
    return Store(paths.db)


# --- scan ---
def _print_report(report, dry_run: bool) -> None:
    for name, res in report.source_status.items():
        _p(f"  {name:<16}" + (f"ERROR: {res.error}" if res.error else f"{len(res.offers)} ofertas"))
    _p(f"Ofertas nuevas: {len(report.new_jobs)} · encajan: {len(report.new_matched)} · "
       f"descartadas: {report.new_discarded}" + ("  (simulación: no se guarda nada)" if dry_run else ""))
    for job in report.new_matched:
        url = job.first_posting.url if job.first_posting else ""
        _p(f"  {'🔥' if job.priority == 'alta' else '📰'} {job.title} — {job.company or '?'}  {url}")
    for alert in report.health_alerts:
        _p(f"  ⚠ {alert}")


def cmd_scan(args, paths: Paths) -> int:
    from jobradar import radar, scheduler, telegram_io
    only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
    report = asyncio.run(radar.scan(paths, only=only, dry_run=args.dry_run))
    _print_report(report, args.dry_run)
    if not args.dry_run:
        scheduler.update_state(paths, last_scan=datetime.now(timezone.utc).isoformat())
        token, chat = telegram_io.credentials(paths)
        if token and chat:
            async def send():
                from telegram import Bot
                async with Bot(token) as bot:
                    return await scheduler.deliver(bot, int(chat), paths, report, datetime.now(timezone.utc))
            _p(f"Avisos enviados a Telegram: {asyncio.run(send())}")
        else:
            _p("Sin TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID: no se envían avisos (ver 'jobradar telegram chat-id').")
    statuses = list(report.source_status.values())
    return 1 if statuses and all(r.error for r in statuses) else 0


def cmd_init_db(args, paths: Paths) -> int:
    _store(paths).close()
    _p(f"Base de datos lista: {paths.db}")
    if args.baseline:
        from jobradar import radar
        report = asyncio.run(radar.init_baseline(paths))
        _print_report(report, False)
        _p("Línea base creada: lo encontrado queda registrado sin avisar.")
    return 0


def cmd_recent(args, paths: Paths) -> int:
    store = _store(paths)
    try:
        jobs = store.recent(args.days, datetime.now(timezone.utc), "avisada")
        for j in jobs:
            urls = ", ".join(p.url for p in store.postings(j.id))
            _p(f"{j.first_seen.astimezone():%d/%m %H:%M} {j.priority or '-':<6} {j.title} — "
               f"{j.company or '?'}  {urls}")
        _p(f"{len(jobs)} ofertas en los últimos {args.days} días.")
    finally:
        store.close()
    return 0


def cmd_descartadas(args, paths: Paths) -> int:
    from itertools import groupby
    store = _store(paths)
    try:
        jobs = sorted(store.discarded(args.hours, datetime.now(timezone.utc)),
                      key=lambda j: j.reasons[0] if j.reasons else "")
        for reason, group in groupby(jobs, key=lambda j: j.reasons[0] if j.reasons else "sin motivo"):
            group = list(group)
            _p(f"{reason} ({len(group)})")
            for j in group:
                _p(f"    {j.title} — {j.company or '?'}")
        _p(f"{len(jobs)} ofertas descartadas en las últimas {args.hours} h.")
    finally:
        store.close()
    return 0


def cmd_sources(args, paths: Paths) -> int:
    from jobradar.radar import load_context
    from jobradar.sources import all_fetchers
    settings = load_context(paths)[0]
    fetchers, store = all_fetchers(), _store(paths)
    try:
        _p(f"{'Fuente':<16}{'Activa':<8}{'Código':<8}Última ejecución")
        for name, opts in settings.sources.items():
            runs = store.last_runs(name, 1)
            last = (f"{datetime.fromisoformat(runs[0]['ts']).astimezone():%d/%m %H:%M} "
                    f"{'OK' if runs[0]['ok'] else 'FALLO'} ({runs[0]['count']} ofertas)") if runs else "nunca"
            _p(f"{name:<16}{'sí' if opts.get('enabled', True) else 'no':<8}"
               f"{'sí' if name in fetchers else 'no':<8}{last}")
    finally:
        store.close()
    return 0


def cmd_verificar(args, paths: Paths) -> int:
    from jobradar import verify
    rows = asyncio.run(verify.verify(paths, args.sample))
    _p(verify.format_table(rows))
    return 0 if all(r.ok for r in rows) else 1


def cmd_filtros(args, paths: Paths) -> int:
    from jobradar import radar
    if args.accion == "probar":
        decision = radar.probe(paths, args.texto)
        if decision is None:
            _p("Error: el texto no es un título válido (3 a 200 caracteres, sin HTML).")
            return 2
        _p(("✅ Encaja" if decision.ok else "❌ No encaja") + f" (prioridad: {decision.priority or '-'})")
        for r in decision.reasons:
            _p(f"  - {r}")
        return 0
    _settings, searches, excl, syn, catalog = radar.load_context(paths)
    if not searches:
        _p("No hay búsquedas. Créalas con /busquedas en Telegram o con 'jobradar configurar'.")
    for s in searches:
        _p(f"{'[pausada] ' if s.paused else ''}{s.name} (id {s.id}, avisos: {s.prioridad})")
        for label, keys in (("Tipo", s.tipos), ("Área", s.areas)):
            for k in keys:
                _p(f"    {label} {k}: " + ", ".join(syn.expand(k)))
        _p(f"    Modalidad: {', '.join(s.modalidades) or 'cualquiera'}")
        _p(f"    Ubicación: {', '.join(s.ubicaciones) or 'cualquiera'}")
    _p(f"Palabras excluidas (solo en el título): {', '.join(excl.words) or 'ninguna'}")
    _p(f"Empresas excluidas: {', '.join(excl.companies) or 'ninguna'}")
    _p("Ante la duda, la oferta se incluye; lo descartado se puede revisar con 'jobradar descartadas'.")
    return 0


# --- telegram ---
def cmd_telegram(args, paths: Paths) -> int:
    from telegram import Bot
    if args.accion == "link":
        return _telegram_link(args, paths)
    creds = _creds_or_explain(paths, need_chat=args.accion == "test")
    if creds is None:
        return 2
    token, chat = creds
    if args.accion == "test":
        from jobradar import telegram_io

        async def send():
            async with Bot(token) as bot:
                await telegram_io.send_text(bot, int(chat), "✅ jobradar está conectado.")
        asyncio.run(send())
        _p("Mensaje de prueba enviado.")
        return 0

    async def updates():
        async with Bot(token) as bot:
            return await bot.get_updates(timeout=0)
    found: dict[int, str] = {}
    for u in asyncio.run(updates()):
        m = u.effective_message
        if m and m.text and m.text.startswith("/start") and u.effective_chat:
            c = u.effective_chat
            found[c.id] = " ".join(filter(None, [c.first_name, c.last_name])) or c.title or c.username or "?"
    if not found:
        _p("No hay mensajes /start. Abre tu bot en Telegram, escríbele /start y vuelve a ejecutar este comando.")
        return 1
    for cid, name in found.items():
        _p(f"chat_id: {cid}  ({name})")
    if not args.save:
        _p("Copia el chat_id en TELEGRAM_CHAT_ID dentro de .env (o ejecuta con --save).")
        return 0
    chosen = next(iter(found))
    if len(found) > 1:
        if not sys.stdin.isatty():
            _p("Hay varios chats: ejecútalo en una terminal para elegir, o copia el chat_id a mano.")
            return 1
        import questionary
        chosen = questionary.select("¿Cuál es tu chat?", choices=[
            questionary.Choice(f"{name} ({cid})", value=cid) for cid, name in found.items()]).ask()
        if chosen is None:
            return 130
    _env_set(paths, "TELEGRAM_CHAT_ID", str(chosen))
    _p(f"TELEGRAM_CHAT_ID guardado en {paths.env.name}.")
    return 0


def _restart_background(paths: Paths) -> bool:
    """Lanza `jobradar run` desacoplado de la terminal. Devuelve False si no se pudo."""
    from jobradar import autostart
    env = dict(os.environ, JOBRADAR_HOME=str(paths.root))
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
        exe = autostart._python(True)
        if not os.path.exists(exe):
            exe = autostart._python()
    else:
        kwargs["start_new_session"] = True
        exe = sys.executable
    try:
        subprocess.Popen([exe, "-m", "jobradar", "run"], cwd=str(paths.root), env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    except OSError:
        return False
    return True


def _telegram_link(args, paths: Paths) -> int:
    from telegram import Bot
    from jobradar import telegram_io, telegram_link
    token, _ = telegram_io.credentials(paths)
    if not token:
        _p("Error: falta TELEGRAM_BOT_TOKEN. Guárdalo con 'jobradar env set TELEGRAM_BOT_TOKEN'.")
        return 2
    was_running = _running_pid(paths) is not None
    if was_running:
        _p("Paro JobRadar un momento para vincular…")
        cmd_stop(args, paths)

    async def link():
        async with Bot(token) as bot:
            me = await bot.get_me()
            code = telegram_link.new_code()
            url = telegram_link.deep_link(me.username, code)
            _p(telegram_link.qr_text(url))
            _p(url)
            _p()
            _p("Escanéalo con el móvil (o abre el enlace) y pulsa INICIAR en Telegram. "
               f"Esperando… (máx. {max(1, round(args.timeout / 60))} min, Ctrl+C para cancelar)")
            res = await telegram_link.wait_for_start(bot, code, timeout=args.timeout)
            if res is not None:
                _env_set(paths, "TELEGRAM_CHAT_ID", str(res[0]))
                await telegram_io.send_text(
                    bot, res[0], "✅ JobRadar conectado. Crea tu primera búsqueda con /busquedas")
            return res

    try:
        try:
            res = asyncio.run(link())
        except KeyboardInterrupt:
            _p("Cancelado.")
            return 130
        except telegram_link.LinkConflict as exc:
            _p(f"Error: {exc}")
            return 1
        if res is None:
            _p("Se agotó el tiempo sin recibir el /start. Alternativa: abre tu bot, escríbele /start y ejecuta "
               "'jobradar telegram chat-id --save'.")
            return 1
        _p(f"Conectado con {res[1]}.")
        return 0
    finally:
        if was_running and not _restart_background(paths):
            _p("No pude volver a arrancar JobRadar: arráncalo con 'jobradar run'.")


# --- ejecución continua ---
def _setup_logging(paths: Paths) -> None:
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [RotatingFileHandler(
        paths.logs_dir / "jobradar.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:  # pythonw no tiene consola
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "apscheduler"):  # httpx escribe el token en las URL
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _running_pid(paths: Paths) -> int | None:
    from jobradar import scheduler
    pid = scheduler.read_state(paths).get("pid")
    return pid if isinstance(pid, int) and _pid_alive(pid) else None


def cmd_run(args, paths: Paths) -> int:
    from jobradar import bot, scheduler
    if _creds_or_explain(paths) is None:
        return 2
    if (pid := _running_pid(paths)) and pid != os.getpid():
        _p(f"Ya hay un jobradar en marcha (pid {pid}). Usa 'jobradar stop' para pararlo.")
        return 1
    _setup_logging(paths)
    app = bot.build_application(paths)
    scheduler.register_jobs(app, paths)
    scheduler.update_state(paths, pid=os.getpid())
    _p("jobradar en marcha (Ctrl+C para parar).")
    try:
        # Telegram recuerda el último allowed_updates: pedirlo explícito para recibir los botones
        from telegram import Update
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        scheduler.update_state(paths, pid=None)
    return 0


def cmd_stop(args, paths: Paths) -> int:
    from jobradar import scheduler
    pid = _running_pid(paths)
    if pid is None:
        scheduler.update_state(paths, pid=None)
        _p("jobradar no está en marcha.")
        return 0
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        os.kill(pid, signal.SIGTERM)
    scheduler.update_state(paths, pid=None)
    _p(f"jobradar parado (pid {pid}).")
    return 0


def cmd_status(args, paths: Paths) -> int:
    from jobradar import scheduler
    now = datetime.now(timezone.utc)
    pid = _running_pid(paths)
    _p("Estado: " + (f"en marcha (pid {pid})" if pid else "parado"))
    last = scheduler.last_scan(paths)
    _p("Último escaneo: " + (f"{last.astimezone():%d/%m/%Y %H:%M}" if last else "nunca"))
    if (nxt := scheduler.next_scan(paths)):
        _p(f"Próximo escaneo: {nxt.astimezone():%d/%m/%Y %H:%M}")
    if (until := scheduler.silenced_until(paths, now)):
        _p(f"Silenciado hasta: {until.astimezone():%d/%m/%Y %H:%M}")
    if paths.db.exists():
        store = _store(paths)
        try:
            _p(f"Pendientes para el resumen: {len(store.pending_digest())}")
        finally:
            store.close()
    return 0


def cmd_digest(args, paths: Paths) -> int:
    from jobradar import scheduler
    creds = _creds_or_explain(paths)
    if creds is None:
        return 2
    token, chat = creds

    async def send():
        from telegram import Bot
        async with Bot(token) as bot:
            return await scheduler.send_digest(bot, int(chat), paths, force=True)
    n = asyncio.run(send())
    _p(f"Resumen enviado con {n} ofertas." if n else "No hay ofertas pendientes.")
    return 0


def cmd_configurar(args, paths: Paths) -> int:
    from jobradar.wizard import main as wizard_main
    return wizard_main(paths) or 0


# --- .env ---
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _ensure_env(paths: Paths) -> None:
    if paths.env.exists():
        return
    example = paths.root / ".env.example"
    paths.env.write_text(example.read_text(encoding="utf-8") if example.exists() else "", encoding="utf-8")


def _env_set(paths: Paths, key: str, value: str) -> None:
    """Escribe KEY=value en .env sustituyendo la línea existente (sin tocar el resto)."""
    _ensure_env(paths)
    lines = paths.env.read_text(encoding="utf-8").splitlines()
    new = f"{key}={value}"
    for i, line in enumerate(lines):
        if re.match(rf"\s*{re.escape(key)}\s*=", line):
            lines[i] = new
            break
    else:
        lines.append(new)
    paths.env.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_env(args, paths: Paths) -> int:
    if not _ENV_KEY.fullmatch(args.key):
        _p("Error: nombre de variable no válido.")
        return 2
    key = args.key.upper()
    value = getpass.getpass(f"Valor de {key} (no se muestra): ").strip()
    if not value:
        _p("Valor vacío: no se ha guardado nada.")
        return 1
    _env_set(paths, key, value)
    _p(f"{key} guardado en {paths.env.name}.")
    return 0


# --- autoarranque ---
def cmd_autostart(args, paths: Paths) -> int:
    from jobradar import autostart
    if args.accion == "on":
        _p(autostart.enable(paths, args.dry_run))
    elif args.accion == "off":
        _p(autostart.disable(paths, args.dry_run))
    else:
        _p("Autoarranque: " + ("activado" if autostart.is_enabled() else "desactivado"))
    return 0


# --- ATS ---
def _add_company(config_path, entry: dict) -> bool:
    """Añade una línea a `companies:` conservando el resto del archivo; False si ya estaba."""
    def q(v: str) -> str:
        return v if re.fullmatch(r"[\w .-]+", v) else json.dumps(v, ensure_ascii=False)
    text = config_path.read_text(encoding="utf-8")
    if re.search(rf"ats:\s*{re.escape(entry['ats'])}\s*,\s*slug:\s*[\"']?{re.escape(entry['slug'])}[\"']?\s*}}", text):
        return False
    line = f"  - {{name: {q(entry['name'])}, ats: {entry['ats']}, slug: {q(entry['slug'])}}}"
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r"companies\s*:", l)), None)
    if start is None:
        lines += ["", "companies:", line]
    else:
        last = start
        for i in range(start + 1, len(lines)):
            if re.match(r"\s+-\s", lines[i]):
                last = i
            elif lines[i].strip() and not lines[i].lstrip().startswith("#") and not lines[i].startswith(" "):
                break
        lines.insert(last + 1, line)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def cmd_ats(args, paths: Paths) -> int:
    from jobradar.ats_detect import detect_url
    from jobradar.http import Http

    async def run():
        async with Http() as http:
            return await detect_url(http, args.url)
    try:
        found = asyncio.run(run())
    except Exception as exc:  # red caída, 404...
        _p(f"Error al descargar la página: {exc}")
        return 1
    if not found:
        _p("No se reconoce el ATS de esa web. Soportados: Greenhouse, Lever, Ashby, SmartRecruiters, "
           "Workday, Recruitee, Personio y Teamtailor.")
        return 1
    _p(f"Detectado: {found['name']} · {found['ats']} · {found['slug']}")
    if args.add:
        if not paths.config.exists():
            _p("Error: no existe config.yaml (cópialo de config.example.yaml).")
            return 2
        import yaml

        from .config import bot_settings_path, load_settings, save_bot_settings
        over = bot_settings_path(paths.config)
        if over.exists() and "companies" in (yaml.safe_load(over.read_text(encoding="utf-8")) or {}):
            # La lista ya se gestiona desde el bot (/empresas): se añade ahí para que no quede oculta
            current = load_settings(paths.config).companies
            if any(c.get("ats") == found["ats"] and c.get("slug") == found["slug"] for c in current):
                _p("Esa empresa ya estaba en la lista.")
            else:
                save_bot_settings(paths.config, companies=[*current, found])
                _p("Añadida a la lista de empresas (la misma que ves en /empresas).")
        else:
            _p("Añadida a config.yaml (companies)." if _add_company(paths.config, found)
               else "Esa empresa ya estaba en config.yaml.")
    else:
        _p("Añádela con --add o pegando en config.yaml: "
           f"- {{name: {found['name']}, ats: {found['ats']}, slug: {found['slug']}}}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobradar", description="Radar de convocatorias cortas")
    parser.add_argument("--version", action="version", version=f"jobradar {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="comando")

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_, description=help_)
        p.set_defaults(fn=fn)
        return p

    p = add("scan", cmd_scan, "Escanea las fuentes ahora y envía los avisos")
    p.add_argument("--dry-run", action="store_true", help="no guarda nada ni envía avisos")
    p.add_argument("--only", help="solo estas fuentes (separadas por comas)")
    p = add("init-db", cmd_init_db, "Crea la base de datos")
    p.add_argument("--baseline", action="store_true", help="además, registra lo existente sin avisar")
    p = add("recent", cmd_recent, "Ofertas que encajan encontradas últimamente")
    p.add_argument("--days", type=int, default=7)
    p = add("descartadas", cmd_descartadas, "Ofertas descartadas, agrupadas por motivo")
    p.add_argument("--hours", type=int, default=24)
    add("sources", cmd_sources, "Fuentes configuradas y su última ejecución")
    p = add("verificar", cmd_verificar, "Compara datos extraídos con las páginas reales")
    p.add_argument("--sample", type=int, default=3, help="ofertas a comprobar por fuente")
    p = add("filtros", cmd_filtros, "Explica o prueba los filtros")
    fsub = p.add_subparsers(dest="accion", required=True, metavar="acción")
    fsub.add_parser("explicar", help="describe las búsquedas activas")
    probar = fsub.add_parser("probar", help="evalúa un título")
    probar.add_argument("texto")
    p = add("telegram", cmd_telegram, "Utilidades de Telegram")
    tsub = p.add_subparsers(dest="accion", required=True, metavar="acción")
    cid = tsub.add_parser("chat-id", help="muestra tu chat_id (escribe /start a tu bot antes)")
    cid.add_argument("--save", action="store_true", help="guarda el chat_id en .env")
    tsub.add_parser("test", help="envía un mensaje de prueba")
    lnk = tsub.add_parser("link", help="vincula tu chat escaneando un QR")
    lnk.add_argument("--timeout", type=int, default=300, help="segundos de espera (por defecto 300)")
    add("run", cmd_run, "Arranca el bot y el programador")
    add("stop", cmd_stop, "Para jobradar")
    add("status", cmd_status, "Estado de jobradar")
    add("digest", cmd_digest, "Envía ahora el resumen de pendientes")
    add("configurar", cmd_configurar, "Asistente de instalación")
    p = add("env", cmd_env, "Guarda un secreto en .env")
    esub = p.add_subparsers(dest="accion", required=True, metavar="acción")
    eset = esub.add_parser("set", help="pide el valor (oculto) y lo guarda")
    eset.add_argument("key")
    p = add("autostart", cmd_autostart, "Arranque automático al iniciar sesión")
    p.add_argument("accion", choices=["on", "off", "status"])
    p.add_argument("--dry-run", action="store_true", help="solo muestra lo que haría")
    p = add("ats", cmd_ats, "Detecta el ATS de la web de empleo de una empresa")
    asub = p.add_subparsers(dest="accion", required=True, metavar="acción")
    det = asub.add_parser("detect", help="detecta el ATS de una URL")
    det.add_argument("url")
    det.add_argument("--add", action="store_true", help="añade la empresa a config.yaml")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help()
        return 0
    try:
        return args.fn(args, Paths.default()) or 0
    except ConfigError as exc:
        _p(f"Error: {exc}")
        return 2
    except KeyboardInterrupt:
        return 130
