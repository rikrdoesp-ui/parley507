# Changelog

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
