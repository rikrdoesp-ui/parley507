"""Califica las proyecciones de días ya jugados contra lo que pasó y aprende del error.

Cada actualización:
- toma la última proyección base de cada jugador y mercado hecha antes del partido (o la primera, si todas son de
  después), y la compara con el box score;
- con las líneas guardadas (Stake o consenso) mira si acertó el lado más probable y compara su Brier con el mercado;
- guarda esas métricas junto con el factor de sesgo que usaron las proyecciones del día.

El factor de sesgo (`factores_temporada`) se calcula con todos los partidos ya jugados de la temporada: real contra lo
que el modelo habría proyectado antes de cada partido. Se encoge hacia 1 con poca muestra y no pasa de ±10 %. En el
backtest bajó el error medio en las dos temporadas probadas (puntos 2026-27: 4,84 a 4,76).
"""
import json

import numpy as np
import pandas as pd

from .. import config, db, odds
from . import modelo

VERSION = "nba-sesgo-0.1"
MUESTRA_CONFIANZA = 1500  # Con esta cantidad de proyecciones calificadas, el factor se aplica a la mitad.
TOPE_FACTOR = 0.10
ULTIMOS_LEGS = 400  # Los legs de los días más recientes, para verlos por partido.


def factor_sesgo(real: float, proyectado: float, n: int) -> float:
    """real/proyectado encogido hacia 1 según la muestra y limitado a ±TOPE_FACTOR."""
    if n == 0 or proyectado <= 0:
        return 1.0
    crudo = real / proyectado - 1
    return float(1 + np.clip(crudo * n / (n + MUESTRA_CONFIANZA), -TOPE_FACTOR, TOPE_FACTOR))


def factores_temporada(df: pd.DataFrame) -> dict:
    """{estadística: factor} con las filas ya jugadas de la temporada (proyección previa y valor real)."""
    salida = {}
    for s in modelo.ESTADISTICAS:
        g = df.dropna(subset=[f"mu_{s}", s])
        salida[s] = round(factor_sesgo(g[s].sum(), g[f"mu_{s}"].sum(), len(g)), 4)
    return salida


def calificar(con) -> pd.DataFrame:
    """Una fila por jugador, partido y mercado ya jugado (con minutos), con la línea guardada si la hay."""
    pred = pd.read_sql("""SELECT p.game_id, p.game_date, p.player_id, p.market, p.projected_mean, p.dispersion,
                             p.lower_interval, p.upper_interval, p.generated_at, g.start_time_utc,
                             s.minutes, s.points, s.rebounds, s.assists, s.points + s.rebounds + s.assists AS pra,
                             s.points + s.rebounds AS pr, s.rebounds + s.assists AS ra, pl.full_name AS jugador,
                             a.abbreviation || ' @ ' || h.abbreviation AS partido
                           FROM predictions p JOIN games g USING(game_id)
                           LEFT JOIN teams h ON h.team_id = g.home_team_id LEFT JOIN teams a ON a.team_id = g.away_team_id
                           JOIN nba_player_game_stats s ON s.game_id = p.game_id AND s.player_id = p.player_id
                           JOIN players pl ON pl.player_id = p.player_id
                           WHERE p.scenario = 'base' AND p.projected_mean IS NOT NULL AND s.minutes > 0""", con)
    if pred.empty:
        return pred
    # Se prefiere la última hecha antes del inicio; si todas son de después, la primera (los datos del modelo
    # solo llegan hasta el día anterior, así que no ve el resultado).
    pred["antes"] = pred.generated_at <= pred.start_time_utc.fillna("")
    pred["orden"] = np.where(pred.antes, pred.generated_at, "")
    pred = pred.sort_values(["antes", "orden", "generated_at"], ascending=[True, True, False])
    pred = pred.groupby(["game_id", "player_id", "market"]).tail(1).copy()
    pred["stat"] = pred.market.map(config.MERCADOS_NBA)
    pred["real"] = [getattr(r, r.stat) for r in pred.itertuples()]

    lineas = pd.read_sql("""SELECT game_date, player_id, market, line, over_odds, under_odds, bookmaker, captured_at
                            FROM player_props WHERE player_id IS NOT NULL""", con)
    lineas = lineas.sort_values("captured_at").groupby(["game_date", "player_id", "market", "line"]).tail(1)
    df = pred.merge(lineas, on=["game_date", "player_id", "market"], how="left")
    con_linea = df.line.notna()
    po = np.where(con_linea, modelo.p_over(df.projected_mean, df.dispersion, df.line.fillna(0)), np.nan)
    pu = np.where(con_linea, modelo.p_under(df.projected_mean, df.dispersion, df.line.fillna(0)), np.nan)
    df["lado"] = np.where(~con_linea, None, np.where(po >= pu, "over", "under"))
    df["p_lado"] = np.where(po >= pu, po, pu)
    over = df.real > df.line
    df["acierto"] = np.where(~con_linea | (df.real == df.line), np.nan, np.where(df.lado == "over", over, ~over))
    df["p_mercado"] = [odds.sin_margen(r.over_odds, r.under_odds) if r.over_odds > 1 and r.under_odds > 1
                       else np.nan for r in df.itertuples()]
    df["p_mercado"] = np.where(df.lado == "under", 1 - df.p_mercado, df.p_mercado)
    return df


