"""Modelo NBA v0.1: minutos esperados x tasa por minuto, con distribución binomial negativa.

- Minutos: media exponencial de los partidos jugados (vida media VIDA_MINUTOS partidos).
- Tasa: estadística por minuto, media exponencial más larga (VIDA_TASA).
- Distribución: binomial negativa con media = minutos x tasa y dispersión k por estadística, ajustada
  en el backtest con datos anteriores al periodo evaluado. k absorbe también la incertidumbre de minutos.
Cada fila se proyecta solo con partidos anteriores (shift): no hay fuga de información.
"""
import math

import numpy as np
import pandas as pd
from scipy.stats import nbinom

ESTADISTICAS = ["points", "rebounds", "assists"]
VIDA_MINUTOS = 4
VIDA_TASA = 12
MUESTRA_MINIMA = 5
K_DEFECTO = {"points": 8.0, "rebounds": 6.0, "assists": 4.0}  # Solo si nunca se corrió el ajuste.
TOPE_MINUTOS = 40.0


def _por_jugador(serie: pd.Series, jugador: pd.Series, funcion) -> pd.Series:
    return serie.groupby(jugador, sort=False).transform(funcion)


def con_proyeccion(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega a cada fila (jugador, partido) la proyección hecha solo con sus partidos anteriores.

    Espera columnas player_id, game_date, game_id, minutes y ESTADISTICAS. Filas futuras llevan NaN.
    """
    df = df.sort_values(["player_id", "game_date", "game_id"]).reset_index(drop=True)
    jugador = df["player_id"]
    previos = df.groupby("player_id", sort=False).cumcount()
    min_prev = df.groupby("player_id", sort=False)["minutes"].shift()
    df["n_previos"] = previos
    df["min_proy"] = _por_jugador(min_prev, jugador, lambda s: s.ewm(halflife=VIDA_MINUTOS).mean())
    df["min_sd"] = _por_jugador(min_prev, jugador, lambda s: s.rolling(10, min_periods=3).std())
    den = _por_jugador(min_prev, jugador, lambda s: s.ewm(halflife=VIDA_TASA).mean())
    valido = previos >= MUESTRA_MINIMA
    for stat in ESTADISTICAS:
        prev = df.groupby("player_id", sort=False)[stat].shift()
        num = _por_jugador(prev, jugador, lambda s: s.ewm(halflife=VIDA_TASA).mean())
        df[f"tasa_{stat}"] = (num / den).where(valido)
        df[f"mu_{stat}"] = (df["min_proy"] * df[f"tasa_{stat}"]).where(valido)
        df[f"l10_{stat}"] = _por_jugador(prev, jugador, lambda s: s.rolling(10, min_periods=MUESTRA_MINIMA).mean())
        # Últimos 10 valores previos, para el acierto L10 a una línea (línea base del backtest).
        for i in range(1, 11):
            df[f"lag{i}_{stat}"] = df.groupby("player_id", sort=False)[stat].shift(i)
    return df


def ajustar_k(mu: np.ndarray, y: np.ndarray) -> float:
    """Dispersión por momentos: Var = mu + mu^2 / k. Sin sobredispersión, k grande (casi Poisson)."""
    exceso = np.sum((y - mu) ** 2 - mu)
    if exceso <= 0:
        return 200.0
    return float(np.clip(np.sum(mu ** 2) / exceso, 0.5, 200.0))


def _p(mu, k):
    return k / (k + np.asarray(mu, dtype=float))


def p_over(mu, k: float, linea):
    """P(valor > línea). En línea entera el empate (push) no cuenta como over."""
    return nbinom.sf(np.floor(linea), k, _p(mu, k))


def p_under(mu, k: float, linea):
    """P(valor < línea)."""
    return nbinom.cdf(np.ceil(linea) - 1, k, _p(mu, k))


def intervalo(mu, k: float, bajo: float = 0.1, alto: float = 0.9):
    p = _p(mu, k)
    return nbinom.ppf(bajo, k, p), nbinom.ppf(alto, k, p)


def lineas_cercanas(mu: float, k: float) -> list[float]:
    """Líneas x.5 entre los percentiles 5 y 95, para exportar P(over) sin que /parley necesite SciPy."""
    bajo, alto = intervalo(mu, k, 0.05, 0.95)
    return [x + 0.5 for x in range(int(bajo), int(math.ceil(alto)) + 1)]


def redistribuir(minutos: dict, fuera: set, tope: float = TOPE_MINUTOS) -> dict:
    """Reparte los minutos de los que no juegan entre la rotación (>= 10 min), según el margen de cada uno hasta
    el tope: el suplente de 20 min recibe más que la estrella de 36, como suele pasar.

    Heurística v0.1: no cambia la tasa por minuto de nadie (sin efecto de uso) y nadie pasa del tope.
    """
    libres = sum(m for j, m in minutos.items() if j in fuera)
    quedan = {j: m for j, m in minutos.items() if j not in fuera}
    margen = {j: tope - m for j, m in quedan.items() if 10 <= m < tope}
    total = sum(margen.values())
    if not libres or not total:
        return quedan
    return {j: min(tope, m + libres * margen[j] / total) if j in margen else m for j, m in quedan.items()}
