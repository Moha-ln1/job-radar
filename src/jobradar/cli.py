"""Punto de entrada de la línea de comandos."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
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
    _p("Copia el chat_id en TELEGRAM_CHAT_ID dentro de .env.")
    return 0


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
        app.run_polling()
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
    try:
        from jobradar.wizard import main as wizard_main
    except ImportError:
        _p("El asistente 'configurar' estará disponible en la fase 6.")
        return 1
    return wizard_main() or 0


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
    tsub.add_parser("chat-id", help="muestra tu chat_id (escribe /start a tu bot antes)")
    tsub.add_parser("test", help="envía un mensaje de prueba")
    add("run", cmd_run, "Arranca el bot y el programador")
    add("stop", cmd_stop, "Para jobradar")
    add("status", cmd_status, "Estado de jobradar")
    add("digest", cmd_digest, "Envía ahora el resumen de pendientes")
    add("configurar", cmd_configurar, "Asistente de instalación")
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
