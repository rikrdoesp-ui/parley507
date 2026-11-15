"""Backtest walk-forward del modelo NBA.

Para cada temporada de prueba, la dispersión k se ajusta solo con partidos anteriores a su inicio, y cada
proyección usa solo partidos anteriores a ese juego. Mide:
- Error de la media contra el resultado (MAE), frente a la media L10 como línea base.
- Calibración de P(over) en una línea sintética (media L10 redondeada a x.5), frente al acierto L10 a esa línea.
  La línea sintética está etiquetada: no es una línea real de casa.
- Cobertura del intervalo 10-90 (debería rondar 80 %).
- Legs reales de /parley: Brier de la app frente a la probabilidad de mercado y la final de /parley.
"""
import json

import numpy as np
import pandas as pd

from .. import config, db, parley_io
from . import modelo
from .proyeccion import historial

CUBETAS = np.linspace(0, 1, 11)


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def evaluar_temporada(df: pd.DataFrame, temporada: str) -> tuple[dict, dict, pd.DataFrame]:
    inicio = df.loc[df.season == temporada, "game_date"].min()
    entreno = df[(df.game_date < inicio)]
    prueba = df[df.season == temporada]
    ks, metricas, calibracion = {}, {}, []
    for stat in modelo.ESTADISTICAS:
        e = entreno.dropna(subset=[f"mu_{stat}", f"l10_{stat}"])
        p = prueba.dropna(subset=[f"mu_{stat}", f"l10_{stat}"])
        if e.empty or p.empty:
            continue
        k = ks[stat] = modelo.ajustar_k(e[f"mu_{stat}"].to_numpy(), e[stat].to_numpy())
        y, mu = p[stat].to_numpy(), p[f"mu_{stat}"].to_numpy()
        linea = np.floor(p[f"l10_{stat}"].to_numpy()) + 0.5
        sobre = (y > linea).astype(float)
        p_modelo = modelo.p_over(mu, k, linea)
        lags = p[[f"lag{i}_{stat}" for i in range(1, 11)]].to_numpy()
        # Un partido que no existe (menos de 10 previos) no cuenta como "no superó la línea".
        p_l10 = np.nanmean(np.where(np.isnan(lags), np.nan, lags > linea[:, None]), axis=1)
        bajo, alto = modelo.intervalo(mu, k)
        metricas[stat] = {"n": int(len(p)), "k": round(k, 2),
                          "mae_modelo": round(float(np.mean(np.abs(y - mu))), 3),
                          "mae_l10": round(float(np.mean(np.abs(y - p[f"l10_{stat}"]))), 3),
                          "brier_modelo": round(brier(p_modelo, sobre), 4),
                          "brier_acierto_l10": round(brier(p_l10, sobre), 4),
                          "brier_50": round(brier(np.full(len(sobre), 0.5), sobre), 4),
                          "cobertura_10_90": round(float(np.mean((y >= bajo) & (y <= alto))), 3)}
        cubeta = np.clip(np.digitize(p_modelo, CUBETAS) - 1, 0, 9)
        for c in range(10):
            sel = cubeta == c
            if sel.sum():
                calibracion.append({"temporada": temporada, "estadistica": stat, "cubeta": f"{c * 10}-{c * 10 + 10} %",
                                    "previsto": float(p_modelo[sel].mean()), "real": float(sobre[sel].mean()),
                                    "n": int(sel.sum())})
    return ks, metricas, pd.DataFrame(calibracion)


