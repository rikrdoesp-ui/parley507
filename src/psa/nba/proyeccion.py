"""Proyecciones de un día: plantillas, lesiones, minutos manuales y escenarios de jugadores en duda."""
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import config, db
from . import lesiones, modelo, resultados

DIAS_PLANTILLA = 30  # Un jugador entra en la plantilla si jugó para ese equipo en los últimos 30 días.
MINUTOS_INESTABLES = 6.0  # Desviación de minutos (L10) a partir de la cual se marca riesgo.


def historial(con) -> pd.DataFrame:
    return modelo.agregar_combos(pd.read_sql("""SELECT game_id, player_id, team_id, season, game_date, minutes, points,
                                                rebounds, assists FROM nba_player_game_stats""", con))


def k_vigente(con) -> tuple[dict, str]:
    fila = con.execute("SELECT params_json, created_at FROM model_runs WHERE model_version = ? ORDER BY run_id DESC LIMIT 1",
                       (config.MODELO_NBA,)).fetchone()
    if not fila:
        return dict(modelo.K_DEFECTO), "dispersión por defecto: falta correr el backtest"
    return {**modelo.K_DEFECTO, **json.loads(fila[0])["k"]}, f"dispersión ajustada en el backtest del {fila[1][:10]}"


def ajuste_ausencias_vigente(con) -> tuple[float, float]:
    """(fracción de minutos repartidos, alfa de uso) elegidos en el último backtest; sin backtest, sin ajuste."""
    fila = con.execute("SELECT params_json FROM model_runs WHERE model_version = ? ORDER BY run_id DESC LIMIT 1",
                       (config.MODELO_NBA,)).fetchone()
    params = json.loads(fila[0]) if fila else {}
    return params.get("fraccion_minutos", 0.0), params.get("alfa_uso", 0.0)


def spreads_estimados(con) -> dict:
    """{(game_id, team_id): margen esperado} con la fuerza reciente de cada equipo y la localía."""
    g = pd.read_sql("""SELECT game_id, game_date, home_team_id, away_team_id, home_score, away_score FROM games
                       WHERE season_type IN ('Regular', 'NBA Cup', 'Play-In', 'Playoffs')""", con)
    return {(r.game_id, r.team_id): r.margen for r in modelo.margenes_esperados(g).itertuples()}


