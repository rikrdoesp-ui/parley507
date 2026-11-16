import pandas as pd
import streamlit as st

from psa import actualizar, config, ui
from psa.nba import resultados

st.title("Hoy")
fecha = ui.elegir_fecha()

col1, col2 = st.columns(2)
if col1.button("Actualizar datos", type="primary", help="Descarga box scores, calendario y lesiones; califica los días ya jugados y corrige el modelo; recalcula, exporta a /parley y publica la página del celular."):
    barra = st.progress(0, text="Empezando...")
    with st.status("Actualizando...", expanded=False) as estado:
        try:
            r = actualizar.actualizar(fecha, aviso=st.write,
                                      progreso=lambda pct, texto: barra.progress(pct / 100, text=f"{pct} %: {texto}"))
            estado.update(label="Actualización terminada", state="complete")
        except RuntimeError as error:
            estado.update(label="Falló la descarga", state="error")
            st.error(str(error))
            r = None
    if r:
        for a in r["avisos"]:
            st.warning(a)
        st.json({k: v for k, v in r.items() if k != "avisos"}, expanded=False)
if col2.button("Recalcular proyecciones", help="Sin descargar: aplica lesiones y minutos corregidos a mano y vuelve a publicar la página."):
    with ui.conexion() as con:
        r = actualizar.recalcular(con, fecha)
        actualizar.publicar_pagina(con, fecha, r)
    for a in r["avisos"]:
        st.warning(a)
    st.success(f"Proyecciones: {r.get('proyecciones', 0)} filas. Export: {r.get('export', 'no')}")
    st.info(r.get("publicacion", ""))

with ui.conexion() as con:
    juegos = pd.read_sql("""SELECT g.start_time_utc, a.abbreviation || ' @ ' || h.abbreviation AS partido, g.status,
                              g.away_score, g.home_score, g.overtime_periods, g.venue, g.season_type
                            FROM games g JOIN teams h ON h.team_id = g.home_team_id JOIN teams a ON a.team_id = g.away_team_id
                            WHERE g.game_date = ? ORDER BY g.start_time_utc""", con, params=(fecha,))
    fuentes = pd.read_sql("""SELECT provider AS fuente, MAX(captured_at) AS ultima_captura, COUNT(*) AS capturas
                             FROM data_sources GROUP BY provider""", con)
    lesiones = con.execute("""SELECT MAX(reported_at), COUNT(*) FROM nba_injuries WHERE game_date = ? AND entry_method = 'PDF'""",
                           (fecha,)).fetchone()
    manuales = con.execute("SELECT COUNT(*) FROM nba_injuries WHERE game_date = ? AND entry_method = 'MANUAL'", (fecha,)).fetchone()[0]
    modelo = con.execute("SELECT created_at FROM model_runs WHERE model_version = ? ORDER BY run_id DESC LIMIT 1", (config.MODELO_NBA,)).fetchone()
    alertas = pd.read_sql("""SELECT checked_at, severity AS severidad, table_name AS tabla, record_id AS registro, message AS mensaje
                             FROM data_quality_log ORDER BY quality_id DESC LIMIT 30""", con)

st.subheader(f"Partidos NBA del {fecha}")
if juegos.empty:
    st.info("Sin partidos en la base para esta fecha. Pulsa Actualizar datos.")
else:
    juegos.insert(0, "hora Panamá", juegos.pop("start_time_utc").map(ui.hora_panama))
    st.dataframe(juegos, hide_index=True, width="stretch")

c1, c2, c3 = st.columns(3)
c1.metric("Reporte de lesiones usado", lesiones[0] or "ninguno", f"{lesiones[1]} jugadores" if lesiones[1] else None)
c2.metric("Correcciones manuales de lesiones", manuales)
c3.metric("Último ajuste del modelo", (modelo[0][:16] if modelo else "nunca") + " UTC")

st.subheader("Fuentes y calidad de datos")
fuentes["ultima_captura"] = fuentes.ultima_captura.map(ui.hora_panama)
st.dataframe(fuentes, hide_index=True, width="stretch")
if alertas.empty:
    st.caption("Sin alertas de calidad.")
else:
    st.dataframe(alertas, hide_index=True, width="stretch")

st.subheader("Resultados: lo que el modelo aprendió")
with ui.conexion() as con:
    res = resultados.ultimas_metricas(con)
if not res:
    st.caption("Todavía no hay días jugados con proyección. Se califican solos al actualizar.")
else:
    st.caption(f"{res['dias']} días calificados ({res['desde']} a {res['hasta']}). Factor = corrección que se aplica "
               "a la media de las proyecciones nuevas (1 = sin cambio).")
    st.dataframe(pd.DataFrame(res["por_stat"]).T, width="stretch")
    l = res["lineas"]
    if l["n"]:
        st.metric("Lado más probable contra líneas guardadas", f"{l['aciertos']} de {l['n']}",
                  f"Brier modelo {l['brier_modelo_vs']} vs mercado {l['brier_mercado']}" if l["n_mercado"] else None,
                  delta_color="off")
        st.dataframe(pd.DataFrame(l["ultimos"]), hide_index=True, width="stretch")
