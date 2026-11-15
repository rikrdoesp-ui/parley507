import numpy as np
import pandas as pd
import streamlit as st

from psa import db, odds, ui
from psa.nba import modelo, proyeccion

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
proy = pred[pred.scenario == escenario].set_index(["player_id", "market"])
props = props.groupby(["player_name", "market", "line", "bookmaker", "entry_method"]).tail(1)  # Última captura.

filas = []
for p in props.itertuples():
    clave = (p.player_id, p.market)
    if pd.isna(p.player_id) or clave not in proy.index:
        filas.append({"jugador": p.player_name, "mercado": p.market, "línea": p.line, "casa": p.bookmaker,
                      "origen": p.entry_method, "estado de datos": "sin proyección (jugador no identificado o fuera)"})
        continue
    r = proy.loc[clave]
    if pd.isna(r.projected_mean):
        filas.append({"jugador": p.player_name, "mercado": p.market, "línea": p.line, "casa": p.bookmaker,
                      "origen": p.entry_method, "estado de datos": "muestra insuficiente"})
        continue
    po = float(modelo.p_over(r.projected_mean, r.dispersion, p.line))
    pu = float(modelo.p_under(r.projected_mean, r.dispersion, p.line))
    dos_lados = pd.notna(p.over_odds) and pd.notna(p.under_odds)
    p_mercado = odds.sin_margen(p.over_odds, p.under_odds) if dos_lados else np.nan
    # El consenso de /parley ya viene sin margen: su "cuota" no es un precio apostable, no tiene VE.
    apostable = p.entry_method != "PARLEY_REF"
    filas.append({
        "jugador": p.player_name, "equipo": r.equipo, "mercado": p.market, "línea": p.line, "casa": p.bookmaker,
        "origen": p.entry_method, "media": r.projected_mean, "rango 10-90": f"{r.lower_interval:.0f}-{r.upper_interval:.0f}",
        "minutos": r.minutes, "P over": po, "P under": pu,
        "cuota justa over": odds.cuota_justa(po), "cuota justa under": odds.cuota_justa(pu),
        "cuota over": p.over_odds, "cuota under": p.under_odds, "P mercado over (sin margen)": p_mercado,
        "edge over": po - p_mercado if dos_lados else np.nan, "edge under": pu - (1 - p_mercado) if dos_lados else np.nan,
        "VE over": odds.valor_esperado(po, p.over_odds) if apostable and pd.notna(p.over_odds) else np.nan,
        "VE under": odds.valor_esperado(pu, p.under_odds) if apostable and pd.notna(p.under_odds) else np.nan,
        "partidos": r.sample_games, "estado de datos": "completo" if r.sample_games >= 20 else "parcial",
        "riesgos": r.notes,
    })
tabla = pd.DataFrame(filas)
if "VE over" in tabla:
    tabla["mejor VE"] = tabla[["VE over", "VE under"]].max(axis=1)
    tabla["mejor edge"] = tabla[["edge over", "edge under"]].max(axis=1)
    tabla = tabla.sort_values(["mejor VE", "mejor edge"], ascending=False, na_position="last")
if not tabla.get("VE over", pd.Series(dtype=float)).notna().any():
    st.warning(ui.SIN_VALOR + ": ninguna línea tiene precio apostable ingresado.")
porcentaje = {c: st.column_config.NumberColumn(format="percent") for c in
              ["P over", "P under", "P mercado over (sin margen)", "edge over", "edge under", "VE over", "VE under",
               "mejor VE", "mejor edge"]}
st.dataframe(tabla, hide_index=True, width="stretch",
             column_config={**porcentaje, "media": st.column_config.NumberColumn(format="%.1f"),
                            "minutos": st.column_config.NumberColumn(format="%.1f"),
                            "cuota justa over": st.column_config.NumberColumn(format="%.2f"),
                            "cuota justa under": st.column_config.NumberColumn(format="%.2f")})
st.caption("Edge = probabilidad del modelo menos la del mercado sin margen (misma línea). VE solo con precio de una "
           "casa; el consenso de BettingPros es referencia, no precio. Ordenado por VE y edge, no por probabilidad.")
