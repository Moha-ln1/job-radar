# Tutorial de JobRadar

Esta guía parte de cero: no hace falta saber programar. Tarda unos 20 minutos.

## 1. Instalar Python y git

- **Python 3.10 o superior**: descárgalo de <https://www.python.org/downloads/>. En Windows, en la primera pantalla
  marca la casilla **Add python.exe to PATH** antes de pulsar Install.
- **git**: descárgalo de <https://git-scm.com/downloads>. Con las opciones por defecto basta.

Para comprobar que están instalados, abre una terminal (en Windows, PowerShell) y escribe:

```
python --version
git --version
```

En Windows, si `python --version` abre la Microsoft Store o no responde, prueba `py --version`: el instalador
usa cualquiera de los dos. Si ninguno responde, vuelve a instalar Python marcando **Add python.exe to PATH**.

## 2. Descargar JobRadar

En la terminal, dentro de la carpeta donde quieras guardarlo:

```
git clone https://github.com/Moha-ln1/job-radar.git
cd job-radar
```

## 3. Crear tu bot de Telegram

JobRadar te avisa a través de un bot que creas tú. Solo tienes que hacerlo una vez.

1. En Telegram, busca **@BotFather** (la cuenta oficial de Telegram para crear bots) y ábrela.
2. Escribe `/newbot`.
3. Te pedirá un **nombre** (cualquiera, p. ej. `Mi JobRadar`).
4. Te pedirá un **usuario**, que debe terminar en `bot` (p. ej. `mi_jobradar_bot`).
5. BotFather te responderá con un **token**: una cadena larga de números y letras. Cópialo entero. Es una contraseña:
   no la compartas.

El token se pedirá durante la instalación. No necesitas escribirle nada al bot: el instalador te mostrará un código QR.

## 4. Ejecutar el instalador

**Windows** (dentro de la carpeta `job-radar`):

