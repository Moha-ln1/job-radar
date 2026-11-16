
import pytest

from jobradar import cli, sources
from jobradar.config import save_searches
from jobradar.models import Exclusions, JobOffer, Search


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBRADAR_HOME", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    (tmp_path / "config.yaml").write_text("sources:\n  fake: {enabled: true}\n", encoding="utf-8")
    save_searches(tmp_path / "busquedas.yaml",
                  [Search(id="b1", name="Prácticas dev", tipos=["practicas"], areas=["programador"])],
                  Exclusions(words=["senior"]))
    return tmp_path


def test_probar_matches_and_rejects(home, capsys):
    assert cli.main(["filtros", "probar", "Becario Programador"]) == 0
    assert "Encaja" in capsys.readouterr().out
    assert cli.main(["filtros", "probar", "Senior Gerente de Ventas"]) == 0
    out = capsys.readouterr().out
    assert "No encaja" in out and "senior" in out
    assert cli.main(["filtros", "probar", "x"]) == 2


def test_explicar(home, capsys):
    assert cli.main(["filtros", "explicar"]) == 0
    out = capsys.readouterr().out
    assert "Prácticas dev" in out and "internship" in out and "senior" in out


def test_scan_dry_run_with_fake_fetchers(home, monkeypatch, capsys):
    async def fake(ctx):
        return [JobOffer(title="Becario Programador", url="https://x.com/1", source="fake", company="Acme"),
                JobOffer(title="Director Comercial", url="https://x.com/2", source="fake", company="Acme")]
    monkeypatch.setattr(sources, "all_fetchers", lambda: {"fake": fake})
    assert cli.main(["scan", "--dry-run", "--only", "fake"]) == 0
    out = capsys.readouterr().out
    assert "fake" in out and "encajan: 1" in out and "descartadas: 1" in out and "Becario Programador" in out
    assert not (home / "jobradar.db").exists()


def test_scan_all_sources_failing_returns_1(home, monkeypatch, capsys):
    async def broken(ctx):
        raise RuntimeError("caída")
    monkeypatch.setattr(sources, "all_fetchers", lambda: {"fake": broken})
    assert cli.main(["scan", "--dry-run", "--only", "fake"]) == 1
    assert "ERROR: caída" in capsys.readouterr().out


def test_telegram_commands_without_credentials(home, capsys):
    assert cli.main(["telegram", "test"]) == 2
    assert "chat-id" in capsys.readouterr().out
    assert cli.main(["run"]) == 2


def test_no_command_prints_help(capsys):
    assert cli.main([]) == 0
    assert "scan" in capsys.readouterr().out


def test_init_db_recent_status(home, capsys):
    assert cli.main(["init-db"]) == 0
    assert cli.main(["recent"]) == 0
    assert cli.main(["status"]) == 0
    assert "parado" in capsys.readouterr().out
