"""Rutas y parámetros. Cambiar rutas con las variables PSA_DATOS y PARLEY_DATOS."""
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# La base va fuera de OneDrive: la sincronización puede corromper un SQLite abierto.
DATOS = Path(os.environ.get("PSA_DATOS", Path.home() / "sports-data"))
DB = DATOS / "psa.sqlite"
STAKE = Path(os.environ.get("PARLEY_DATOS", Path.home() / "OneDrive" / "Desktop" / "CODE" / "stake"))

PANAMA = timezone(timedelta(hours=-5), "Panamá")  # Panamá no usa horario de verano.
PAUSA_API = 0.7  # Segundos entre llamadas a stats.nba.com.
MODELO_NBA = "nba-min-tasa-nb-0.2"  # 0.2: agrega PRA, PR y RA (fuerza un backtest nuevo).
# Las combinadas usan las mismas claves que /parley (pra, pr, ra).
MERCADOS_NBA = {"puntos": "points", "rebotes": "rebounds", "asistencias": "assists", "pra": "pra", "pr": "pr", "ra": "ra"}


def hoy_panama() -> date:
    return datetime.now(PANAMA).date()


def temporada_actual(dia: date | None = None) -> str:
    dia = dia or hoy_panama()
    inicio = dia.year if dia.month >= 9 else dia.year - 1
    return f"{inicio}-{(inicio + 1) % 100:02d}"


def temporadas(dia: date | None = None) -> list[str]:
    """La actual y las 2 anteriores, de la más vieja a la más nueva."""
    inicio = int(temporada_actual(dia)[:4])
    return [f"{a}-{(a + 1) % 100:02d}" for a in range(inicio - 2, inicio + 1)]
