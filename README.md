<img src="docs/img/avatar.png" alt="" width="96" align="right">

# JobRadar

JobRadar busca en tu PC convocatorias cortas (prácticas, trainee y empleo junior) en webs de empresas,
APIs de empleo y portales, y te avisa por Telegram. Una misma oferta publicada en varios portales llega una sola vez,
con todos sus enlaces. Las búsquedas se crean con botones, sin tocar archivos.

## Ejemplo de aviso

Ejemplo ficticio de cómo llega un aviso al chat de Telegram:

```
🔥 Desarrollador/a Backend en prácticas — Ejemplo Tech S.L. · Granada (híbrido)
🔎 Búsqueda: Prácticas de programación · Granada
🔗 LinkedIn · Greenhouse

[🚫 Ocultar empresa] [👎 No me interesa]
```

🔥 llega al momento; 📰 llega en el resumen diario. Si la misma oferta aparece después en otro portal, JobRadar
responde al aviso original:

```
➕ También en InfoJobs
```

## Características

- **Fuentes de empresas (APIs sin clave)**: Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Recruitee,
  Personio y Teamtailor.
- **Empleo remoto (APIs sin clave)**: Remotive, RemoteOK, We Work Remotely y Himalayas.
- **APIs oficiales opcionales (con clave gratuita)**: InfoJobs, Adzuna y Jooble. Sin clave se usan las webs públicas.
- **Portales**: LinkedIn, InfoJobs, Tecnoempleo, Infoempleo y Primer Empleo.
- **Vigilancia de páginas**: avisa cuando aparece algo nuevo en páginas de convocatorias sin listado de ofertas (p. ej. la de prácticas de tu universidad).
- **Para cualquier sector**: 27 áreas (de programación a hostelería, salud o logística) y todas las comunidades
  autónomas. Se empieza sin búsquedas, empresas ni páginas de nadie: cada uno crea las suyas.
- **Filtros con botones y sinónimos**: tipo, área, modalidad y ubicación, en español e inglés.
- **Bot listo de serie**: al primer arranque se pone nombre, foto de perfil y descripción.
- **Todo se configura desde Telegram**: búsquedas, exclusiones, fuentes (`/fuentes`), webs de empresas (`/empresas`)
  y páginas vigiladas (`/paginas`), sin editar archivos.
- **Ante la duda, se incluye**: si una oferta no dice su área, su modalidad o una ubicación conocida, no se descarta.
- **Ofertas repetidas**: una sola notificación con todos los enlaces.
- **Revisión de descartes**: `/descartadas` muestra qué se ha descartado y por qué, y permite rescatar ofertas.

## Inicio rápido

Requisitos: Python 3.10 o superior, git y una cuenta de Telegram.

**Windows**

```
git clone https://github.com/Moha-ln1/job-radar.git
cd job-radar
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

**Linux / macOS**

```
git clone https://github.com/Moha-ln1/job-radar.git
cd job-radar
bash scripts/setup.sh
```

El instalador crea el entorno virtual, instala JobRadar, configura Telegram y tus búsquedas, y pregunta si quieres
que arranque al iniciar sesión. Es seguro repetirlo.

### Arrancar, parar y comprobar

Con el autoarranque activado no hay que hacer nada al encender el PC: el bot arranca solo al iniciar sesión.
Si lo desactivaste o el bot no responde, arráncalo a mano desde la carpeta del proyecto:

| Acción | Windows | Linux / macOS |
|---|---|---|
| Arrancar | `.venv\Scripts\jobradar.exe run` | `.venv/bin/jobradar run` |
| Parar | `.venv\Scripts\jobradar.exe stop` | `.venv/bin/jobradar stop` |
| ¿Está en marcha? | `.venv\Scripts\jobradar.exe status` | `.venv/bin/jobradar status` |
| Autoarranque | `.venv\Scripts\jobradar.exe autostart on` / `off` | `.venv/bin/jobradar autostart on` / `off` |

`run` deja la terminal ocupada mientras el bot funciona; ciérrala o pulsa Ctrl+C para pararlo. En Telegram,
`/estado` responde si el bot está vivo y muestra cada fuente con su último escaneo y el porcentaje de datos completos.

### Configurar desde Telegram

Al terminar la instalación, abre tu bot y escribe `/busquedas` → **➕ Nueva búsqueda**. Son 5 pasos con botones:
tipo, área, modalidad, ubicación y cuándo avisarte. No hace falta tocar ningún archivo:

| Quiero… | Comando |
|---|---|
| Elegir qué ofertas me llegan | `/busquedas` |
| No ver nunca una palabra o una empresa | `/excluir` |
| Apagar LinkedIn u otra fuente | `/fuentes` |
| Seguir la web de empleo de una empresa | `/empresas` |
| Vigilar una página de convocatorias | `/paginas` |
| Saber si un título me llegaría | `/probar <título>` |
| Ver todas las ofertas de la semana, por búsqueda | `/semana` |
| Ver qué se ha descartado y por qué | `/descartadas` |

El [tutorial](docs/TUTORIAL.md#5-primer-uso-del-bot) lo explica paso a paso, con un ejemplo de búsquedas.

## Documentación

- [docs/TUTORIAL.md](docs/TUTORIAL.md): instalación paso a paso, primer uso del bot y solución de problemas.
- [docs/APIS.md](docs/APIS.md): cómo obtener las claves gratuitas de InfoJobs, Adzuna y Jooble.
- [docs/FUENTES.md](docs/FUENTES.md): fuentes disponibles, cómo añadir empresas y páginas, y notas para desarrolladores.

## Aviso legal

- JobRadar es una herramienta de uso personal. Cada usuario es responsable de cumplir las condiciones de uso de
  cada web que consulte.
- LinkedIn prohíbe el scraping en sus condiciones. La fuente de LinkedIn viene activada, pero puedes desactivarla
  con `/fuentes` en el bot.
- RemoteOK exige citar y enlazar su web como fuente; si reenvías o publicas ofertas de RemoteOK, hazlo así.
- JobRadar no evita CAPTCHAs ni bloqueos. Si una web bloquea las peticiones, la fuente se pausa.

## Privacidad

Todo se ejecuta en tu equipo. El token de Telegram y las claves están en `.env`, y la base de datos está en
`jobradar.db`. Ni `.env` ni la base de datos se suben a git.

## Licencia

MIT.
