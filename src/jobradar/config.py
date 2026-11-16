"""Carga y guardado de configuración: config.yaml, .env, busquedas.yaml y sinónimos del usuario."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .models import Exclusions, Search
from .normalize import fold


class ConfigError(ValueError):
    """Error de configuración con mensaje en español."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScanSettings(_Strict):
    every_hours: float = 2
    digest_time: str = "09:00"
    max_age_days: int = 14


class HttpSettings(_Strict):
    delay_seconds: list[float] = [1, 3]
    timeout_seconds: float = 20

    @field_validator("delay_seconds")
    @classmethod
    def _pair(cls, v: list[float]) -> list[float]:
        if len(v) != 2 or v[0] > v[1] or v[0] < 0:
            raise ValueError("debe ser [mínimo, máximo] en segundos, p. ej. [1, 3]")
        return v


class Settings(_Strict):
    scan: ScanSettings = ScanSettings()
    http: HttpSettings = HttpSettings()
    sources: dict[str, dict] = {}
    companies: list[dict] = []
    watch: list[dict] = []


def _spanish_errors(exc: ValidationError, where: str) -> ConfigError:
    lines = []
    for e in exc.errors():
        key = ".".join(str(p) for p in e["loc"]) or "(raíz)"
        if e["type"] == "extra_forbidden":
            lines.append(f"clave desconocida '{key}'")
        elif e["type"] == "missing":
            lines.append(f"falta la clave '{key}'")
        else:
            lines.append(f"clave '{key}': valor no válido ({e['msg']})")
    return ConfigError(f"Error en {where}: " + "; ".join(lines))


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"No se encuentra el archivo {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"El archivo {path} no es un YAML válido: {exc}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"El archivo {path} debe contener un mapa de claves")
    return data


def load_settings(path: Path) -> Settings:
    data = _read_yaml(Path(path))
    try:
        return Settings(**data)
    except ValidationError as exc:
        raise _spanish_errors(exc, str(path)) from None


def load_env(path: str | Path = ".env") -> dict:
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def _atomic_write_yaml(path: Path, data: dict) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def load_searches(path: Path) -> tuple[list[Search], Exclusions]:
    if not Path(path).exists():
        return [], Exclusions()
    data = _read_yaml(Path(path))
    try:
        searches = [Search(**s) for s in data.get("busquedas") or []]
        excl = Exclusions(**(data.get("exclusiones") or {}))
    except ValidationError as exc:
        raise _spanish_errors(exc, str(path)) from None
    except TypeError:
        raise ConfigError(f"Error en {path}: formato de búsquedas no válido") from None
    return searches, excl


def save_searches(path: Path, searches: list[Search], excl: Exclusions) -> None:
    _atomic_write_yaml(path, {
        "busquedas": [s.model_dump() for s in searches],
        "exclusiones": excl.model_dump(),
    })


def add_user_synonym(path: Path, group: str, term: str) -> None:
    """Añade un término a un grupo de sinonimos_usuario.yaml (sin duplicados)."""
    path = Path(path)
    data = _read_yaml(path) if path.exists() else {}
    terms = list(data.get(group) or [])
    if fold(term) not in {fold(t) for t in terms}:
        terms.append(term)
    data[group] = terms
    _atomic_write_yaml(path, data)
