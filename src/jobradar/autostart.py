"""Arranque automático de `jobradar run` al iniciar sesión (Windows, Linux, macOS).

Windows: se usa un .vbs en la carpeta Inicio del usuario en vez de `schtasks /SC ONLOGON`.
Motivo: en Windows 11 crear tareas ONLOGON suele exigir administrador ("Acceso denegado"), la carpeta
Inicio no; además el .vbs permite fijar el directorio de trabajo y JOBRADAR_HOME y lanzar sin ventana."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .paths import Paths

WIN_NAME = "JobRadar.vbs"
SERVICE = "jobradar.service"
PLIST = "com.jobradar.plist"
LABEL = "com.jobradar"


def _platform() -> str:
    if sys.platform == "win32":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _target() -> Path:
    home = Path.home()
    return {"windows": _startup_dir() / WIN_NAME,
            "macos": home / "Library" / "LaunchAgents" / PLIST,
            "linux": home / ".config" / "systemd" / "user" / SERVICE}[_platform()]


def _python(windowless: bool = False) -> str:
    exe = Path(sys.executable)
    if windowless:
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
        return str(exe.with_name("pythonw.exe"))
    return str(exe)


def _vbs(paths: Paths) -> str:
    root, py = str(paths.root), _python(True)
    return ("' Generado por 'jobradar autostart on'. Arranca jobradar sin ventana al iniciar sesion.\r\n"
            'Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.CurrentDirectory = "{root}"\r\n'
            f'sh.Environment("PROCESS")("JOBRADAR_HOME") = "{root}"\r\n'
            f'sh.Run """{py}"" -m jobradar run", 0, False\r\n')


def _unit(paths: Paths) -> str:
    return ("[Unit]\nDescription=JobRadar\nAfter=network-online.target\n\n[Service]\n"
            f"WorkingDirectory={paths.root}\nEnvironment=JOBRADAR_HOME={paths.root}\n"
            f"ExecStart={_python()} -m jobradar run\nRestart=on-failure\nRestartSec=30\n\n"
            "[Install]\nWantedBy=default.target\n")


def _plist(paths: Paths) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            f'<plist version="1.0"><dict>\n<key>Label</key><string>{LABEL}</string>\n'
            f'<key>ProgramArguments</key><array><string>{_python()}</string><string>-m</string>'
            '<string>jobradar</string><string>run</string></array>\n'
            f'<key>WorkingDirectory</key><string>{paths.root}</string>\n'
            f'<key>EnvironmentVariables</key><dict><key>JOBRADAR_HOME</key><string>{paths.root}</string></dict>\n'
            '<key>RunAtLoad</key><true/>\n<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>\n'
            f'<key>StandardErrorPath</key><string>{paths.logs_dir / "launchd.log"}</string>\n'
            '</dict></plist>\n')


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False, capture_output=True)


def enable(paths: Paths, dry_run: bool = False) -> str:
    plat, target = _platform(), _target()
    content = {"windows": _vbs, "linux": _unit, "macos": _plist}[plat](paths)
    cmds = {"linux": [["systemctl", "--user", "daemon-reload"],
                      ["systemctl", "--user", "enable", "--now", SERVICE]],
            "macos": [["launchctl", "unload", str(target)], ["launchctl", "load", "-w", str(target)]],
            "windows": []}[plat]
    if dry_run:
        lines = [f"[simulación] Escribiría {target}:", content.rstrip()]
        lines += ["[simulación] Ejecutaría: " + " ".join(c) for c in cmds]
        return "\n".join(lines)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="")
    for c in cmds:
        _run(c)
    return f"Autoarranque activado ({target})."


def disable(paths: Paths, dry_run: bool = False) -> str:
    plat, target = _platform(), _target()
    cmds = {"linux": [["systemctl", "--user", "disable", "--now", SERVICE]],
            "macos": [["launchctl", "unload", str(target)]], "windows": []}[plat]
    if dry_run:
        lines = ["[simulación] Ejecutaría: " + " ".join(c) for c in cmds]
        return "\n".join(lines + [f"[simulación] Borraría {target}"])
    for c in cmds:
        _run(c)
    existed = target.exists()
    target.unlink(missing_ok=True)
    return "Autoarranque desactivado." if existed else "El autoarranque no estaba activado."


def is_enabled() -> bool:
    return _target().exists()
