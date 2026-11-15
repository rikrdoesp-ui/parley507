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
GANANCIA_MAXIMA = 8.0  # Minutos extra máximos por jugador cuando falta un compañero.


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


def redistribuir(minutos: dict, fuera: set, tope: float = TOPE_MINUTOS, fraccion: float = 1.0) -> dict:
    """Reparte los minutos de los que no juegan entre la rotación (>= 10 min), en proporción a sus minutos y con
    un máximo de GANANCIA_MAXIMA por jugador.

    `fraccion`: parte de los minutos libres que se reparte (el resto se lo llevan jugadores fuera de la rotación
    o ya está en la media reciente). Se elige en el backtest.
    """
    libres = fraccion * sum(m for j, m in minutos.items() if j in fuera)
    quedan = {j: m for j, m in minutos.items() if j not in fuera}
    rotacion = {j: m for j, m in quedan.items() if m >= 10}
    total = sum(rotacion.values())
    if not libres or not total:
        return quedan
    # Proporcional a los minutos, con tope de ganancia: los minutos que sobran quedan sin asignar antes que
    # inflar a un suplente (un margen grande no significa que el técnico le vaya a dar 25 minutos más).
    return {j: min(tope, m + min(GANANCIA_MAXIMA, libres * m / total)) if j in rotacion else m
            for j, m in quedan.items()}


TOPE_AUMENTO_USO = 0.35  # Una ausencia no sube la media de un compañero más de un 35 % por uso.


def ajustar_ausencias(presentes: dict, ausentes: dict, alfa: float, fraccion: float = 1.0) -> tuple[dict, dict]:
    """Minutos y medias de los presentes cuando faltan jugadores de rotación.

    presentes: {jugador: (minutos, {stat: tasa por minuto})}; ausentes: {jugador: (minutos, {stat: producción})}.
    1. Una `fraccion` de los minutos de los ausentes se reparte con `redistribuir`.
    2. Por estadística, el hueco es la producción de los ausentes que no recuperan esos minutos extra. Una
       fracción `alfa` del hueco (efecto de uso) va a la rotación en proporción a lo que ya produce cada uno:
       el que más asiste recibe más asistencias. `alfa` se elige en el backtest; 0 = sin efecto de uso.
    """
    minutos = redistribuir({**{p: m for p, (m, _) in presentes.items()}, **{a: m for a, (m, _) in ausentes.items()}},
                           set(ausentes), fraccion=fraccion)
    medias = {p: {} for p in presentes}
    for stat in ESTADISTICAS:
        base = {p: minutos[p] * t[stat] for p, (_, t) in presentes.items() if t.get(stat) == t.get(stat)}
        recuperado = sum((minutos[p] - presentes[p][0]) * presentes[p][1][stat] for p in base)
        hueco = max(0.0, sum(prod.get(stat, 0) or 0 for _, prod in ausentes.values()) - recuperado)
        rotacion = {p: mu for p, mu in base.items() if minutos[p] >= 10}
        total = sum(rotacion.values())
        for p, mu in base.items():
            extra = alfa * hueco * rotacion[p] / total if p in rotacion and total else 0.0
            medias[p][stat] = mu + min(extra, TOPE_AUMENTO_USO * mu)
    return minutos, medias


VIDA_FUERZA = 15  # Partidos de vida media para la fuerza de un equipo (margen de puntos reciente).
VENTAJA_LOCAL = 2.5


def margenes_esperados(juegos: pd.DataFrame) -> pd.DataFrame:
    """Margen esperado de cada equipo en cada partido, solo con partidos anteriores (spread estimado propio).

    juegos: game_id, game_date, home_team_id, away_team_id, home_score, away_score (NaN si no se ha jugado).
    Devuelve game_id, team_id y margen (positivo = favorito por esos puntos).
    """
    j = juegos.sort_values(["game_date", "game_id"])
    local = pd.DataFrame({"game_id": j.game_id, "game_date": j.game_date, "team_id": j.home_team_id,
                          "rival": j.away_team_id, "margen_real": j.home_score - j.away_score, "localia": 1.0})
    visita = pd.DataFrame({"game_id": j.game_id, "game_date": j.game_date, "team_id": j.away_team_id,
                           "rival": j.home_team_id, "margen_real": j.away_score - j.home_score, "localia": -1.0})
    largo = pd.concat([local, visita]).sort_values(["team_id", "game_date", "game_id"]).reset_index(drop=True)
    largo["fuerza"] = largo.groupby("team_id")["margen_real"].transform(
        lambda s: s.shift().ewm(halflife=VIDA_FUERZA).mean()).fillna(0.0)
    rival = largo[["game_id", "team_id", "fuerza"]].rename(columns={"team_id": "rival", "fuerza": "fuerza_rival"})
    largo = largo.merge(rival, on=["game_id", "rival"])
    largo["margen"] = largo.fuerza - largo.fuerza_rival + VENTAJA_LOCAL * largo.localia
    return largo[["game_id", "team_id", "margen"]]



UMBRAL_PALIZA = 12.0  # Spread estimado desde el que se avisa riesgo de paliza a los titulares.
# Probado en el backtest (15-nov-2026): quitarles minutos según el spread no mejora el Brier en 2025-26 ni en
# 2026-27 (efecto real ~1,4 min con spread 16+, y el spread previo anticipa mal las palizas). Por eso solo se avisa.
