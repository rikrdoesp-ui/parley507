import json

import pandas as pd
import streamlit as st

from psa import ui
from psa.nba import backtest

st.title("Backtest NBA")
st.caption("Walk-forward: cada proyección usa solo partidos anteriores y la dispersión se ajusta con temporadas previas. "
           "La línea sintética (media L10 redondeada a x.5) no es una línea real de casa.")

if st.button("Correr backtest", type="primary"):
    with st.spinner("Calculando (unos segundos)..."), ui.conexion() as con:
        st.session_state["bt"] = backtest.correr(con)

r = st.session_state.get("bt")
if r is None:
    with ui.conexion() as con:
        fila = con.execute("SELECT metrics_json, created_at FROM model_runs ORDER BY run_id DESC LIMIT 1").fetchone()
    if not fila:
        st.info("Aún no hay backtest. Pulsa Correr backtest.")
        st.stop()
    r = json.loads(fila[0])
    st.caption(f"Último backtest guardado: {fila[1][:16]} UTC")

for temporada, por_stat in r["metricas"].items():
    st.subheader(f"Temporada {temporada}")
    st.dataframe(pd.DataFrame(por_stat).T.rename_axis("estadística"), width="stretch")
st.caption("Brier: menor es mejor. 'acierto L10' es la frecuencia de los últimos 10 juegos sobre la línea; "
           "'50' es lanzar una moneda. MAE: error absoluto medio de la media. Cobertura 10-90 ideal: 0.80.")

st.subheader("Legs reales de /parley")
legs = r.get("legs_reales") or {}
if not legs:
    st.info("No hay legs NBA decididos de puntos, rebotes o asistencias en el registro de /parley.")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Legs comparables", legs["legs_comparables"], f"de {legs['legs_decididos']} decididos")
    c2.metric("Brier app", legs["comparables_brier_app"])
    c3.metric("Brier mercado", legs["comparables_brier_mercado"])
    c4.metric("Brier /parley", legs["comparables_brier_parley"])
    if legs["muestra_suficiente"]:
        st.success("Hay 100 legs o más: ya se puede aplicar el criterio para pasar la app a fuente de /parley.")
    else:
        st.warning(f"Muestra insuficiente: {legs['legs_comparables']} de 100 legs. La app sigue siendo solo informativa.")

if isinstance(r.get("calibracion"), pd.DataFrame) and not r["calibracion"].empty:
    st.subheader("Calibración de P(over) en línea sintética")
    cal = r["calibracion"]
    stat = st.selectbox("Estadística", sorted(cal.estadistica.unique()))
    vista = cal[cal.estadistica == stat]
    st.scatter_chart(vista, x="previsto", y="real", color="temporada", size="n")
    st.dataframe(vista, hide_index=True, width="stretch")
if isinstance(r.get("legs"), pd.DataFrame) and not r["legs"].empty:
    with st.expander("Detalle de legs reales"):
        st.dataframe(r["legs"], hide_index=True, width="stretch")
