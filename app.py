"""Panama Sports Analytics. Ejecutar: uv run streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Panama Sports Analytics", layout="wide")
st.navigation([
    st.Page("paginas/hoy.py", title="Hoy", default=True),
    st.Page("paginas/nba.py", title="NBA"),
    st.Page("paginas/props.py", title="Props"),
    st.Page("paginas/backtest.py", title="Backtest"),
]).run()