```
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

**Linux / macOS**:

```
bash scripts/setup.sh
```

El instalador tiene 8 pasos. Esto es lo que hace y lo que te pregunta:

| Paso | Qué hace | Qué te pregunta |
|---|---|---|
| 1. Python | Comprueba que tienes Python 3.10 o superior. | Nada. |
| 2. Entorno e instalación | Crea la carpeta `.venv` e instala JobRadar. | Nada. |
| 3. Configuración | Crea `config.yaml` y `.env` a partir de los ejemplos, si no existen. | Nada. |
| 4. Telegram | Guarda el token del bot. | Pide el **token** (no se ve al pegarlo). Después muestra un **código QR**: escanéalo con la cámara del móvil, se abre tu bot en Telegram y pulsas **Iniciar**. El instalador lo detecta solo (sin escribir nada ni volver a la terminal), guarda tu chat y te envía un mensaje de confirmación. |
| 5. Claves opcionales | Permite añadir claves de InfoJobs, Adzuna y Jooble. | Si quieres añadirlas (`s/N`). Son opcionales: sin ellas se usan las webs públicas. Ver [APIS.md](APIS.md). |
| 6. Búsquedas | Si no tienes búsquedas, abre el asistente para crear la primera. | Las preguntas del asistente (ver la siguiente sección). |
| 7. Base de datos | Crea la base de datos. La primera vez marca como vistas las ofertas actuales para no recibir avisos de ofertas antiguas. | Nada. |
| 8. Arranque automático | Puede arrancar JobRadar al iniciar sesión en Windows. | Si quieres que arranque automáticamente (`S/n`). |

Si en algún paso no sabes qué responder, pulsa Enter: las opciones con mayúscula son las recomendadas.

Cuando termine, verás la lista de comandos útiles. Puedes ejecutarlo de nuevo en cualquier momento.

## 5. Primer uso del bot

Abre tu bot en Telegram y escribe `/busquedas`. Pulsa **➕ Nueva búsqueda** y responde a los **5 pasos** con los
botones:

1. **Tipo**: prácticas, trainee, bootcamp/academy, junior...
2. **Área**: desarrollo, datos, diseño, marketing...
3. **Modalidad**: presencial, híbrido, remoto o cualquiera.
4. **Ubicación**: la ciudad o región donde buscas (solo se aplica a presencial e híbrido).
5. **Avisos**: 🔥 al momento (en cuanto aparece una oferta) o 📰 resumen diario.

Al final pulsa **Guardar**. JobRadar aplicará la búsqueda también a las ofertas de los últimos 14 días y te dirá
cuántas encajan.

Puedes tener varias búsquedas. Puedes editarlas, pausarlas o borrarlas desde `/busquedas`.

## 6. Resto de comandos del bot

| Comando | Para qué sirve |
|---|---|
| `/busquedas` | Crear, editar, pausar o borrar búsquedas. |
| `/excluir` | Añadir palabras o empresas que nunca quieres ver. |
| `/fuentes` | Activar o desactivar cada fuente (LinkedIn, InfoJobs, portales de remoto...). |
| `/empresas` | Añadir la web de empleo de una empresa pegando su enlace, o quitarla. |
| `/paginas` | Vigilar la página de una academia o programa: te aviso cuando aparece un enlace nuevo. |
| `/descartadas` | Ver las ofertas descartadas en las últimas 24 h, agrupadas por motivo. |
| `/probar <texto>` | Comprobar si un título encaja con tus búsquedas. Ejemplo: `/probar Prácticas de marketing en Madrid`. |
| `/recientes` | Ver las ofertas que encajan encontradas últimamente. |
| `/estado` | Ver el estado de cada fuente y si alguna está bloqueada. |
| `/silencio` | Silenciar los avisos durante un tiempo. |
| `/escanear` | Buscar ofertas ahora, sin esperar al siguiente escaneo. |
| `/ayuda` | Ver la lista de comandos. |

El bot solo responde al chat de Telegram que configuraste durante la instalación.

No hace falta editar ningún archivo: lo que cambias con `/fuentes`, `/empresas` y `/paginas` se guarda en
`ajustes_bot.yaml` y tiene prioridad sobre `config.yaml`.

**Cómo se clasifican las ofertas.** Cada opción busca sus sinónimos en español e inglés en el título (y la
categoría, si el portal la da), con plurales, femeninos y marcas como "Técnico/a". Si el título no indica el área
(por ejemplo "Estudiante en prácticas – Departamento TEF7"), la oferta no se descarta: te llega en el resumen
diario, para que no se pierda.

## 7. Botones de cada aviso

Cada aviso trae botones:

- **🚫 Ocultar empresa**: no volverás a recibir ofertas de esa empresa.
- **👎 No me interesa**: descarta esa oferta.

Si una misma oferta aparece en varios portales, recibes **un solo aviso con los enlaces de todos**. Si más tarde
aparece en otro portal, el aviso original se actualiza y el bot te responde con "➕ También en …".

En `/descartadas`, cada oferta trae el botón **➕ Era buena**: te la envía, te pregunta qué palabra del título
debería haberla encontrado y la añade a los sinónimos, para que las siguientes parecidas no se pierdan.

## 8. Cómo funcionan los filtros

- **Dentro de un campo basta con una opción (O)**. Por ejemplo, "Prácticas" o "Trainee".
- **Entre campos se exigen todos (Y)**. Por ejemplo, tipo "Prácticas" y ubicación "Granada".
- **Entre búsquedas basta con una (O)**. Si una búsqueda encaja, recibes el aviso.
- **Las exclusiones ganan**: si el título de una oferta contiene una palabra excluida, no se avisa. La excepción es
  que el título contenga también el tipo buscado (p. ej. "Junior/Senior Developer"): en ese caso se incluye.
- **Ante la duda, se incluye**. Si falta la modalidad, la ubicación o la fecha, la oferta pasa el filtro. Es
  preferible recibir una oferta de más a perder una buena.
- **Sinónimos en español e inglés**: "prácticas" encuentra también "internship", "intern" o "becario/a".
  No distingue mayúsculas ni tildes.
- **Revisión**: si una oferta buena se ha descartado, `/descartadas` te deja añadir su término a la búsqueda.

## 9. Comandos de terminal útiles

Ejecútalos desde la carpeta `job-radar`. En Windows puedes usar `.venv\Scripts\jobradar.exe` o activar el entorno
virtual; en Linux/macOS, `source .venv/bin/activate`.

| Comando | Para qué sirve |
|---|---|
| `jobradar run` | Arranca el bot y los escaneos automáticos. |
| `jobradar stop` | Para JobRadar. |
| `jobradar status` | Muestra el estado actual. |
| `jobradar scan` | Escanea las fuentes ahora y envía los avisos. |
| `jobradar scan --dry-run` | Prueba un escaneo sin guardar nada ni enviar avisos. |
| `jobradar scan --only <fuentes>` | Escanea solo algunas fuentes, separadas por comas. |
| `jobradar configurar` | Abre el asistente para crear una búsqueda. |
| `jobradar filtros explicar` | Describe las búsquedas activas. |
| `jobradar filtros probar <texto>` | Evalúa si un título encaja con tus búsquedas. |
| `jobradar recent` | Ofertas que encajan encontradas últimamente. |
| `jobradar descartadas` | Ofertas descartadas, agrupadas por motivo. |
| `jobradar sources` | Fuentes configuradas y su última ejecución. |
| `jobradar verificar` | Comprueba que los datos extraídos coinciden con las páginas reales. |
| `jobradar digest` | Envía ahora el resumen de pendientes. |
| `jobradar telegram test` | Envía un mensaje de prueba a tu chat. |
| `jobradar ats detect <url> --add` | Añade la web de empleo de una empresa. |
| `jobradar autostart on\|off\|status` | Activa, desactiva o consulta el arranque automático. |
| `jobradar --help` | Muestra todos los comandos. |

## 10. Arrancar y parar

- **Arrancar**: `jobradar run`. Deja la ventana abierta mientras quieras que funcione, o usa el arranque automático.
- **Parar**: `jobradar stop`.
- **Estado**: `jobradar status`.
- **Arranque automático**: `jobradar autostart on` para que arranque al iniciar sesión (Windows, Linux o macOS), y
  `jobradar autostart off` para desactivarlo. `jobradar autostart status` muestra si está activo.

**El PC debe estar encendido** para que JobRadar busque ofertas. Si lo apagas, al volver a encenderlo recupera el
escaneo atrasado.

## 11. Solución de problemas

**En `/estado` aparece una fuente en pausa ("nos ha bloqueado; descansa hasta…").** La web ha detectado demasiadas
peticiones (403, 429 o una página anti-bot). JobRadar deja de consultarla un tiempo para no saturarla: 6 h tras el
primer bloqueo y el doble con cada bloqueo seguido, hasta 48 h. Cuando vuelve a responder bien, todo vuelve a la
normalidad solo. No hace falta hacer nada. Si una fuente se bloquea siempre, usa su API oficial si existe (ver
[APIS.md](APIS.md)) o desactívala (ver [FUENTES.md](FUENTES.md)). Las demás fuentes siguen funcionando mientras tanto.

**El primer día no llega ningún aviso.** Es normal: el primer escaneo marca como vistas las ofertas que ya existían,
para no enviarte cientos de golpe. Desde entonces solo recibes las nuevas. Para ver lo que ya hay que encaja con una
búsqueda, guárdala desde `/busquedas`: el bot te dice cuántas ofertas guardadas encajan y te las enseña.

**El QR no se ve bien en la terminal.** Abre el enlace que aparece justo debajo del QR (empieza por `https://t.me/`), en el móvil o en el ordenador, y pulsa **Iniciar**. También puedes repetirlo con `jobradar telegram link`.

**No llegan avisos al móvil.** Comprueba que el bot está activo con `jobradar telegram test`. Si no llega el mensaje
de prueba, repite `jobradar telegram link` (o, a mano, `jobradar telegram chat-id --save` después de escribir `/start` a tu bot). Después ejecuta
`jobradar verificar` para comprobar que las fuentes extraen bien los datos.

**Quiero saber por qué no ha llegado una oferta.** Usa `/descartadas` en el bot o `jobradar descartadas` en la terminal.
Ahí aparece el motivo exacto de cada descarte.

## 12. Actualizar JobRadar

Dentro de la carpeta `job-radar`:

```
git pull
```

Después vuelve a ejecutar el instalador (`scripts\setup.ps1` en Windows, `scripts/setup.sh` en Linux/macOS). Es
idempotente: no borra tus búsquedas, tu token ni tu base de datos.
