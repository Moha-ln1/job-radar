# Arquitectura de Job Radar

Proceso local que busca convocatorias cortas (prácticas, trainee, junior) en APIs y portales,
junta la misma oferta publicada en varios portales y **avisa por Telegram**. Las búsquedas se configuran **con
botones** (en el bot o en el asistente de instalación). Se ejecuta en el PC del usuario; repo público con licencia MIT.

Fuera del alcance actual: navegador sin interfaz (Playwright), Glassdoor/Indeed, panel web, app móvil y
despliegue 24/7 (Docker/VPS/Raspberry Pi).

---

## 1. Principios de calidad

### 1.1 Los filtros no deben descartar ofertas válidas
Ante la duda, **se incluye**: es preferible una oferta de más que perder una convocatoria.

1. **Nada se borra.** Todas las ofertas extraídas se guardan, encajen o no. Cada una lleva su decisión
   (`avisada` / `descartada`) y **el motivo exacto** ("excluida por 'senior' en el título", "ubicación Madrid ∉
   [Granada]", "ninguna búsqueda: tipo no reconocido").
2. **Lo que falta no descarta.** Modalidad, región del remoto, ubicación o fecha desconocidas → la oferta pasa.
3. **El tipo y el área se buscan en el título y en los campos de categoría o departamento**, nunca en la
   descripción: allí "buenas prácticas" o "trabajarás con perfiles senior" generarían falsos positivos y falsos
   descartes.
4. **Las exclusiones solo miran el título**, y si el título contiene a la vez un término de tipo de la búsqueda
   (p. ej., "Junior/Senior Developer"), la oferta no se excluye: el caso ambiguo se incluye.
5. **Revisable**: `/descartadas` en el bot (y `jobradar descartadas`) muestra lo descartado en las últimas 24 h
   agrupado por motivo, con botón `[➕ Era buena: añadir a la búsqueda]` que añade el término al grupo y la avisa.
6. **Búsquedas nuevas retroactivas**: al guardar una búsqueda, se aplica a lo ya guardado de los últimos 14 días
   ("Esta búsqueda ya encaja con 7 ofertas guardadas → [Ver]").
7. **Conjunto de referencia** (`tests/golden/titulos.yaml`): ≥ 150 títulos reales de las fuentes, etiquetados a mano
   (debe encajar / no debe encajar con las búsquedas por defecto). Criterio de aceptación: **recall 100 %** (ninguna
   oferta etiquetada como "debe encajar" descartada); la precisión se mide y se reporta, sin umbral bloqueante.
   Cada fallo real que encontremos en uso se añade al conjunto como test de regresión.

### 1.2 La información extraída debe ser correcta
1. **Contrato por fuente** (`tests/sources/`): fixtures reales recortados y tests que comprueban campo a campo
   el título, la empresa, la URL, la ubicación y la fecha de ofertas concretas conocidas.
2. **Validación al extraer** (pydantic + reglas):
   - título y URL obligatorios;
   - URL absoluta y del dominio de la fuente, sin parámetros de seguimiento;
   - sin restos de HTML ni espacios basura;
   - título ≠ empresa, y título entre 3 y 200 caracteres;
   - fecha no futura y no anterior a 1 año.

   La oferta que no cumple se rechaza y se registra en el log con el motivo, no se guarda a medias.
3. **Contraste con la página de detalle**: muchas páginas de detalle sí traen JSON-LD `JobPosting`.
   `jobradar verificar` toma 3 ofertas por fuente, abre su detalle y compara título y empresa con lo extraído
   del listado (normalizados; similitud ≥ 0,9).
4. **Salud de cada fuente en cada escaneo**: número de ofertas y % de campos rellenos. Si una fuente devuelve 0
   ofertas cuando normalmente trae más, o baja más de 30 puntos en campos rellenos (un selector roto), se avisa por
   Telegram (máx. 1 aviso/día/fuente) y aparece en `/estado`.
5. **`jobradar verificar`** es el comando de comprobación real: escanea cada fuente activa, aplica 2–4 y muestra
   una tabla de OK/FALLO por fuente. Se ejecuta antes de cerrar cada fase que toque fuentes.

---

## 2. Fuentes

Prioridad: **API → HTML → vigilar la página**.

| Tipo | Fuentes | Estado |
|---|---|---|
| API sin clave (webs de empleo de empresas, ATS) | Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Recruitee, Personio (XML), Teamtailor (RSS) | 200 con datos |
| API sin clave (empleo remoto) | Remotive, RemoteOK, We Work Remotely (RSS), Himalayas; Arbeitnow desactivada por defecto | 200 con datos |
| API con clave gratuita (opcional) | InfoJobs oficial, Adzuna, Jooble | 401/400 sin clave, esperado |
| HTML | LinkedIn (guest), InfoJobs (sin clave), Tecnoempleo, Infoempleo, Primer Empleo | 200 con ofertas en el HTML |
| Vigilancia de páginas | Las que añada el usuario (`/paginas`) | 200 |
| No incluidas | Indeed, Glassdoor, web de Jooble (403); WTTJ, StudentJob (JS); Talent.com (duplicados); Jobatus (no responde); EURES, Empléate (apps JS); Ícaro (requiere cuenta) | — |

- Ritmo: 1–3 s entre peticiones al mismo dominio, topes de páginas y términos por escaneo, `timeout_seconds` y
  `min_interval_hours` propios por fuente (LinkedIn 4 h, InfoJobs y Remotive 6 h).
- Bloqueos: un 403/429 o un muro anti-bot servido con 200 marcan la fuente como bloqueada. Cada bloqueo seguido
  duplica su pausa (6 h, 12 h, 24 h… hasta 48 h) y una ejecución correcta la pone a cero; `/estado` muestra
  hasta cuándo descansa.
- InfoJobs: con clave se usa su API oficial; el registro de aplicaciones de InfoJobs puede estar cerrado, en cuyo
  caso se lee el HTML de resultados.
- RemoteOK: citar y enlazar la fuente (exigido por sus términos).
- `jobradar ats detect <url>` identifica el ATS de una web de empleo y añade la empresa a la lista.

## 3. Ofertas repetidas → una oferta, todos sus enlaces

```
jobs      (id, key, title, company, company_norm, location, modality, first_seen,
           status, reasons, matched_searches, notified_at, tg_message_id)
postings  (id, job_id, source, url UNIQUE, posted_at, first_seen, raw_title, raw_company)
```
Emparejamiento:
1. Normalización: minúsculas, sin tildes ni signos; se quitan `(h/m)`, `(m/f/d)`, `h/m/x`, sufijos de ubicación
   y modalidad, y las formas jurídicas o de país de la empresa (S.L., S.A., SLU, Spain, España, Group).
2. Clave exacta `empresa_norm|título_norm`.
3. Si no la hay: misma empresa, últimos 30 días y `difflib` sobre los tokens ordenados con ratio ≥ 0,90.
4. Sin empresa → no se fusiona.

Aviso con todos los enlaces (`🔗 LinkedIn · InfoJobs · Workday`). Si aparece un portal nuevo en una oferta ya avisada,
se edita el mensaje original y se responde a él con `➕ También en X`.

## 4. Filtros

### 4.1 Modelo
Una **búsqueda** tiene los campos Tipo, Área, Modalidad, Ubicación y Avisos (🔥 al momento / 📰 resumen diario).
- Dentro de un campo basta con una opción (O); entre campos se exigen todos (Y); entre búsquedas basta con una (O).
- Campo vacío o "Cualquiera" → no filtra.
- La ubicación solo se aplica a presencial e híbrido; el remoto se filtra por región (España/Europa/Mundial),
  y si no se conoce la región, se incluye.
- Las exclusiones globales (palabras y empresas) ganan, con las salvedades de 1.1.4.
- Antigüedad máxima: 14 días (`posted_at`; si no hay, `first_seen`). No se aplica a las fuentes ATS
  (`filters.LIVE_BOARDS`): solo listan ofertas abiertas.

### 4.2 Sinónimos (`src/jobradar/data/sinonimos.yaml`)
Cada opción del catálogo es un grupo en español e inglés (Prácticas = prácticas, intern, internship, becario/a,
beca, pasantía, work placement, FP dual…). Sin distinguir mayúsculas ni tildes, por palabra completa (`intern` no coincide con
"International") y con femenino y plural automáticos. El usuario puede añadir términos desde el bot
(`/descartadas → Era buena` o `✏️ Otra…`); se guardan en `sinonimos_usuario.yaml`.

### 4.3 Configuración con botones
- **Bot**: `/busquedas` (crear, editar, pausar, borrar en 5 pasos con botones), `/excluir`, `/descartadas`,
  `/probar <texto>`, `/recientes`, `/semana`, `/estado`, `/silencio`, `/escanear`. Botones en cada aviso:
  `[🚫 Ocultar empresa] [👎 No me interesa]`. **Solo responde al `chat_id` configurado.**
- **Asistente de instalación**: `jobradar configurar` (questionary), mismas preguntas, mismo catálogo.
- Archivos que escribe la app (no hace falta tocarlos): `busquedas.yaml`, `sinonimos_usuario.yaml`.
  `config.yaml` = ajustes técnicos, ya listo para usar.

## 5. Ejecución

`jobradar run` = bot (long polling) + programador interno: escaneo cada 2 h, resumen diario a las 09:00
y recuperación del escaneo atrasado al despertar el PC. El primer escaneo es una línea base: lo que ya existía
queda como visto y no se avisa. Arranque automático al iniciar sesión (`jobradar autostart on`): en Windows un
`.vbs` en la carpeta Inicio del usuario (sin permisos de administrador, sin ventana); en Linux un servicio de
usuario de systemd; en macOS un LaunchAgent. Logs en `logs/jobradar.log`, que rota.

## 6. Estructura

```
src/jobradar/
  models.py  config.py  normalize.py  dedup.py  store.py  filters.py
  http.py  radar.py  health.py  verify.py
  sources/ (linkedin, infojobs, tecnoempleo, infoempleo, primerempleo, ats, remote, watch)
  notify.py  bot.py  scheduler.py  wizard.py  cli.py
  data/ (sinonimos.yaml, catalogo.yaml)
tests/ (unit/, sources/ + fixtures, golden/titulos.yaml)
scripts/ (setup.ps1, setup.sh)
docs/ (TUTORIAL.md, FUENTES.md)
.github/workflows/tests.yml  config.example.yaml  .env.example  .gitignore  pyproject.toml  LICENSE  README.md
```
Dependencias: httpx, beautifulsoup4, lxml, pydantic, pyyaml, python-dotenv, python-telegram-bot[job-queue],
questionary; para desarrollo, pytest y pytest-asyncio. Python ≥ 3.10 (en local, 3.14).
