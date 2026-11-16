"""Ajustes cambiados desde el bot (ajustes_bot.yaml) sobre config.yaml."""
from jobradar import cli
from jobradar.config import bot_settings_path, load_settings, save_bot_settings

CONFIG = """# comentario que debe conservarse
sources:
  linkedin: {enabled: true, max_pages: 2}
  infojobs: {enabled: true}
companies:
  - {name: Acme, ats: greenhouse, slug: acme}
watch:
  - {name: A, url: "https://a.invalid/"}
"""


def test_bot_settings_override_and_keep_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    save_bot_settings(cfg, source_enabled=("linkedin", False))
    s = load_settings(cfg)
    assert s.sources["linkedin"] == {"enabled": False, "max_pages": 2}  # se combina, no se pierde max_pages
    assert s.companies == [{"name": "Acme", "ats": "greenhouse", "slug": "acme"}]  # sin tocar: los de config
    save_bot_settings(cfg, watch=[])
    assert load_settings(cfg).watch == []  # lista tocada desde el bot: sustituye
    assert cfg.read_text(encoding="utf-8") == CONFIG
    assert bot_settings_path(cfg).exists()


def test_cli_ats_add_goes_to_bot_list_when_bot_manages_it(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(CONFIG, encoding="utf-8")
    save_bot_settings(cfg, companies=[])  # el usuario quitó Acme desde /empresas
    assert cli.main(["ats", "detect", "https://jobs.lever.co/nuevaempresa", "--add"]) == 0
    assert load_settings(cfg).companies == [{"name": "Nuevaempresa", "ats": "lever", "slug": "nuevaempresa"}]
    assert cfg.read_text(encoding="utf-8") == CONFIG
