"""Rutas de los archivos de trabajo de jobradar."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Paths:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def searches(self) -> Path:
        return self.root / "busquedas.yaml"

    @property
    def user_synonyms(self) -> Path:
        return self.root / "sinonimos_usuario.yaml"

    @property
    def db(self) -> Path:
        return self.root / "jobradar.db"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def env(self) -> Path:
        return self.root / ".env"

    @property
    def state(self) -> Path:
        return self.root / "estado.json"

    @classmethod
    def default(cls) -> "Paths":
        home = os.environ.get("JOBRADAR_HOME")
        if home:
            return cls(Path(home))
        repo = Path(__file__).resolve().parents[2]
        return cls(repo if (repo / "pyproject.toml").exists() else Path.cwd())
