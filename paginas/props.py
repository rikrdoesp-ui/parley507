import pandas as pd
import streamlit as st

from psa import db, odds, ui
from psa.nba import proyeccion
from psa.nba import props as props_nba

st.title("Player props")
st.caption("La app muestra proyección, probabilidad y valor por leg. BET / PASS, montos y topes los decide /parley.")
fecha = ui.elegir_fecha()
with ui.conexion() as con:
    pred = proyeccion.ultimas(con, fecha)
    props = pd.read_sql("""SELECT * FROM player_props WHERE game_date = ? ORDER BY captured_at""", con, params=(fecha,))
if pred.empty:
    st.info("No hay proyecciones para esta fecha. Ve a Hoy y pulsa Actualizar datos.")
    st.stop()

base = pred[pred.scenario == "base"]
jugadores = base[["player_id", "jugador", "equipo"]].drop_duplicates().sort_values("jugador")
opciones = dict(zip(jugadores.player_id, jugadores.jugador + " (" + jugadores.equipo + ")"))

with st.expander("Ingresar una línea a mano (la que ves en Stake)"):
    with st.form("linea"):
        c1, c2, c3 = st.columns(3)
        pid = c1.selectbox("Jugador", list(opciones), format_func=opciones.get)
        mercado = c2.selectbox("Mercado", ["puntos", "rebotes", "asistencias"])
        linea = c3.number_input("Línea", 0.0, 80.0, 10.5, 0.5)
        c4, c5, c6 = st.columns(3)
        sobre = c4.text_input("Cuota Over (decimal o americana)")
        debajo = c5.text_input("Cuota Under (opcional)")
        casa = c6.text_input("Casa", "Stake")
        if st.form_submit_button("Guardar línea"):
            try:
                o = odds.a_decimal(sobre) if sobre.strip() else None
                u = odds.a_decimal(debajo) if debajo.strip() else None
            except ValueError as error:
                st.error(str(error))
            else:
                if o is None and u is None:
                    st.error("Escribe al menos una cuota.")
                else:
                    with ui.conexion() as con:
                        con.execute("""INSERT OR IGNORE INTO player_props(game_date, player_id, player_name, market, line,
                                       over_odds, under_odds, bookmaker, captured_at, entry_method, source_ref)
                                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'MANUAL', ?)""",
                                    (fecha, int(pid), jugadores.set_index("player_id").jugador[pid], mercado, linea, o, u,
                                     casa.strip() or "Stake", db.ahora_utc(), db.ahora_utc()))
                    st.success("Línea guardada (ingresada por el usuario).")
                    st.rerun()

if props.empty:
    st.warning(ui.SIN_VALOR + ". No hay líneas para esta fecha: ingrésalas arriba o carga las referencias de /parley.")
    st.stop()

escenarios = sorted(pred.scenario.unique(), key=lambda s: (s != "base", s))
escenario = st.selectbox("Escenario", escenarios)
tabla = props_nba.evaluar(pred, props, escenario)
if not props_nba.hay_precio(tabla):
    st.warning(ui.SIN_VALOR + ": ninguna línea tiene precio apostable ingresado.")
porcentaje = {c: st.column_config.NumberColumn(format="percent") for c in
              ["P over", "P under", "P mercado over (sin margen)", "P mezcla over", "P mezcla under", "edge modelo over", "edge over", "edge under", "VE over", "VE under",
               "mejor VE", "mejor edge"]}
st.dataframe(tabla, hide_index=True, width="stretch",
             column_config={**porcentaje, "media": st.column_config.NumberColumn(format="%.1f"),
                            "minutos": st.column_config.NumberColumn(format="%.1f"),
                            "cuota justa over": st.column_config.NumberColumn(format="%.2f"),
                            "cuota justa under": st.column_config.NumberColumn(format="%.2f")})
st.caption("P mezcla = mercado sin margen movido por el modelo (25 %, máx. 4 puntos con dos lados). Edge y VE usan la mezcla; VE solo con precio de una "
           "casa; el consenso de BettingPros es referencia, no precio. Ordenado por VE y edge, no por probabilidad.")
