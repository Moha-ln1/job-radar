# Fuentes de ofertas

JobRadar consulta estas fuentes en cada escaneo. Las APIs y las webs de empresas van primero; la vigilancia de páginas
va al final. Las fuentes que necesitan clave gratuita se desactivan solas si no la tienen (ver [APIS.md](APIS.md)).

## Tabla de fuentes

| Fuente | Tipo | Necesita clave | Qué trae |
|---|---|---|---|
| Greenhouse | API de empresa (ATS) | No | Ofertas de las empresas de `companies:`. |
| Lever | API de empresa (ATS) | No | Ofertas de las empresas de `companies:`. |
| Ashby | API de empresa (ATS) | No | Ofertas de las empresas de `companies:`. |
| SmartRecruiters | API de empresa (ATS) | No | Ofertas de las empresas de `companies:`. |
| Workday | API de empresa (ATS) | No | Ofertas de las empresas de `companies:`. |
| Recruitee | API de empresa (ATS) | No | Ofertas de las empresas de `companies:`. |
| Personio | XML de empresa (ATS) | No | Ofertas de las empresas de `companies:`. |
| Teamtailor | RSS de empresa (ATS) | No | Ofertas de las empresas de `companies:`. |
| Remotive | API de empleo remoto | No | Ofertas remotas. Consulta como mucho cada 6 h (`min_interval_hours`). |
| RemoteOK | API de empleo remoto | No | Ofertas remotas. Hay que citar y enlazar la fuente. |
| We Work Remotely | RSS de empleo remoto | No | Ofertas remotas. |
| Himalayas | API de empleo remoto | No | Ofertas remotas. |
| Arbeitnow | API de empleo | No | Desactivada por defecto. |
| InfoJobs | API oficial o HTML público | Opcional (`INFOJOBS_CLIENT_ID`, `INFOJOBS_CLIENT_SECRET`) | Ofertas de InfoJobs. Sin clave lee la web pública. |
| Adzuna | API oficial | Opcional (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`) | Ofertas de varios portales agregados. |
| Jooble | API oficial | Opcional (`JOOBLE_API_KEY`) | Ofertas de varios portales agregados. |
| LinkedIn | HTML (vista de invitados) | No | Ofertas de LinkedIn. Prohibido por sus condiciones: uso bajo tu responsabilidad. |
| Tecnoempleo | HTML | No | Ofertas del portal Tecnoempleo. |
| Infoempleo | HTML | No | Ofertas del portal Infoempleo. |
| Primer Empleo | HTML | No | Ofertas del portal Primer Empleo. |
| Vigilancia de páginas | Página web | No | Avisa cuando aparece contenido nuevo en las páginas de `watch:`. |

## Añadir empresas

Las webs de empleo de empresas se detectan y se añaden con:

```
jobradar ats detect <url> --add
```

`ats detect` identifica el sistema de reclutamiento que usa la web (Greenhouse, Lever, Workday...) y, con `--add`,
añade la empresa al bloque `companies:` de `config.yaml`. Sin `--add` solo muestra lo que ha encontrado.

También puedes añadirla a mano:

```yaml
companies:
  - {name: GitLab, ats: greenhouse, slug: gitlab}
  - {name: Bosch, ats: smartrecruiters, slug: BoschGroup}
```

## Añadir páginas vigiladas

Algunas páginas de programas no tienen listado de ofertas, pero publican novedades. Para ellas, añade un bloque
`watch:` en `config.yaml`:

```yaml
watch:
  - {name: Factoría F5, url: "https://factoriaf5.org/"}
  - {name: Generation Spain, url: "https://spain.generation.org/"}
  - {name: 42 Málaga, url: "https://42malaga.com/"}
  - {name: Mi bootcamp, url: "https://ejemplo.com/convocatorias"}
```

JobRadar avisa cuando aparece contenido nuevo en la página. No intenta extraer ofertas de ella.

## Desactivar una fuente

En `config.yaml`, bloque `sources:`, cambia `enabled` a `false`:

```yaml
sources:
  linkedin: {enabled: false}
  remotive: {enabled: true, min_interval_hours: 6}
```

Para comprobar qué fuentes hay configuradas y cuándo se ejecutaron por última vez: `jobradar sources`.

## Ritmo y respeto a las webs

- Entre peticiones al mismo dominio hay una pausa aleatoria de 1 a 3 segundos (`http.delay_seconds`).
- Cada fuente puede tener su propio intervalo mínimo entre consultas (`min_interval_hours`).
- Si una web responde 403 o 429 (bloqueo o demasiadas peticiones), JobRadar pausa esa fuente hasta el siguiente
  escaneo y lo muestra en `/estado`. No intenta saltarse el bloqueo.

## Para desarrolladores

### Contrato de las fuentes

Cada fuente es un módulo de `src/jobradar/sources/` que expone `FETCHERS`. Este es el contrato, copiado del docstring
de `src/jobradar/sources/__init__.py`:

```
Contrato: cada módulo de este paquete expone ``FETCHERS: dict[str, Fetcher]``, donde la clave es el nombre de la
fuente en ``config.yaml`` (``sources:``) y el valor es ``async def fetch(ctx: SourceContext) -> list[JobOffer]``.

- Usa siempre ``ctx.http`` (ritmo por dominio y SourceBlocked ya incluidos) y ``build_offer(expected_domains=...)``.
- No filtres por tipo/área en la fuente: eso lo hace ``filters.evaluate``. Sí puedes usar ``ctx.terms`` y
  ``ctx.locations`` como parámetros de búsqueda del portal para traer menos.
- Deja que ``SourceBlocked`` y los errores de red se propaguen: ``radar`` los aísla por fuente.
```

`SourceContext` contiene `http`, `settings`, `terms`, `locations` y `env`. Para leer las opciones de la fuente en
`config.yaml`, usa `ctx.options(nombre)`.

Para añadir una fuente nueva:

1. Escribe el módulo en `src/jobradar/sources/` y exporta `FETCHERS`.
2. Regístralo en `all_fetchers()` de `src/jobradar/sources/__init__.py`, en la lista de módulos.
3. Añade un fixture recortado de una respuesta real en `tests/sources/`.
4. Añade un test de contrato que compruebe, campo a campo, el título, la empresa, la URL, la ubicación y la fecha de
   ofertas concretas del fixture.
5. Ejecuta `pytest -q` y `jobradar verificar` antes de abrir un pull request.
