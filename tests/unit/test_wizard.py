import pytest

from jobradar import bot, wizard
from jobradar.config import load_searches, save_searches
from jobradar.models import Exclusions, Search
from jobradar.paths import Paths


class FakeQ:
    """Sustituye al módulo questionary: cada pregunta devuelve la siguiente respuesta guionizada."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def _mk(self, kind):
        def make(message, **kw):
            self.asked.append((kind, message, kw))
            ans = self.answers.pop(0)
            return type("Q", (), {"ask": lambda self_: ans})()
        return make

    def __getattr__(self, name):
        if name in ("checkbox", "select", "text", "confirm"):
            return self._mk(name)
        raise AttributeError(name)

    class Choice:
        def __init__(self, title, value=None, checked=False):
            self.title, self.value, self.checked = title, value, checked


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(wizard.radar, "reevaluate", lambda paths, ids: [])
    return Paths(tmp_path)


def test_full_flow_saves_and_appends(home, monkeypatch):
    save_searches(home.searches, [Search(id="b1", name="Vieja")], Exclusions(words=["senior"]))
    fake = FakeQ([["practicas", wizard.OTHER], "ia generativa", ["programador"], ["presencial"],
                  ["granada"], "normal", "", True])
    monkeypatch.setattr(wizard, "questionary", fake)
    assert wizard.main(home) == 0
    searches, excl = load_searches(home.searches)
    assert [s.id for s in searches] == ["b1", "b2"] and excl.words == ["senior"]
    new = searches[1]
    assert new.tipos == ["practicas", "ia generativa"] and new.modalidades == ["presencial"]
    assert new.ubicaciones == ["granada"] and new.prioridad == "normal"
    assert new.name == bot.auto_name(bot.search_to_state(new))


def test_remote_only_skips_location(home, monkeypatch):
    fake = FakeQ([[], [], ["remoto"], "alta", "Mi nombre", True])
    monkeypatch.setattr(wizard, "questionary", fake)
    assert wizard.main(home) == 0
    s = load_searches(home.searches)[0][0]
    assert s.name == "Mi nombre" and s.ubicaciones == [] and s.modalidades == ["remoto"]
    assert [k for k, *_ in fake.asked].count("checkbox") == 3


def test_ctrl_c_saves_nothing(home, monkeypatch):
    monkeypatch.setattr(wizard, "questionary", FakeQ([["practicas"], None]))
    assert wizard.main(home) == 0
    assert not home.searches.exists()


def test_decline_confirmation(home, monkeypatch):
    monkeypatch.setattr(wizard, "questionary", FakeQ([[], [], ["remoto"], "alta", "", False]))
    assert wizard.main(home) == 0
    assert not home.searches.exists()


def test_not_a_tty_exits_2(home, monkeypatch, capsys):
    monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: False, raising=False)
    assert wizard.main(home) == 2
    assert "Telegram" in capsys.readouterr().out
