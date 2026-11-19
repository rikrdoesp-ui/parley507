# Changelog

## v0.1.29 — 2026-11-19

- Parley: un leg necesita además VE no negativo a la cuota de Stake. El 18-nov los 19 escalones tenían VE de −2 % a
  −35 %: el leg más probable suele ser la línea alterna con más margen (cuota 1.28-1.30).
- Parley: de cada escenario se guarda y califica un solo escalón (★ en la escalera), el más corto con cuota x3 o más
  y hasta 4 legs. Los escalones comparten sus primeros legs; el 18-nov Dort U13.5 → 16 tumbó los 19 a la vez.

## v0.1.28 — 2026-11-16

- Líneas alternas de Stake (la flecha junto a la línea): `/parley` las lee con `scripts/escaner_lineas.js` y la app
  usa todas. La principal de cada jugador y mercado es la más pareja sin margen; las fichas, Props y el acierto de
  Resultados siguen con la principal. De Stake solo cuenta la última lectura del día.
- Parley con los dos escenarios: **1 prop por juego** (el más probable de cada partido entre todas sus líneas y la
  escalera de 2 legs en adelante) y **2 props por juego** (el mejor par de cada partido y la escalera por número
  de partidos). Reemplazan a los parleys de 2 y 3 legs de un solo partido.
- Probabilidad conjunta del mismo juego con la correlación histórica entre jugadores (se ajusta en el backtest).
  Resultó pequeña: 0,07 entre asistencias y puntos de compañeros y menos de 0,03 en el resto.
- Ficha del jugador: la línea "Segura" de cada mercado y el destacado "Más segura" ya son líneas reales de Stake
  con su cuota (la más probable entre sus alternas); sin alternas se sigue mostrando la del modelo, marcada como tal.
  Junto al nombre sale el dorsal (PlayerIndex de la NBA, una vez al día).
- Resultados: aciertos por escenario y la tabla "¿Cumplen lo que dicen?", que compara por tramo de probabilidad lo
  que cumplió el lado favorito de cada línea de Stake con lo esperado.

## v0.1.27 — 2026-11-16

- Capa de regresión sobre la media (modelo nba-min-tasa-nb-0.4): minutos × tasa se pasaba con los jugadores de
  media alta y se quedaba corto con los de media baja. La capa combina esa media con los últimos 4 partidos, la
  media por partido, la tasa larga (40 partidos), el L10 y la tendencia de minutos; los pesos se ajustan en el
  backtest solo con partidos anteriores. El Brier baja en las 6 áreas y las 2 temporadas (puntos 0,2438 a 0,2408 en
  2025-26 y 0,2345 a 0,2327 en 2026-27; PRA 0,2440 a 0,2410 y 0,2350 a 0,2326). El error medio baja en 2026-27
  (PRA 6,41 a 6,35) y sube un poco en 2025-26 (6,07 a 6,10), donde la capa solo tuvo una temporada para ajustarse.
- Probado y descartado: defensa del rival, ritmo, descanso, localía, spread y volumen de tiro (menos de 0,001 de
  Brier y no en las dos temporadas); gradient boosting con las mismas variables (igual que la capa); dispersión por
  máxima verosimilitud (igual que por momentos).
- Contra las 225 líneas de Stake del 15-11 el modelo solo sigue por debajo del mercado: Brier 0,2654 a 0,2631, mercado
  0,2501; lado acertado 51 % antes y después. Es un solo día.

## v0.1.26 — 2026-11-16

- Jugadores: separados por partido y, dentro, por equipo (en PC los dos equipos lado a lado).
- Cada ficha sugiere el prop "Más probable" del jugador: el de mayor probabilidad entre sus líneas de Stake, con
  cuota, cuántas veces cumplió en sus últimos 10 y VE; sin Stake, el de su línea de referencia, marcado como tal.

## v0.1.25 — 2026-11-16

- Resultados: "Parleys sugeridos" muestra los de días ya jugados (por fecha) con el valor real de cada leg; los de
  hoy quedan en la pestaña Parley hasta que terminen. Los propuestos con el partido ya empezado se marcan y se
  cuentan aparte, no en el registro. Se cargaron los 10 del 15-11: ganaron 2 (SAS @ UTA, de 2 y de 3 legs); por su
  probabilidad se esperaban 3,1.
- Si el commit de la página falla (PC recién despierta), se reintenta una vez.

## v0.1.24 — 2026-11-15

- Tocar la foto del jugador la abre en grande (1040x760 de la NBA) con su nombre y partido; se cierra con la X,
  tocando fuera o con Esc. En el celular ocupa casi todo el ancho.

## v0.1.23 — 2026-11-15

- Alineaciones de RotoWire en cada actualización (solo los partidos del calendario del día). La ficha dice
  "Titular confirmado", "Titular esperado" o "Suplente". Si el reporte oficial no trae estado de un jugador, se usa
  el de RotoWire (Out, OFS y suspendido = Out; GTD = Questionable; Doubt = Doubtful): el modelo reparte sus minutos y
  Parley lo descarta. Las proyecciones lo anotan como "estado según RotoWire".
- Foto oficial de la NBA junto al nombre (cdn.nba.com; si no carga, no deja hueco).

## v0.1.22 — 2026-11-15

- En PC (1100 px o más) la página usa el ancho: hasta 1320 px, jugadores, props, parleys, resultados por partido y
  modelo en 2 columnas, y partidos y lesiones en 3. En el celular no cambia.
- Props: ahora también muestra las áreas de PRA, PR y RA cuando hay línea.

## v0.1.21 — 2026-11-15

