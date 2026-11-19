# parley507 — Panama Sports Analytics

Analiza los mercados para hacer el mejor parley.

Proyecciones propias de player props NBA que alimentan a la skill `/parley`. Uso personal.
Especificación: `PANAMA_FOOTBALL_ANALYTICS_PRO_MASTER_SPEC.md` (v1.1, en Descargas). Esta es la **v0.1**: base + NBA.
NFL llega en v0.2 y Panamá en v0.3.

La app **no** decide apuestas: muestra proyección, probabilidad, edge y VE por leg. BET / PASS, montos y topes los
decide `/parley`. Su proyección es informativa hasta que, con 100 legs reales o más, tenga mejor Brier que la mezcla
actual de `/parley` (ver página Backtest).

## Comandos (PowerShell o Git Bash, en esta carpeta)

```bash
uv sync
```

```bash
uv run actualizar
```

```bash
uv run streamlit run app.py
```

```bash
uv run backtest
```

```bash
uv run pytest
```

- `actualizar`: descarga box scores (temporada actual y 2 anteriores; las cerradas solo la primera vez), calendario,
  estadísticas sin prórroga de partidos con OT, el último reporte oficial de lesiones; proyecta el día y escribe
  `CODE/stake/proyecciones/FECHA.json`. Opciones: `--fecha 2026-11-20`, `--sin-ot`. La primera vez tarda varios minutos.
- La app hace lo mismo con el botón **Actualizar datos** (página Hoy). **Recalcular proyecciones** aplica correcciones
  manuales sin descargar.
- `backtest`: walk-forward y comparación con los legs reales de `/parley`; guarda la dispersión que usan las proyecciones.

## Página para el celular

`actualizar` (y los botones de la página Hoy) generan `index.html` (raíz del repositorio) y lo suben a GitHub, que lo publica con
GitHub Pages en https://rikrdoesp-ui.github.io/parley507/. Es una foto de solo lectura de la última actualización:
partidos, proyecciones por jugador, líneas, lesiones y backtest. El repositorio es público, así que la página también.
Para no subirla: `uv run actualizar --sin-publicar`.
Para tenerla como app en el celular: ábrela en el navegador y usa "Agregar a pantalla de inicio" (Android) o
Compartir → "Agregar a inicio" (iPhone). El logo vive en `src/psa/marca.py`; si cambia, regenera los íconos con
`uv run --with pillow python tools/iconos.py`.

## Dónde están los datos

| Qué | Dónde |
|---|---|
| Base SQLite | `C:\Users\rikrd\sports-data\psa.sqlite` (fuera de OneDrive; cambiar con `PSA_DATOS`) |
| Carpeta de `/parley` | `CODE/stake` (cambiar con `PARLEY_DATOS`) |
| Proyecciones exportadas | `CODE/stake/proyecciones/FECHA.json` |
| Referencias leídas | `CODE/stake/referencias/FECHA.txt` (consenso BettingPros que guarda `/parley`) |

## Fuentes y límites

| Fuente | Uso | Límite conocido |
|---|---|---|
| stats.nba.com vía `nba_api` | Box scores, calendario, box score por periodos | No es API pública documentada; puede bloquear o ir lento. Pausa de 0.7 s entre llamadas y reintentos. |
| Reporte oficial de lesiones (PDF) | Estado de jugadores | Se lee por posición de columnas. Si el formato cambia, la app avisa y se corrige a mano. |
| `/parley` (`CODE/stake`) | Líneas de referencia y legs reales | El consenso de BettingPros es referencia sin margen, no precio de Stake: no tiene VE. |

Dato faltante = vacío, nunca cero. Cada fila guarda su fuente y hora de captura (`data_sources`).

## Modelo NBA v0.1

1. **Minutos:** media exponencial de los partidos jugados (vida media 4 partidos). Ajustables a mano con razón.
2. **Tasa:** estadística por minuto, media exponencial más larga (vida media 12 partidos).
3. **Media:** minutos × tasa, pasada por una capa de regresión que la combina con otras lecturas del mismo jugador
   (últimos 4 partidos, media por partido, tasa larga de 40 partidos, L10) y con la tendencia de sus minutos. Los
   pesos salen por mínimos cuadrados en el backtest, solo con partidos anteriores. Corrige la regresión a la media:
   baja a los de media alta y sube a los de media baja. **Distribución:** binomial negativa; su dispersión `k` se ajusta en el backtest con
   datos anteriores al periodo evaluado.
4. **Bajas (efecto de uso):** Out no juega. Por cada baja nueva de rotación, sus compañeros reciben una parte de la
   producción que deja (alfa) en proporción a lo que ya producen, y opcionalmente una fracción de sus minutos. Ambos
   valores los elige el backtest con los partidos históricos en que faltó alguien: hoy fracción de minutos 0 y alfa
   0.25 (repartir todos los minutos empeoraba el error). Tope: +35 % de la media por uso, +8 minutos, 40 minutos.
   Questionable/Doubtful: escenario base "juega" y un escenario "sin X" para sus compañeros.
5. **Ancla al mercado:** con línea real, edge y VE no usan la probabilidad del modelo sola. Parten del mercado sin
   margen y el modelo la mueve un 25 % del camino, con tope de 4 puntos (dos lados de una casa), 3 (consenso) o 5
   (una sola cuota), como en /parley. El peso se recalibrará con 100 legs comparables. La del modelo se sigue mostrando.
6. Menos de 5 partidos previos = "muestra insuficiente", sin proyección.

Parleys del día (pestaña Parley): con todas las líneas de Stake, alternas incluidas (las lee `/parley` con
`scripts/escaner_lineas.js` y quedan en `CODE/stake/lineas/FECHA.txt`), la página arma dos escenarios. **1 prop por
juego:** el leg más probable de cada partido y la escalera de 2 legs en adelante. **2 props por juego:** el mejor
par de cada partido y la escalera por número de partidos. Un leg entra con 55 % o más, VE no negativo a la cuota de
Stake, jugador confirmado, 20+ minutos estables y 6 de 10 a esa línea. De cada escenario se guarda y califica un solo
escalón (★): el más corto con cuota x3 o más y hasta 4 legs, como el ticket seguro de `/parley`; los escalones
comparten sus primeros legs y contarlos todos multiplicaba un mismo fallo (18-nov-2026: Dort U13.5 tumbó los 19). Se
guarda antes de que empiece su primer partido; Resultados muestra el acierto por escenario y si cada tramo de
probabilidad cumple lo que dice.

Spread y palizas: cada partido muestra un spread estimado propio y los titulares de partidos con spread de 12 o más
llevan un aviso de riesgo de paliza. No se les quitan minutos: se probó en el backtest y no mejoraba.

Limitaciones conocidas: el efecto de uso es un promedio y se queda corto cuando faltan varios del mismo puesto; no
modela rival, ritmo ni descanso (probados el 16-nov-2026: suman menos de 0,001 de Brier), ni blowout ni cambios de
equipo. Con box scores el modelo solo no le gana a las líneas reales (15-nov: Brier 0,263 contra 0,250 del mercado
en 225 líneas de Stake); por eso edge y VE usan el ancla al mercado; la titularidad histórica es desconocida (NULL). Solo temporada regular: en playoffs no hay box scores
nuevos, así que desde la segunda ronda no habrá proyecciones hasta añadir ese tipo de temporada.

## Overtime

Se guardan estadísticas totales y, para partidos con OT, las del tiempo reglamentario
(`nba_player_game_stats_regulation`). Falta confirmar con Stake cuál usa para liquidar props de baloncesto.
