from pathlib import Path

import pytest
import yaml

from jobradar.config import (ConfigError, add_user_synonym, load_env, load_searches,
                             load_settings, save_searches)
from jobradar.models import Exclusions, Search

ROOT = Path(__file__).resolve().parents[2]


def test_settings_de_ejemplo():
    s = load_settings(ROOT / "config.example.yaml")
    assert s.scan.max_age_days == 14 and s.http.delay_seconds == [1, 3]
    assert s.sources["linkedin"]["max_pages"] == 2 and len(s.companies) == 3


def test_clave_erronea_en_espanol(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("scan:\n  cada_horas: 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="clave desconocida 'scan.cada_horas'"):
        load_settings(p)


def test_archivo_inexistente(tmp_path):
    with pytest.raises(ConfigError, match="No se encuentra"):
        load_settings(tmp_path / "no.yaml")


def test_busquedas_roundtrip_utf8(tmp_path):
    p = tmp_path / "busquedas.yaml"
    s = [Search(id="1", name="Prácticas Programación", tipos=["practicas"], ubicaciones=["Málaga"])]
    save_searches(p, s, Exclusions(words=["sénior"], companies=["Año S.L."]))
    assert "Prácticas" in p.read_text(encoding="utf-8")
    s2, ex = load_searches(p)
    assert s2 == s and ex.words == ["sénior"] and ex.companies == ["Año S.L."]
    assert not (tmp_path / "busquedas.yaml.tmp").exists()


def test_busquedas_inexistente(tmp_path):
    assert load_searches(tmp_path / "x.yaml") == ([], Exclusions())


def test_add_user_synonym(tmp_path):
    p = tmp_path / "sinonimos_usuario.yaml"
    add_user_synonym(p, "practicas", "Stage")
    add_user_synonym(p, "practicas", "stage")
    assert yaml.safe_load(p.read_text(encoding="utf-8")) == {"practicas": ["Stage"]}


def test_load_env(tmp_path):
    p = tmp_path / ".env"
    p.write_text("TOKEN=abc\n", encoding="utf-8")
    assert load_env(p) == {"TOKEN": "abc"}
