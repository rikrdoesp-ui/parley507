"""Piezas compartidas por las páginas de la app."""
from datetime import datetime

import pandas as pd
import streamlit as st

from . import config, db


def conexion():
    return db.conectar()


def elegir_fecha() -> str:
    return st.sidebar.date_input("Fecha (hora de Panamá)", value=config.hoy_panama(), format="YYYY-MM-DD").isoformat()


def hora_panama(utc: str | None) -> str:
    if not utc or pd.isna(utc):
        return "sin hora"
    return datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(config.PANAMA).strftime("%d-%m %H:%M")


def pct(x) -> str:
    return "" if x is None or pd.isna(x) else f"{x:.1%}"


SIN_VALOR = "PROYECCIÓN ESTADÍSTICA — SIN VALOR DE APUESTA CONFIRMADO"
