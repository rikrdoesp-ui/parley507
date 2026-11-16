"""Califica las proyecciones de días ya jugados contra lo que pasó y aprende del error.

Cada actualización:
- toma la última proyección base de cada jugador y mercado hecha antes del partido (o la primera, si todas son de
  después), y la compara con el box score;
- con las líneas guardadas (Stake o consenso) mira si acertó el lado más probable y compara su Brier con el mercado;
- calcula, por estadística, cuánto se queda corto o se pasa el modelo (real / proyectado) y guarda un factor de
  corrección que las proyecciones siguientes aplican a la media. El factor se encoge hacia 1 con poca muestra y no pasa
  de ±10 %, para que unos pocos días raros no lo descontrolen.
"""
import json

import numpy as np
import pandas as pd

from .. import config, db, odds
from . import modelo

VERSION = "nba-sesgo-0.1"
MUESTRA_CONFIANZA = 1500  # Con esta cantidad de proyecciones calificadas, el factor se aplica a la mitad.
TOPE_FACTOR = 0.10
ULTIMOS_LEGS = 40


def factor_sesgo(real: float, proyectado: float, n: int) -> float:
    """real/proyectado encogido hacia 1 según la muestra y limitado a ±TOPE_FACTOR."""
    if n == 0 or proyectado <= 0:
        return 1.0
    crudo = real / proyectado - 1
    return float(1 + np.clip(crudo * n / (n + MUESTRA_CONFIANZA), -TOPE_FACTOR, TOPE_FACTOR))


def historial_factores(con) -> pd.DataFrame:
    filas = con.execute("SELECT created_at, params_json FROM model_runs WHERE model_version = ? ORDER BY created_at",
                        (VERSION,)).fetchall()
    return pd.DataFrame([{"desde": c, **json.loads(p)["factores"]} for c, p in filas])


def factores_vigentes(con) -> dict:
    """{estadística: factor} de la última calificación; sin calificaciones, 1."""
    h = historial_factores(con)
    return {s: float(h[s].iloc[-1]) if not h.empty and s in h else 1.0 for s in modelo.ESTADISTICAS}


def calificar(con) -> pd.DataFrame:
    """Una fila por jugador, partido y mercado ya jugado (con minutos), con la línea guardada si la hay."""
    pred = pd.read_sql("""SELECT p.game_id, p.game_date, p.player_id, p.market, p.projected_mean, p.dispersion,
                             p.lower_interval, p.upper_interval, p.generated_at, g.start_time_utc,
                             s.minutes, s.points, s.rebounds, s.assists, pl.full_name AS jugador
                           FROM predictions p JOIN games g USING(game_id)
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

    # Media sin la corrección que estaba vigente al proyectar, para que el factor no se aplique dos veces.
    h = historial_factores(con)
    pred["factor"] = 1.0
    for r in h.itertuples():
        posterior = pred.generated_at >= r.desde
        if posterior.any():
            pred.loc[posterior, "factor"] = pred.loc[posterior, "stat"].map(
                lambda s, r=r: float(getattr(r, s, 1.0))).astype(float)
    pred["crudo"] = pred.projected_mean / pred.factor

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


def resumir(df: pd.DataFrame) -> tuple[dict, dict]:
    """(factores nuevos, métricas para la página)."""
    unico = df.drop_duplicates(["game_id", "player_id", "market"])
    factores, por_stat = {}, {}
    for s in modelo.ESTADISTICAS:
        g = unico[unico.stat == s]
        factores[s] = round(factor_sesgo(g.real.sum(), g.crudo.sum(), len(g)), 4)
        por_stat[s] = {"n": int(len(g)),
                       "sesgo": round(float(g.real.mean() - g.projected_mean.mean()), 3) if len(g) else None,
                       "mae": round(float((g.real - g.projected_mean).abs().mean()), 3) if len(g) else None,
                       "cobertura_10_90": round(float(g.real.between(g.lower_interval, g.upper_interval).mean()), 3)
                       if len(g) else None,
                       "factor": factores[s]}
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
                          "p": round(float(r.p_lado), 3), "real": int(r.real), "ok": bool(r.acierto)}
                         for r in ultimos.itertuples()]
    dias = sorted(df.game_date.unique())
    return factores, {"por_stat": por_stat, "lineas": lineas, "dias": len(dias),
                      "desde": dias[0] if dias else None, "hasta": dias[-1] if dias else None}


def actualizar(con) -> dict:
    """Califica todo lo jugado, guarda el factor de corrección nuevo y devuelve las métricas."""
    df = calificar(con)
    if df.empty:
        return {}
    factores, metricas = resumir(df)
    con.execute("INSERT INTO model_runs(sport, model_version, training_cutoff, params_json, metrics_json, created_at)"
                " VALUES ('NBA', ?, ?, ?, ?, ?)",
                (VERSION, metricas["hasta"], json.dumps({"factores": factores}), json.dumps(metricas), db.ahora_utc()))
    con.commit()
    return metricas


def ultimas_metricas(con) -> dict | None:
    fila = con.execute("SELECT metrics_json, created_at FROM model_runs WHERE model_version = ? ORDER BY run_id DESC LIMIT 1",
                       (VERSION,)).fetchone()
    return {**json.loads(fila[0]), "fecha": fila[1][:10]} if fila else None
