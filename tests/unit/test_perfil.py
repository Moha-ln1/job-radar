from telegram.error import TimedOut

from jobradar import perfil


class FakeBot:
    id = 777

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def _call(self, name, *args):
        if self.fail:
            raise TimedOut()
        self.calls.append(name)
        return True

    async def set_my_name(self, name):
        return await self._call("name")

    async def set_my_short_description(self, text):
        return await self._call("short")

    async def set_my_description(self, text):
        return await self._call("description")

    async def set_my_profile_photo(self, photo):
        return await self._call("photo")


def test_textos_caben_en_los_limites_de_telegram():
    assert len(perfil.NAME) <= 64 and len(perfil.SHORT_DESCRIPTION) <= 120 and len(perfil.DESCRIPTION) <= 512
    assert perfil.AVATAR.is_file()


async def test_se_aplica_una_vez_por_bot(tmp_path):
    marker = tmp_path / "perfil_bot.txt"
    bot = FakeBot()
    assert await perfil.apply_profile(bot, marker)
    assert bot.calls == ["name", "short", "description", "photo"]
    assert not await perfil.apply_profile(bot, marker)  # segundo arranque: no pisa cambios de BotFather
    assert len(bot.calls) == 4
    otro = FakeBot()
    otro.id = 888  # otro token en el mismo .env: se aplica de nuevo
    assert await perfil.apply_profile(otro, marker)


async def test_un_fallo_no_impide_arrancar_y_se_reintenta(tmp_path):
    marker = tmp_path / "perfil_bot.txt"
    assert not await perfil.apply_profile(FakeBot(fail=True), marker)
    assert not marker.exists()
