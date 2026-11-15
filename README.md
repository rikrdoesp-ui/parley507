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
3. **Media:** minutos × tasa. **Distribución:** binomial negativa; su dispersión `k` se ajusta en el backtest con
   datos anteriores al periodo evaluado.
4. **Bajas (efecto de uso):** Out no juega. Por cada baja nueva de rotación, sus compañeros reciben una parte de la
   producción que deja (alfa) en proporción a lo que ya producen, y opcionalmente una fracción de sus minutos. Ambos
   valores los elige el backtest con los partidos históricos en que faltó alguien: hoy fracción de minutos 0 y alfa
   0.25 (repartir todos los minutos empeoraba el error). Tope: +35 % de la media por uso, +8 minutos, 40 minutos.
   Questionable/Doubtful: escenario base "juega" y un escenario "sin X" para sus compañeros.
5. Menos de 5 partidos previos = "muestra insuficiente", sin proyección.

Limitaciones conocidas: el efecto de uso es un promedio y se queda corto cuando faltan varios del mismo puesto; no modela rival, ritmo, descanso, blowout ni cambios
de equipo; la titularidad histórica es desconocida (NULL). Solo temporada regular: en playoffs no hay box scores
nuevos, así que desde la segunda ronda no habrá proyecciones hasta añadir ese tipo de temporada.

## Overtime

Se guardan estadísticas totales y, para partidos con OT, las del tiempo reglamentario
(`nba_player_game_stats_regulation`). Falta confirmar con Stake cuál usa para liquidar props de baloncesto.
