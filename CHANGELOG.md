# Changelog

## v0.1.13 — 2026-11-15

- Resultados: cada actualización califica las proyecciones de los días ya jugados contra el box score (la última
  hecha antes del partido) y contra las líneas guardadas (acierto del lado más probable, Brier del modelo y del
  mercado). Se ve en la pestaña Modelo de la página y en Hoy de la app.
- Aprendizaje: por estadística se calcula cuánto se queda corto o se pasa el modelo y las proyecciones nuevas se
  corrigen con ese factor, encogido hacia 1 con poca muestra (mitad del efecto a las 1500 proyecciones) y con tope
  de ±10 %. Se descuenta el factor que ya estaba aplicado, para no corregir dos veces.
- El backtest (dispersión, ajuste por bajas y legs reales de /parley) se rehace cada 7 días, no solo la primera vez.
- Botón "Actualizar datos" con barra de porcentaje.
- Un box score de prórroga que aún no publica la NBA ya no detiene la actualización: se reintenta la próxima vez.

## v0.1.12 — 2026-11-15

- Prueba como celular (Android emulado, 375 px, toques): sin desborde, letra mínima 13 px, partidos y apartados
  plegables de 58 px o más, "atrás" funciona; manifiesto e íconos válidos para instalar en Android e iPhone.
- Pestañas de 42 a 48 px de alto, como recomiendan Google y Apple para el dedo.
- Los partidos se leen bien con lector de pantalla ("IND visita a PHI, 13:00 hora de Panamá").

## v0.1.11 — 2026-11-15

- Las direcciones del ícono de pestaña, el de iPhone y el manifiesto llevan la versión (`?v=`), para que el
  navegador descargue el logo nuevo en lugar del que tenía en caché.

## v0.1.10 — 2026-11-15

- Logo cambiado al boleto de parley (la opción elegida): muescas, línea de corte, talón con punto verde y el 507
  en dígitos de marcador con los colores de Panamá (5 azul, 0 azul noche, 7 rojo; el blanco es el boleto).
  Los dígitos son polígonos, no texto, para que el ícono de la pestaña y los PNG se vean igual sin fuentes web.

## v0.1.9 — 2026-11-15

- Logo nuevo, elegido entre cinco opciones: una P cuyo tallo es la barra de probabilidad y cuya panza es un balón.
- "507" con los colores de la bandera de Panamá: 5 azul, 0 blanco (delineado en modo claro), 7 rojo.
- Íconos de pestaña y pantalla de inicio regenerados con el logo nuevo.

## v0.1.8 — 2026-11-15

- Logo: la trayectoria de un tiro en puntos, el balón y la barra de probabilidad de la página
  (`src/psa/marca.py`, una sola geometría para la cabecera, la pestaña y los PNG).
- Nombre: "parley" en Barlow Condensed negra inclinada y "507" en números delineados, como un dorsal.
- Ícono de pestaña, ícono para iPhone y manifiesto web: la página se puede agregar a la pantalla de inicio.
  Los íconos se regeneran con `uv run --with pillow python tools/iconos.py`.

## v0.1.7 — 2026-11-15

- Spread estimado propio por partido (fuerza reciente de cada equipo + localía, solo con partidos anteriores):
  correlación 0,45 con el margen real. Se muestra el favorito en cada partido.
- Aviso de riesgo de paliza a titulares (28+ min) con spread estimado de 12 o más.
- Probado y descartado: quitar minutos a titulares según el spread. El efecto real es de ~1,4 min con spread 16+
  y no mejora el Brier en 2025-26 ni en 2026-27; el ancla al mercado ya recoge el spread de Stake.

## v0.1.6 — 2026-11-15

- Rediseño de la página del celular: tema de arena (concreto y tinta azul noche, over en verde duela, under en
  azul), Barlow Condensed para partidos y cifras, modo oscuro en azul marino.
- Barra de probabilidad en cada prop, con una marca donde está el mercado sin margen.
- Reloj de tiro: neutro, ámbar a 30 minutos o menos, naranja en juego.
- Tabla del jugador con el lado más probable, su VE y sus aciertos en los últimos 10.
- La plantilla pasa a `src/psa/pagina.html`.

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
