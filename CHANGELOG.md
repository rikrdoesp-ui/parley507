# Changelog

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