def proyectar_dia(con, fecha: str) -> pd.DataFrame:
    juegos = pd.read_sql("""SELECT g.game_id, g.start_time_utc, g.status, g.home_team_id, g.away_team_id,
                              h.abbreviation AS local, a.abbreviation AS visita
                            FROM games g JOIN teams h ON h.team_id = g.home_team_id JOIN teams a ON a.team_id = g.away_team_id
                            WHERE g.game_date = ? AND g.season_type IN ('Regular', 'NBA Cup', 'Play-In', 'Playoffs')""",
                         con, params=(fecha,))
    if juegos.empty:
        return pd.DataFrame()
    hist = historial(con)
    hist = hist[hist.game_date < fecha]
    corte = hist.game_date.max()
    desde = (date.fromisoformat(fecha) - timedelta(days=DIAS_PLANTILLA)).isoformat()
    ultimo = hist.sort_values("game_date").groupby("player_id").tail(1)
    recientes = ultimo[ultimo.game_date >= desde]

    objetivos = []
    for j in juegos.itertuples():
        for equipo in (j.home_team_id, j.away_team_id):
            plantilla = recientes[recientes.team_id == equipo]
            if plantilla.empty:
                # Inicio de temporada: el equipo aún no juega; se usa a quienes jugaron para él por última vez.
                # shortcut: no ve cambios de equipo del verano hasta su primer partido; luego se corrige solo.
                plantilla = ultimo[ultimo.team_id == equipo]
            for pid in plantilla.player_id:
                objetivos.append({"game_id": j.game_id, "player_id": pid, "team_id": equipo, "game_date": fecha,
                                  "objetivo": True})
    if not objetivos:
        return pd.DataFrame()
    df = modelo.con_proyeccion(pd.concat([hist.assign(objetivo=False), pd.DataFrame(objetivos)], ignore_index=True))
    temporada = config.temporada_actual(date.fromisoformat(fecha))
    jugados = df[df.objetivo.eq(False) & (df.season == temporada) & (df.minutes > 0)]
    factores = resultados.factores_temporada(jugados)  # Sesgo de la temporada, aprendido de lo ya jugado.
    df = df[df.objetivo.eq(True)].merge(juegos, on="game_id")
    nombres = dict(con.execute("SELECT player_id, full_name FROM players"))
    df["jugador"] = df.player_id.map(nombres)
    df["equipo"] = np.where(df.team_id == df.home_team_id, df.local, df.visita)
    df["partido"] = df.visita + "@" + df.local

    estados = lesiones.vigentes(con, fecha)
    por_id = {int(r.player_id): r.status for r in estados.itertuples() if pd.notna(r.player_id)}
    por_clave = dict(zip(estados.clave, estados.status)) if not estados.empty else {}
    df["estado"] = [por_id.get(p) or por_clave.get(db.clave_nombre(n)) or "" for p, n in zip(df.player_id, df.jugador)]
    ajustes = {int(p): (m, r) for p, m, r in con.execute(
        "SELECT player_id, minutes, reason FROM minutes_overrides WHERE game_date = ?", (fecha,))}

    k, nota_k = k_vigente(con)
    spreads = spreads_estimados(con)
    fraccion, alfa = ajuste_ausencias_vigente(con)
    filas = []
    for (_, equipo), g in df.groupby(["game_id", "team_id"]):
        ultimos = hist[hist.team_id == equipo].sort_values("game_date").game_id.drop_duplicates().tail(3)
        recientes = set(hist[hist.game_id.isin(ultimos) & (hist.team_id == equipo)].player_id)
        fuera = set(g[g.estado.isin(lesiones.NO_JUEGA)].player_id)
        validos = g.dropna(subset=["min_proy"] + [f"tasa_{s}" for s in modelo.ESTADISTICAS])
        presentes = {r.player_id: (r.min_proy, {s: getattr(r, f"tasa_{s}") for s in modelo.ESTADISTICAS})
                     for r in validos.itertuples() if r.player_id not in fuera}
        # Solo cuentan las bajas nuevas (jugó en alguno de los 3 últimos partidos): las largas ya están en las medias.
        produccion = {r.player_id: (r.min_proy, {s: getattr(r, f"mu_{s}") for s in modelo.ESTADISTICAS})
                      for r in validos.itertuples()}
        nuevas = {p: produccion[p] for p in fuera & recientes if p in produccion}

        def escenario(sin: dict) -> tuple[dict, dict]:
            pres = {p: v for p, v in presentes.items() if p not in sin}
            mins, medias = modelo.ajustar_ausencias(pres, {**nuevas, **sin}, alfa, fraccion)
            for p, (m, _) in ajustes.items():  # Minutos a mano: la media se escala con ellos.
                if p in mins and mins[p]:
                    medias[p] = {s: v * m / mins[p] for s, v in medias[p].items()}
                    mins[p] = m
            return mins, medias

        escenarios = {"base": escenario({})}
        for d in g[g.estado.isin(lesiones.DUDA) & g.player_id.isin(list(presentes))].itertuples():
            escenarios[f"sin {d.jugador}"] = escenario({d.player_id: produccion[d.player_id]})
        # Jugadores sin muestra suficiente: se listan sin proyección.
        sin_muestra = {r.player_id: (r.min_proy, {}) for r in g.itertuples()
                       if r.player_id not in presentes and r.player_id not in fuera and pd.notna(r.min_proy)}
        for nombre, (mins, medias) in escenarios.items():
            mins = {**{p: m for p, (m, _) in sin_muestra.items()}, **mins}
            for r in g[g.player_id.isin(list(mins))].itertuples():
                notas = [nota_k]
                if r.player_id in ajustes:
                    notas.append(f"minutos a mano: {ajustes[r.player_id][1]}")
                if (nuevas or nombre != "base") and r.player_id in medias and alfa + fraccion > 0:
                    notas.append(f"ajuste por {len(nuevas) + (nombre != 'base')} baja(s) de rotación")
                if pd.notna(r.min_sd) and r.min_sd > MINUTOS_INESTABLES:
                    notas.append(f"minutos inestables (desv. {r.min_sd:.1f})")
                spread = spreads.get((r.game_id, r.team_id), 0.0)
                if abs(spread) >= modelo.UMBRAL_PALIZA and mins.get(r.player_id, 0) >= 28:
                    notas.append(f"riesgo de paliza (spread estimado {spread:+.0f})")
                if r.n_previos < modelo.MUESTRA_MINIMA:
                    notas.append("muestra insuficiente")
                fila = {"game_id": r.game_id, "game_date": fecha, "partido": r.partido, "hora_utc": r.start_time_utc,
                        "team_id": r.team_id, "equipo": r.equipo, "player_id": int(r.player_id), "jugador": r.jugador,
                        "estado": r.estado, "escenario": nombre, "minutos": mins[r.player_id], "min_sd": r.min_sd,
                        "n_previos": int(r.n_previos), "data_cutoff": corte, "notas": "; ".join(notas), "spread": spread}
                for stat in modelo.TODAS:
                    if stat in modelo.COMBOS:  # Suma de las partes ya corregidas.
                        mu = sum(fila[f"mu_{s}"] for s in modelo.COMBOS[stat])
                    else:
                        mu = medias.get(r.player_id, {}).get(stat, np.nan) * factores[stat]
                    k_fila = modelo.k_para(k[stat], mins[r.player_id])
                    bajo, alto = modelo.intervalo(mu, k_fila) if pd.notna(mu) else (np.nan, np.nan)
                    fila.update({f"mu_{stat}": mu, f"k_{stat}": k_fila, f"p10_{stat}": bajo, f"p90_{stat}": alto})
                filas.append(fila)
    salida = pd.DataFrame(filas)
    salida.attrs["factores"] = factores
    return salida


