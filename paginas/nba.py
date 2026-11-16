import pandas as pd
import streamlit as st

from psa import config, db, ui
from psa.nba import lesiones, proyeccion

st.title("NBA: proyecciones por partido")
fecha = ui.elegir_fecha()
with ui.conexion() as con:
    pred = proyeccion.ultimas(con, fecha)
if pred.empty:
    st.info("No hay proyecciones para esta fecha. Ve a Hoy y pulsa Actualizar datos.")
    st.stop()

# set_index + unstack conserva las filas con NaN (sin muestra), que pivot_table descartaría.
ancho = (pred.set_index(["game_id", "player_id", "jugador", "equipo", "scenario", "minutes", "minutes_sd",
                         "sample_games", "notes", "market"])[["projected_mean", "lower_interval", "upper_interval"]]
         .unstack("market").reset_index())
ancho.columns = ["_".join(c for c in col if c) for col in ancho.columns]
with ui.conexion() as con:
    partidos = dict(con.execute("""SELECT g.game_id, a.abbreviation || ' @ ' || h.abbreviation FROM games g
                                   JOIN teams h ON h.team_id = g.home_team_id JOIN teams a ON a.team_id = g.away_team_id
                                   WHERE g.game_date = ?""", (fecha,)))
    estados = lesiones.vigentes(con, fecha)
juego = st.selectbox("Partido", sorted(ancho.game_id.unique()), format_func=lambda g: partidos.get(g, g))
del_juego = ancho[ancho.game_id == juego]
escenario = st.selectbox("Escenario", sorted(del_juego.scenario.unique(), key=lambda s: (s != "base", s)),
                         help="'sin X': si un jugador en duda no juega, sus minutos se reparten en la rotación.")
estado_por_clave = dict(zip(estados.clave, estados.status)) if not estados.empty else {}

vista = del_juego[del_juego.scenario == escenario].copy()
vista["estado"] = vista.jugador.map(lambda n: estado_por_clave.get(db.clave_nombre(n), ""))
for mercado in config.MERCADOS_NBA:
    vista[mercado] = [f"{m:.1f} ({lo:.0f}-{hi:.0f})" if pd.notna(m) else "sin muestra" for m, lo, hi in
                      zip(vista[f"projected_mean_{mercado}"], vista[f"lower_interval_{mercado}"],
                          vista[f"upper_interval_{mercado}"])]
st.caption("Media proyectada (intervalo 10-90 %). Minutos: media ponderada reciente, con ajustes y bajas aplicados.")
for equipo, g in vista.groupby("equipo"):
    st.subheader(equipo)
    st.dataframe(g.sort_values("minutes", ascending=False)[
        ["jugador", "estado", "minutes", "minutes_sd", "sample_games", *config.MERCADOS_NBA, "notes"]]
        .rename(columns={"minutes": "minutos", "minutes_sd": "desv. min L10", "sample_games": "partidos", "notes": "notas"}),
        hide_index=True, width="stretch", column_config={"minutos": st.column_config.NumberColumn(format="%.1f"),
                                                          "desv. min L10": st.column_config.NumberColumn(format="%.1f")})

st.divider()
jugadores = del_juego[["player_id", "jugador", "equipo"]].drop_duplicates().sort_values("jugador")
opciones = dict(zip(jugadores.player_id, jugadores.jugador + " (" + jugadores.equipo + ")"))
izq, der = st.columns(2)
with izq.form("lesion"):
    st.markdown("**Corregir estado de lesión** (manda sobre el PDF ese día)")
    pid = st.selectbox("Jugador", list(opciones), format_func=opciones.get)
    nuevo = st.selectbox("Estado", ["Out", "Doubtful", "Questionable", "Probable", "Available"])
    motivo = st.text_input("Motivo o fuente")
    if st.form_submit_button("Guardar estado"):
        with ui.conexion() as con:
            fila = jugadores[jugadores.player_id == pid].iloc[0]
            equipo_id = con.execute("SELECT team_id FROM teams WHERE abbreviation = ?", (fila.equipo,)).fetchone()
            lesiones.corregir(con, fecha, fila.jugador, int(pid), equipo_id[0] if equipo_id else None, nuevo, motivo)
        st.success("Guardado. Pulsa Recalcular proyecciones en Hoy.")
with der.form("minutos"):
    st.markdown("**Minutos a mano** (titularidad, restricción, rol nuevo)")
    pid_m = st.selectbox("Jugador ", list(opciones), format_func=opciones.get)
    mins = st.number_input("Minutos esperados", 0.0, 48.0, 24.0, 0.5)
    razon = st.text_input("Razón (obligatoria)")
    guardar, borrar = st.columns(2)
    if guardar.form_submit_button("Guardar minutos"):
        if not razon.strip():
            st.error("Escribe la razón del ajuste.")
        else:
            with ui.conexion() as con:
                con.execute("INSERT OR REPLACE INTO minutes_overrides VALUES (?, ?, ?, ?, ?)",
                            (fecha, int(pid_m), mins, razon.strip(), db.ahora_utc()))
            st.success("Guardado. Pulsa Recalcular proyecciones en Hoy.")
    if borrar.form_submit_button("Quitar ajuste"):
        with ui.conexion() as con:
            con.execute("DELETE FROM minutes_overrides WHERE game_date = ? AND player_id = ?", (fecha, int(pid_m)))
        st.success("Ajuste quitado. Pulsa Recalcular proyecciones en Hoy.")
