# JobRadar

JobRadar busca en tu PC convocatorias cortas (prácticas, trainee, bootcamp/academy y empleo junior) en webs de empresas,
APIs de empleo y portales, y te avisa por Telegram. Una misma oferta publicada en varios portales llega una sola vez,
con todos sus enlaces. Las búsquedas se crean con botones, sin tocar archivos.

## Ejemplo de aviso

Ejemplo ficticio de cómo llega un aviso al chat de Telegram:

```
Nueva oferta: Prácticas
Desarrollador/a Backend (prácticas)
Empresa: Ejemplo Tech S.L.
Ubicación: Granada (híbrido)
Enlaces: LinkedIn · Greenhouse

[🚫 Ocultar empresa] [👎 No me interesa]
```

Si la misma oferta aparece después en otro portal, JobRadar responde al aviso original:

```
También en InfoJobs
```

## Características

- **Fuentes de empresas (APIs sin clave)**: Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Recruitee,
  Personio y Teamtailor.
- **Empleo remoto (APIs sin clave)**: Remotive, RemoteOK, We Work Remotely y Himalayas.
- **APIs oficiales opcionales (con clave gratuita)**: InfoJobs, Adzuna y Jooble. Sin clave se usan las webs públicas.
- **Portales**: LinkedIn, InfoJobs, Tecnoempleo, Infoempleo y Primer Empleo.
- **Vigilancia de páginas**: avisa cuando aparece algo nuevo en páginas de programas sin listado de ofertas.
- **Filtros con botones y sinónimos**: tipo, área, modalidad y ubicación, en español e inglés.
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

## Documentación

- [docs/TUTORIAL.md](docs/TUTORIAL.md): instalación paso a paso, primer uso del bot y solución de problemas.
- [docs/APIS.md](docs/APIS.md): cómo obtener las claves gratuitas de InfoJobs, Adzuna y Jooble.
- [docs/FUENTES.md](docs/FUENTES.md): fuentes disponibles, cómo añadir empresas y páginas, y notas para desarrolladores.

## Aviso legal

- JobRadar es una herramienta de uso personal. Cada usuario es responsable de cumplir las condiciones de uso de
  cada web que consulte.
- LinkedIn prohíbe el scraping en sus condiciones. La fuente de LinkedIn viene activada, pero puedes desactivarla
  en `config.yaml`.
- RemoteOK exige citar y enlazar su web como fuente; si reenvías o publicas ofertas de RemoteOK, hazlo así.
- JobRadar no evita CAPTCHAs ni bloqueos. Si una web bloquea las peticiones, la fuente se pausa.

## Privacidad

Todo se ejecuta en tu equipo. El token de Telegram y las claves están en `.env`, y la base de datos está en
`jobradar.db`. Ni `.env` ni la base de datos se suben a git.

## Licencia

MIT.