def guardar(con, df: pd.DataFrame) -> int:
    ahora = db.ahora_utc()
    filas = [(r.game_id, r.game_date, r.player_id, r.team_id, mercado, r.escenario, r.minutos, getattr(r, f"mu_{stat}"),
              getattr(r, f"k_{stat}"), getattr(r, f"p10_{stat}"), getattr(r, f"p90_{stat}"), r.n_previos, r.min_sd,
              config.MODELO_NBA, ahora, r.data_cutoff, r.notas)
             for r in df.itertuples() for mercado, stat in config.MERCADOS_NBA.items()]
    con.executemany("""INSERT INTO predictions(game_id, game_date, player_id, team_id, market, scenario, minutes,
                       projected_mean, dispersion, lower_interval, upper_interval, sample_games, minutes_sd, model_version,
                       generated_at, data_cutoff, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [tuple(None if isinstance(v, float) and np.isnan(v) else v for v in f) for f in filas])
    return len(filas)


def ultimas(con, fecha: str) -> pd.DataFrame:
    """Las proyecciones guardadas más recientes del día, en formato ancho."""
    df = pd.read_sql("""SELECT p.*, pl.full_name AS jugador, t.abbreviation AS equipo FROM predictions p
                        JOIN players pl USING(player_id) LEFT JOIN teams t ON t.team_id = p.team_id
                        WHERE p.game_date = ? AND p.generated_at =
                          (SELECT MAX(generated_at) FROM predictions WHERE game_date = ?)""", con, params=(fecha, fecha))
    return df
