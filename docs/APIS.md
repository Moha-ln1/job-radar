# Claves de las APIs oficiales

Son opcionales y gratuitas. Sin clave, esa fuente se desactiva sola (InfoJobs vuelve a leer su web pública).
Rellena los valores en tu archivo `.env` y reinicia JobRadar. Consulta los límites del plan gratuito en la web de cada servicio.

## InfoJobs
1. Entra en <https://developer.infojobs.net/> e inicia sesión con tu cuenta de InfoJobs.
2. Crea una aplicación (nombre y descripción libres).
3. Copia el *client id* y el *client secret* que te muestra.
4. En `.env`: `INFOJOBS_CLIENT_ID=` y `INFOJOBS_CLIENT_SECRET=`.

Si la clave no es válida (error 401), JobRadar avisa en el log y usa el HTML público.

## Adzuna
1. Regístrate en <https://developer.adzuna.com/>.
2. Tras el registro verás tu `app_id` y tu `app_key` en el panel.
3. En `.env`: `ADZUNA_APP_ID=` y `ADZUNA_APP_KEY=`.

## Jooble
1. Abre <https://jooble.org/api/about> y rellena el formulario de solicitud de clave.
2. Te llegará la clave por email.
3. En `.env`: `JOOBLE_API_KEY=`.