def resumir(df: pd.DataFrame, factores: dict) -> dict:
    """Métricas para la página; `factores` es la corrección que usaron las proyecciones del día."""
    unico = df.drop_duplicates(["game_id", "player_id", "market"])
    por_stat = {}
    for s in modelo.TODAS:
        g = unico[unico.stat == s]
        por_stat[s] = {"n": int(len(g)),
                       "sesgo": round(float(g.real.mean() - g.projected_mean.mean()), 3) if len(g) else None,
                       "mae": round(float((g.real - g.projected_mean).abs().mean()), 3) if len(g) else None,
                       "cobertura_10_90": round(float(g.real.between(g.lower_interval, g.upper_interval).mean()), 3)
                       if len(g) else None,
                       "factor": factores.get(s)}  # Las combinadas heredan la de sus partes.
    legs = df.dropna(subset=["acierto"])
    con_mercado = legs.dropna(subset=["p_mercado"])
    lineas = {"n": int(len(legs)),
              "aciertos": int(legs.acierto.sum()),
              "brier_modelo": round(float(((legs.p_lado - legs.acierto) ** 2).mean()), 4) if len(legs) else None,
              "n_mercado": int(len(con_mercado)),
              "brier_modelo_vs": round(float(((con_mercado.p_lado - con_mercado.acierto) ** 2).mean()), 4)
              if len(con_mercado) else None,
              "brier_mercado": round(float(((con_mercado.p_mercado - con_mercado.acierto) ** 2).mean()), 4)
              if len(con_mercado) else None}
    ultimos = legs.sort_values(["game_date", "p_lado"], ascending=False).head(ULTIMOS_LEGS)
    lineas["ultimos"] = [{"f": r.game_date, "j": r.jugador, "m": r.market, "l": float(r.line), "lado": r.lado,
                          "p": round(float(r.p_lado), 3), "real": int(r.real), "ok": bool(r.acierto),
                          "partido": r.partido or ""}
                         for r in ultimos.itertuples()]
    dias = sorted(df.game_date.unique())
    return {"por_stat": por_stat, "lineas": lineas, "dias": len(dias),
                      "desde": dias[0] if dias else None, "hasta": dias[-1] if dias else None}


def actualizar(con, factores: dict) -> dict:
    """Califica todo lo jugado y guarda las métricas con el factor de sesgo que usaron las proyecciones."""
    df = calificar(con)
    if df.empty:
        return {}
    metricas = resumir(df, factores)
    con.execute("INSERT INTO model_runs(sport, model_version, training_cutoff, params_json, metrics_json, created_at)"
                " VALUES ('NBA', ?, ?, ?, ?, ?)",
                (VERSION, metricas["hasta"], json.dumps({"factores": factores}), json.dumps(metricas), db.ahora_utc()))
    con.commit()
    return metricas


def ultimas_metricas(con) -> dict | None:
    fila = con.execute("SELECT metrics_json, created_at FROM model_runs WHERE model_version = ? ORDER BY run_id DESC LIMIT 1",
                       (VERSION,)).fetchone()
    return {**json.loads(fila[0]), "fecha": fila[1][:10]} if fila else None
