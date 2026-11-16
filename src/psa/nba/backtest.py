"""Backtest walk-forward del modelo NBA.

Para cada temporada de prueba, la dispersión k se ajusta solo con partidos anteriores a su inicio, y cada
proyección usa solo partidos anteriores a ese juego. Mide:
- Error de la media contra el resultado (MAE), frente a la media L10 como línea base.
- Calibración de P(over) en una línea sintética (media L10 redondeada a x.5), frente al acierto L10 a esa línea.
  La línea sintética está etiquetada: no es una línea real de casa.
- Cobertura del intervalo 10-90 (debería rondar 80 %).
- Legs reales de /parley: Brier de la app frente a la probabilidad de mercado y la final de /parley.
- Partidos con ausencias de rotación: elige qué parte de los minutos libres repartir y cuánto efecto de uso aplicar.
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
    for stat in modelo.TODAS:
        e = entreno.dropna(subset=[f"mu_{stat}", f"l10_{stat}"])
        p = prueba.dropna(subset=[f"mu_{stat}", f"l10_{stat}"])
        if e.empty or p.empty:
            continue
        ks[stat] = modelo.ajustar_k_tramos(e.min_proy, e[f"mu_{stat}"], e[stat])
        k = modelo.k_para(ks[stat], p.min_proy.to_numpy())
        y, mu = p[stat].to_numpy(), p[f"mu_{stat}"].to_numpy()
        linea = np.floor(p[f"l10_{stat}"].to_numpy()) + 0.5
        sobre = (y > linea).astype(float)
        p_modelo = modelo.p_over(mu, k, linea)
        lags = p[[f"lag{i}_{stat}" for i in range(1, 11)]].to_numpy()
        # Un partido que no existe (menos de 10 previos) no cuenta como "no superó la línea".
        p_l10 = np.nanmean(np.where(np.isnan(lags), np.nan, lags > linea[:, None]), axis=1)
        bajo, alto = modelo.intervalo(mu, k)
        metricas[stat] = {"n": int(len(p)), "k": ks[stat],
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
            k = modelo.k_para(ks_por_temporada.get(cand.season.iloc[0], {}).get(stat, k_final[stat]), cand.min_proy.iloc[0])
            if pd.notna(mu):
                p = float(modelo.p_over(mu, k, leg.linea))
                p_app = p if leg.lado == "over" else float(modelo.p_under(mu, k, leg.linea))
        filas.append({**leg._asdict(), "p_app": p_app, "acierto": float(leg.resultado == "gano")})
    return pd.DataFrame(filas)


# (fracción de minutos repartidos, alfa de uso). (0, 0) = sin ajuste.
COMBOS = [(f, a) for f in (0.0, 0.25, 0.5, 1.0) for a in (0.0, 0.25, 0.5)]
MIN_AUSENTE = 15  # Solo cuenta como ausencia un jugador de rotación (15+ min en su último partido).


def filas_con_ausencias(df: pd.DataFrame) -> pd.DataFrame:
    """Reconstruye cada partido histórico en que faltó un jugador de rotación que había jugado en alguno de los 3
    partidos previos del equipo (y hace 10 días o menos). Por cada presente, guarda la media sin ajustar y la
    ajustada con cada alfa. Todo con información anterior al partido, salvo saber quién no jugó (que en vivo da el
    reporte de lesiones).
    """
    df = df.sort_values(["player_id", "game_date", "game_id"])
    jugador = df["player_id"]
    df["min_ultimo"] = df.groupby("player_id", sort=False)["minutes"].transform(
        lambda s: s.ewm(halflife=modelo.VIDA_MINUTOS).mean())
    for stat in modelo.ESTADISTICAS:
        df[f"prod_{stat}"] = df.groupby("player_id", sort=False)[stat].transform(
            lambda s: s.rolling(10, min_periods=3).mean())
    filas = []
    for _, g in df.sort_values(["game_date", "game_id"]).groupby("team_id", sort=False):
        ultimo, previos = {}, []
        for juego, filas_juego in g.groupby("game_id", sort=False):
            fecha = pd.Timestamp(filas_juego.game_date.iloc[0])
            presentes = set(filas_juego.player_id)
            ausentes = {p for p in set().union(*previos[-3:]) - presentes if p in ultimo
                        and ultimo[p][1] >= MIN_AUSENTE and (fecha - ultimo[p][0]).days <= 10} if previos else set()
            validos = filas_juego.dropna(subset=["min_proy"] + [f"tasa_{s}" for s in modelo.ESTADISTICAS])
            if ausentes and not validos.empty:
                pres = {r.player_id: (r.min_proy, {s: getattr(r, f"tasa_{s}") for s in modelo.ESTADISTICAS})
                        for r in validos.itertuples()}
                aus = {p: (ultimo[p][1], ultimo[p][2]) for p in ausentes}
                ajustes = {c: modelo.ajustar_ausencias(pres, aus, c[1], c[0]) for c in COMBOS}
                for r in validos.itertuples():
                    fila = {"season": r.season, "minutes": r.minutes, "min_proy": r.min_proy,
                            **{f"min_{f}": ajustes[(f, 0.0)][0][r.player_id] for f, a in COMBOS if a == 0.0}}
                    for s in modelo.ESTADISTICAS:
                        fila.update({s: getattr(r, s), f"l10_{s}": getattr(r, f"l10_{s}"), f"mu_base_{s}": getattr(r, f"mu_{s}")})
                        for c in COMBOS:
                            fila[f"mu_{c[0]}_{c[1]}_{s}"] = ajustes[c][1][r.player_id][s]
                    filas.append(fila)
            for r in filas_juego.itertuples():
                ultimo[r.player_id] = (fecha, r.min_ultimo, {s: getattr(r, f"prod_{s}") for s in modelo.ESTADISTICAS})
            previos.append(presentes)
    return pd.DataFrame(filas)


def evaluar_ausencias(df: pd.DataFrame, ks: dict) -> dict:
    """Error de minutos y de medias, y Brier en línea sintética, sin ajuste y con cada alfa, por temporada."""
    filas = filas_con_ausencias(df)
    salida = {}
    for temporada, f in filas.groupby("season"):
        if temporada not in ks:
            continue
        m = {"n_jugador_partido": int(len(f)),
             "mae_minutos": {str(fr): round(float((f.minutes - f[f"min_{fr}"]).abs().mean()), 3)
                             for fr, a in COMBOS if a == 0.0}}
        for s in modelo.ESTADISTICAS:
            d = f.dropna(subset=[f"l10_{s}", f"mu_base_{s}"])
            linea = np.floor(d[f"l10_{s}"].to_numpy()) + 0.5
            sobre = (d[s].to_numpy() > linea).astype(float)
            m[s] = {}
            for c in COMBOS:
                mu = d[f"mu_{c[0]}_{c[1]}_{s}"]
                m[s][f"{c[0]}_{c[1]}"] = {"mae": round(float((d[s] - mu).abs().mean()), 3),
                                          "brier": round(brier(modelo.p_over(mu, modelo.k_para(ks[temporada][s], d[f"min_{c[0]}"].to_numpy()), linea), sobre), 4)}
        salida[temporada] = m
    return salida


def elegir_combo(ausencias: dict) -> tuple[float, float]:
    """(fracción, alfa) con menor Brier medio en la primera temporada de prueba; la segunda queda como confirmación."""
    if not ausencias:
        return 0.0, 0.0
    primera = ausencias[min(ausencias)]
    return min(COMBOS, key=lambda c: sum(primera[s][f"{c[0]}_{c[1]}"]["brier"] for s in modelo.ESTADISTICAS))


def correr(con) -> dict:
    crudo = modelo.con_proyeccion(historial(con))
    temporadas = sorted(crudo.season.unique())
    # La capa y la k que usan las proyecciones del día se ajustan con todo lo disponible.
    capa_final = modelo.ajustar_capa(crudo)
    final = modelo.aplicar_capa(crudo, capa_final)
    # Cada temporada de prueba lleva la capa ajustada solo con lo anterior a su inicio. La primera, que solo
    # sirve de entrenamiento de la dispersión, usa la suya propia (nada posterior).
    capas = {t: modelo.ajustar_capa(crudo[crudo.game_date < crudo.loc[crudo.season == t, "game_date"].min()])
             for t in temporadas[1:]}
    capas[temporadas[0]] = modelo.ajustar_capa(crudo[crudo.season == temporadas[0]])
    df = pd.concat([modelo.aplicar_capa(crudo[crudo.season == t], capas[t]) for t in temporadas], ignore_index=True)
    metricas, calibraciones, ks = {}, [], {}
    for t in temporadas[1:]:
        ks[t], m, c = evaluar_temporada(df, t)
        metricas[t] = m
        calibraciones.append(c)
    k_final = {s: modelo.ajustar_k_tramos(d.min_proy, d[f"mu_{s}"], d[s])
               for s in modelo.TODAS for d in [final.dropna(subset=[f"mu_{s}", s])]}
    ausencias = evaluar_ausencias(df, ks)
    fraccion, alfa = elegir_combo(ausencias)
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
    resultado = {"metricas": metricas, "legs_reales": reales, "k_final": k_final,
                 "ausencias": ausencias, "fraccion_minutos": fraccion, "alfa_uso": alfa}
    con.execute("INSERT INTO model_runs(sport, model_version, training_cutoff, params_json, metrics_json, created_at)"
                " VALUES ('NBA', ?, ?, ?, ?, ?)",
                (config.MODELO_NBA, str(df.game_date.max()),
                 json.dumps({"k": k_final, "capa": capa_final, "correlacion": modelo.correlaciones(final, k_final),
                             "vida_minutos": modelo.VIDA_MINUTOS, "vida_tasa": modelo.VIDA_TASA,
                             "muestra_minima": modelo.MUESTRA_MINIMA, "fraccion_minutos": fraccion, "alfa_uso": alfa}),
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
    print(json.dumps({k: r[k] for k in ("metricas", "legs_reales", "k_final", "fraccion_minutos", "alfa_uso")},
                     indent=1, ensure_ascii=False))

