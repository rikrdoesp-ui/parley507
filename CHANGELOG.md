# Changelog

## v0.1.5 — 2026-11-15

- Props en bloques plegables por partido (abierto el próximo en empezar) y, dentro, apartados plegables por área y
  lado (Puntos Over, Puntos Under, Rebotes, Asistencias), ordenados por probabilidad de salir, con cuota, VE y
  proyección en filas compactas.

## v0.1.4 — 2026-11-15

- Props agrupadas por partido, en orden de inicio, con la hora de Panamá.
- Cuenta regresiva hasta el inicio y, ya iniciado, minutos desde el comienzo (se actualiza cada 30 s), también en
  la lista de partidos y en cada juego.

## v0.1.3 — 2026-11-15

- La página del celular muestra la versión junto al nombre (tomada de `pyproject.toml`).

- Probabilidad anclada al mercado para edge y VE (`props.mezclar`): mercado sin margen + 25 % hacia el modelo, con los
  topes de /parley. Antes, 140 de 246 líneas de Stake salían con VE positivo por errores del modelo; con el ancla, 0.
- La página del celular muestra la mezcla con sus partes (mercado y modelo) y el VE, y avisa cuando ninguna línea
  tiene VE positivo.

## v0.1.2 — 2026-11-15

- Efecto de uso por bajas de rotación (`modelo.ajustar_ausencias`), con fracción de minutos y alfa elegidos por
  backtest sobre partidos históricos con ausencias. Resultado: alfa 0.25 sin mover minutos; el reparto completo de
  minutos que se usaba antes empeoraba el Brier y se retiró.
- Líneas de Stake desde `CODE/stake/lineas/FECHA.txt`, con VE; el consenso de BettingPros sigue como referencia.

## v0.1.1 — 2026-11-15

- Página estática para el celular (`index.html` en la raíz, GitHub Pages), regenerada y publicada en cada actualización.
- El cálculo de props pasa a `psa.nba.props`, compartido por la app y la página.

## v0.1 — 2026-11-15

Primera entrega: base + NBA de punta a punta.

- Esquema SQLite con fuente y hora de captura por dato; tabla única `player_props`; estadísticas con y sin OT.
- Conector NBA (`nba_api`): box scores de 3 temporadas, calendario, box score por periodos para partidos con OT,
  controles de calidad (minutos imposibles, partidos suspendidos).
- Lector del reporte oficial de lesiones (PDF) con corrección manual; escenarios para jugadores en duda.
- Modelo de minutos × tasa con binomial negativa; minutos manuales con razón.
- Backtest walk-forward (MAE, Brier en línea sintética, cobertura 10-90) y Brier contra los legs reales de `/parley`.
- App Streamlit: Hoy, NBA, Props (línea manual, edge, VE), Backtest.
- Export `CODE/stake/proyecciones/FECHA.json`; `/parley completar` lo agrega a cada prop en el campo `proyeccion`
  (informativo, no cambia `evaluar`).
