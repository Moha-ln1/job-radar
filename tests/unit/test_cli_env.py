import pytest
import yaml

from jobradar import cli


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    return tmp_path


def test_env_set_writes_without_printing_value(home, monkeypatch, capsys):
    (home / ".env.example").write_text("# ejemplo\nTELEGRAM_BOT_TOKEN=\nOTRA=1\n", encoding="utf-8")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "s3cr3t-token")
    assert cli.main(["env", "set", "TELEGRAM_BOT_TOKEN"]) == 0
    captured = capsys.readouterr()
    assert "s3cr3t-token" not in captured.out + captured.err
    assert (home / ".env").read_text(encoding="utf-8") == "# ejemplo\nTELEGRAM_BOT_TOKEN=s3cr3t-token\nOTRA=1\n"
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "nuevo")
    assert cli.main(["env", "set", "NUEVA"]) == 0
    text = (home / ".env").read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=s3cr3t-token" in text and text.endswith("NUEVA=nuevo\n")


def test_env_set_rejects_bad_key_and_empty_value(home, monkeypatch):
    assert cli.main(["env", "set", "mala clave"]) == 2
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "  ")
    assert cli.main(["env", "set", "X"]) == 1
    assert not (home / ".env").exists()


CONFIG = """# cabecera
sources:
  ats: {enabled: true}   # comentario

# Webs de empresas
companies:
  - {name: GitLab, ats: greenhouse, slug: gitlab}
  # a medias
  - {name: Bosch, ats: smartrecruiters, slug: BoschGroup}

watch:
  - {name: X, url: "https://x.org/"}
"""


def test_ats_add_preserves_comments(home, capsys):
    (home / "config.yaml").write_text(CONFIG, encoding="utf-8")
    assert cli.main(["ats", "detect", "https://jobs.lever.co/acme-corp", "--add"]) == 0
    text = (home / "config.yaml").read_text(encoding="utf-8")
    assert "# cabecera" in text and "# comentario" in text and "# a medias" in text
    lines = text.splitlines()
    i = lines.index("  - {name: Acme Corp, ats: lever, slug: acme-corp}")
    assert lines[i - 1].startswith("  - {name: Bosch") and lines[i + 1] == "" and lines[i + 2] == "watch:"
    assert cli.main(["ats", "detect", "https://jobs.lever.co/acme-corp", "--add"]) == 0
    assert (home / "config.yaml").read_text(encoding="utf-8") == text
    assert "ya estaba" in capsys.readouterr().out


def test_ats_add_workday_slug_is_valid_yaml(home):
    (home / "config.yaml").write_text("sources: {}\n", encoding="utf-8")
    assert cli.main(["ats", "detect", "https://acme.wd3.myworkdayjobs.com/en-US/Ext", "--add"]) == 0
    data = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    assert data["companies"] == [{"name": "Acme", "ats": "workday", "slug": "acme.wd3/Ext"}]


def test_autostart_cli_dry_run(home, capsys):
    assert cli.main(["autostart", "on", "--dry-run"]) == 0
    assert "simulación" in capsys.readouterr().out