def legs_con_modelo(df: pd.DataFrame, con, ks_por_temporada: dict, k_final: dict) -> pd.DataFrame:
    """Une cada leg real de /parley con la proyección del partido que se jugó ese día (o el siguiente)."""
    legs = parley_io.legs_reales()
    if legs.empty:
        return legs
    claves = pd.read_sql("SELECT player_id, name_key FROM players", con)
    unicos = claves.groupby("name_key").filter(lambda g: len(g) == 1)
    legs["player_id"] = legs.jugador.map(db.clave_nombre).map(dict(zip(unicos.name_key, unicos.player_id)))
    filas = []
    for leg in legs.itertuples():
        stat = config.MERCADOS_NBA[leg.mercado]
        cand = df[(df.player_id == leg.player_id) & (df.game_date >= leg.fecha)].head(1)
        p_app = np.nan
        if not cand.empty and (pd.Timestamp(cand.game_date.iloc[0]) - pd.Timestamp(leg.fecha)).days <= 1:
            mu = cand[f"mu_{stat}"].iloc[0]
            # k ajustada solo con temporadas anteriores a la del leg (sin datos posteriores).
            k = ks_por_temporada.get(cand.season.iloc[0], {}).get(stat, k_final[stat])
            if pd.notna(mu):
                p = float(modelo.p_over(mu, k, leg.linea))
                p_app = p if leg.lado == "over" else float(modelo.p_under(mu, k, leg.linea))
        filas.append({**leg._asdict(), "p_app": p_app, "acierto": float(leg.resultado == "gano")})
    return pd.DataFrame(filas)


def correr(con) -> dict:
    df = modelo.con_proyeccion(historial(con))
    temporadas = sorted(df.season.unique())
    metricas, calibraciones, ks = {}, [], {}
    for t in temporadas[1:]:  # La primera temporada solo sirve de entrenamiento.
        ks[t], m, c = evaluar_temporada(df, t)
        metricas[t] = m
        calibraciones.append(c)
    # La k que usan las proyecciones del día se ajusta con todo lo disponible.
    k_final = {s: modelo.ajustar_k(d[f"mu_{s}"].to_numpy(), d[s].to_numpy())
               for s in modelo.ESTADISTICAS for d in [df.dropna(subset=[f"mu_{s}"])]}
    legs = legs_con_modelo(df, con, ks, k_final)
    reales = {}
    if not legs.empty:
        con_app = legs.dropna(subset=["p_app"])
        comunes = con_app.dropna(subset=["p_mercado", "p_final"])
        reales = {"legs_decididos": int(len(legs)), "legs_con_proyeccion": int(len(con_app)),
                  "brier_app": round(brier(con_app.p_app, con_app.acierto), 4) if len(con_app) else None,
                  "legs_comparables": int(len(comunes)),
                  "comparables_brier_app": round(brier(comunes.p_app, comunes.acierto), 4) if len(comunes) else None,
                  "comparables_brier_mercado": round(brier(comunes.p_mercado, comunes.acierto), 4) if len(comunes) else None,
                  "comparables_brier_parley": round(brier(comunes.p_final, comunes.acierto), 4) if len(comunes) else None,
                  "muestra_suficiente": bool(len(comunes) >= 100)}
    resultado = {"metricas": metricas, "legs_reales": reales, "k_final": {s: round(v, 3) for s, v in k_final.items()}}
    con.execute("INSERT INTO model_runs(sport, model_version, training_cutoff, params_json, metrics_json, created_at)"
                " VALUES ('NBA', ?, ?, ?, ?, ?)",
                (config.MODELO_NBA, str(df.game_date.max()),
                 json.dumps({"k": k_final, "vida_minutos": modelo.VIDA_MINUTOS, "vida_tasa": modelo.VIDA_TASA,
                             "muestra_minima": modelo.MUESTRA_MINIMA}),
                 json.dumps(resultado), db.ahora_utc()))
    con.commit()
    resultado["calibracion"] = pd.concat(calibraciones, ignore_index=True) if calibraciones else pd.DataFrame()
    resultado["legs"] = legs
    return resultado


def main() -> None:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    with db.conectar() as con:
        r = correr(con)
    print(json.dumps({k: r[k] for k in ("metricas", "legs_reales", "k_final")}, indent=1, ensure_ascii=False))