- Corrección: el game log de la NBA trae box scores parciales de los partidos en juego, y la app los trataba como
  terminados (ATL @ MIL tenía 372 de 480 minutos y OKC @ SAC 204). Ahora el historial del modelo, la calificación
  de props y la de parleys usan solo partidos con estado final; lo que está en juego queda pendiente.
- Con eso cambian las cifras del 15-11: props con línea 81 de 167 (48 %, no 54 %); parleys revisados a mano 2 de 7
  decididos (se esperaban 2,2), ATL @ MIL y OKC @ SAC pendientes. Los titulares de 32+ min quedaron 2,4 PRA bajo lo
  proyectado, no 6. Las mejoras de v0.1.18 no cambian: salieron del backtest, que usa temporadas completas.
- Stake aún no publica props del 16-11; se leen cuando aparezcan.

## v0.1.20 — 2026-11-15

- Ficha del jugador: columna "Prop real" con la línea de Stake y su cuota en el lado más probable (o "Sin Stake"),
  y debajo la línea segura del modelo: la más exigente que todavía da 75 % o más, para buscarla entre las
  alternativas de Stake (solo modelo, sin mercado). En pantallas de menos de 420 px se oculta la columna Temp.

## v0.1.19 — 2026-11-15

- Parleys propuestos: se guardan los de partidos que aún no empiezan (la última versión antes del inicio) y se
  califican solos con el box score. En Resultados: cuántos ganaron contra cuántos se esperaban por su probabilidad.
  Lo propuesto con el partido ya empezado no cuenta.
- Revisión de los parleys del 15-11 (propuestos con los partidos ya empezados, así que no cuentan en el registro):
  ganaron 2 de 10 (SAS @ UTA, de 2 y de 3 legs); por probabilidad se esperaban 3,1. Legs: 9 de 16.
- Textos: nota de Parley corta con "Cómo se eligen" plegable; avisos sin mayúsculas; mensajes vacíos que dicen
  cuándo se llenan; VE y Brier explicados.
- Revisión de código: minutos desconocidos toman la dispersión más prudente; el backtest de bajas usa la dispersión
  de los minutos ajustados, como en producción (ahora elige repartir 25 % de los minutos del ausente).

## v0.1.18 — 2026-11-15

Mejoras tras revisar los resultados del 15-11 y confirmarlas en el backtest (30 mil partidos de 2025-26 y 2026-27):
- Dispersión según minutos proyectados (6 tramos). Con una sola k, un suplente parecía tan predecible como un
  titular: los rangos 10-90 atrapaban 63 % en suplentes y 88 % en titulares. Ahora la cobertura queda cerca de 80 %
  (puntos 2026-27: 73 % a 80 %) y mejora la probabilidad en líneas bajas como AST over 0.5 (Brier 0,220 a 0,214).
- Sesgo aprendido con todos los partidos de la temporada, no solo con las proyecciones guardadas de la app. En
  2026-27 el modelo proyectaba ~8 % de más; el factor (mitad del efecto a 1500 casos, tope ±10 %) bajó el error medio
  en las dos temporadas (puntos 4,84 a 4,76; PRA 6,41 a 6,30). Hoy: puntos ×0,937, rebotes ×0,961, asistencias ×0,945.
- Probado y descartado: recortar minutos a titulares por paliza (en el historial pierden 1,5 min y 0,25 PRA más que
  en un partido parejo; el 15-11 fue un día raro) y corregir por tramo de minutos (empeora el error medio).
- Modelo nba-min-tasa-nb-0.3.

## v0.1.17 — 2026-11-15

- Mercados combinados PRA (puntos+rebotes+asistencias), PR y RA. La media es la suma de las partes (con las bajas,
  el uso y la corrección por resultados ya aplicados); la dispersión se ajusta aparte en el backtest. En el backtest
  también le ganan al promedio L10 (PRA 2026-27: Brier 0,235 contra 0,251). Modelo nba-min-tasa-nb-0.2.
- Salen en la ficha de cada jugador, en Props y en Parley cuando hay línea de Stake, en Resultados y en el export a
  /parley (claves `pra`, `pr`, `ra`, las mismas que usa el skill). Sin línea de Stake se muestran con línea de
  referencia (*).

## v0.1.16 — 2026-11-15

- Resultados: se ven por partido (bloques plegables con "30 de 39" acertadas) o todas de mayor a menor
  probabilidad; la página recuerda la elección. Ahora entran todas las props calificadas, no solo 40.

## v0.1.15 — 2026-11-15

- Pestaña Parley: por partido, el parley de 2 y de 3 legs más probable con líneas y precio de Stake, cada leg con
  su justificación (proyección contra línea, cumplimiento en los últimos 10, promedios L5 y L10, minutos, mercado
  sin margen y probabilidad con el modelo). Filtros: sin duda ni baja, 20+ minutos estables, muestra suficiente,
  6 de 10 o más, 55 % o más, sin overs con riesgo de paliza, un leg por jugador y máximo 2 por equipo. Muestra la
  probabilidad conjunta, la cuota de Stake, la cuota justa y el VE. BET o PASS los sigue decidiendo /parley.
- Pestaña Resultados aparte: si se dieron o no las props. En Modelo queda solo la corrección por sesgo.

## v0.1.14 — 2026-11-15

- Actualización automática: tarea de Windows "Parley507 actualizar" cada 30 min de 10:00 a 01:00, sin ventana
  (`tools/instalar_tarea.ps1`; registro en `~/sports-data/actualizar_auto.log`). Necesita la PC encendida y la sesión
  iniciada.
- Página: botón Recargar (se salta la caché de GitHub Pages) y "hace X min" junto a la hora de actualización.

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
