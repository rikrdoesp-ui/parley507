"""Conector NBA vía nba_api (endpoints de stats.nba.com).

Límites: no es una API pública documentada; bloquea con frecuencia IPs de nube y responde lento.
Se pausa PAUSA_API s entre llamadas y se reintenta con espera creciente. La base hace de caché:
las temporadas pasadas se descargan una vez.
"""
import time

import pandas as pd
from nba_api.stats.endpoints import boxscoretraditionalv3, leaguegamelog, scheduleleaguev2
from nba_api.stats.static import teams as equipos_estaticos

from .. import config, db

URL = "https://stats.nba.com"
LICENCIA = "Uso personal; términos de NBA.com"
TIPOS = {"001": "Pretemporada", "002": "Regular", "003": "All-Star", "004": "Playoffs", "005": "Play-In", "006": "NBA Cup"}
ESTADOS = {1: "programado", 2: "en vivo", 3: "final"}


def llamar(endpoint, intentos: int = 3, **parametros) -> list[pd.DataFrame]:
    for intento in range(intentos):
        try:
            time.sleep(config.PAUSA_API)
            return endpoint(timeout=60, **parametros).get_data_frames()
        except Exception as error:  # nba_api lanza errores de requests y de JSON sin una clase común.
            if intento == intentos - 1:
                raise RuntimeError(f"stats.nba.com no respondió ({endpoint.__name__}): {error}") from error
            time.sleep(5 * (intento + 1))


def cargar_equipos(con) -> None:
    con.executemany("INSERT OR REPLACE INTO teams VALUES (?, ?, ?)",
                    [(e["id"], e["abbreviation"], e["full_name"]) for e in equipos_estaticos.get_teams()])


def cargar_dorsales(con, temporada: str) -> int:
    """Dorsal de cada jugador (PlayerIndex, una llamada). Se pide una vez al día: cambia muy poco."""
    hoy = db.ahora_utc()[:10]
    if con.execute("SELECT 1 FROM nba_jerseys WHERE captured_at >= ? LIMIT 1", (hoy,)).fetchone():
        return 0
    from nba_api.stats.endpoints import playerindex
    indice = llamar(playerindex.PlayerIndex, season=temporada)[0]
    filas = [(int(r.PERSON_ID), str(r.JERSEY_NUMBER).strip(), db.ahora_utc()) for r in indice.itertuples()
             if r.JERSEY_NUMBER is not None and str(r.JERSEY_NUMBER).strip() not in ("", "nan", "None")]
    con.executemany("INSERT OR REPLACE INTO nba_jerseys VALUES (?, ?, ?)", filas)
    return len(filas)


def minutos(texto) -> float | None:
    """'31:47' -> 31.78; vacío -> None."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)) or str(texto).strip() == "":
        return None
    partes = str(texto).split(":")
    return int(partes[0]) + (int(partes[1]) / 60 if len(partes) > 1 else 0)


def cargar_calendario(con, temporada: str) -> int:
    s = llamar(scheduleleaguev2.ScheduleLeagueV2, season=temporada)[0]
    fuente = db.registrar_fuente(con, "NBA (nba_api)", f"ScheduleLeagueV2 {temporada}", URL, LICENCIA)
    filas = []
    for _, g in s.iterrows():
        estado = "pospuesto" if g["postponedStatus"] == "Y" else ESTADOS.get(int(g["gameStatus"]), str(g["gameStatus"]))
        final = int(g["gameStatus"]) == 3
        filas.append((g["gameId"], temporada, TIPOS.get(g["gameId"][:3], "Otro"), g["gameDateEst"][:10],
                      g["gameDateTimeUTC"], int(g["homeTeam_teamId"]), int(g["awayTeam_teamId"]), g["arenaName"],
                      int(str(g["isNeutral"]).lower() == "true"), estado,
                      int(g["homeTeam_score"]) if final else None, int(g["awayTeam_score"]) if final else None, fuente))
    con.executemany("""
        INSERT INTO games(game_id, season, season_type, game_date, start_time_utc, home_team_id, away_team_id, venue,
                          neutral_site, status, home_score, away_score, source_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(game_id) DO UPDATE SET game_date=excluded.game_date, start_time_utc=excluded.start_time_utc,
          venue=excluded.venue, neutral_site=excluded.neutral_site, status=excluded.status,
          home_score=COALESCE(excluded.home_score, games.home_score),
          away_score=COALESCE(excluded.away_score, games.away_score), source_id=excluded.source_id""", filas)
    return len(filas)


def cargar_logs(con, temporada: str) -> int:
    """Box scores de jugadores (temporada regular) y prórrogas por partido."""
    jugadores = llamar(leaguegamelog.LeagueGameLog, season=temporada, player_or_team_abbreviation="P",
                       season_type_all_star="Regular Season")[0]
    equipos = llamar(leaguegamelog.LeagueGameLog, season=temporada, player_or_team_abbreviation="T",
                     season_type_all_star="Regular Season")[0]
    fuente = db.registrar_fuente(con, "NBA (nba_api)", f"LeagueGameLog Regular Season {temporada}", URL, LICENCIA)

    con.executemany("INSERT OR REPLACE INTO players VALUES (?, ?, ?)",
                    {(int(r.PLAYER_ID), r.PLAYER_NAME, db.clave_nombre(r.PLAYER_NAME)) for r in jugadores.itertuples()})
    columnas = ["MIN", "PTS", "REB", "OREB", "DREB", "AST", "STL", "BLK", "TOV", "FGM", "FGA", "FG3M", "FG3A", "FTM",
                "FTA", "PF", "PLUS_MINUS"]
    filas = []
    for r in jugadores.itertuples():
        valores = [None if pd.isna(getattr(r, c)) else float(getattr(r, c)) for c in columnas]
        if valores[0] is not None and not 0 <= valores[0] <= 70:
            db.calidad(con, "nba_player_game_stats", f"{r.GAME_ID}/{r.PLAYER_ID}", "minutos_imposibles", "alta",
                       f"{r.PLAYER_NAME}: {valores[0]} minutos.")
        # El game log no dice si fue titular: queda NULL (desconocido), no 0.
        filas.append((r.GAME_ID, int(r.PLAYER_ID), int(r.TEAM_ID), temporada, r.GAME_DATE, *valores, None, fuente))
    con.executemany(f"INSERT OR REPLACE INTO nba_player_game_stats VALUES ({','.join('?' * 24)})", filas)

    for (juego, fecha), g in equipos.groupby(["GAME_ID", "GAME_DATE"]):
        local = g[g.MATCHUP.str.contains("vs.")]
        visita = g[g.MATCHUP.str.contains("@")]
        minutos_equipo = int(g.MIN.max())
        prorrogas = (minutos_equipo - 240) // 25 if minutos_equipo >= 240 else None
        if minutos_equipo < 240 or (minutos_equipo - 240) % 25:
            db.calidad(con, "games", juego, "minutos_de_equipo", "media",
                       f"{fecha}: {minutos_equipo} min de equipo; posible partido suspendido o reanudado.")
        if len(local) != 1 or len(visita) != 1:
            db.calidad(con, "games", juego, "local_visitante", "media", "No se pudo determinar local y visitante.")
            continue
        con.execute("""
            INSERT INTO games(game_id, season, season_type, game_date, home_team_id, away_team_id, status, home_score,
                              away_score, overtime_periods, source_id)
            VALUES (?, ?, 'Regular', ?, ?, ?, 'final', ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET status='final', home_score=excluded.home_score,
              away_score=excluded.away_score, overtime_periods=excluded.overtime_periods""",
                    (juego, temporada, fecha, int(local.TEAM_ID.iloc[0]), int(visita.TEAM_ID.iloc[0]),
                     int(local.PTS.iloc[0]), int(visita.PTS.iloc[0]), prorrogas, fuente))
    return len(filas)


def cargar_regulacion(con, limite: int | None = None) -> int:
    """Estadísticas sin prórroga de los partidos con OT que aún no las tienen."""
    pendientes = [r[0] for r in con.execute("""
        SELECT game_id FROM games WHERE overtime_periods > 0
          AND game_id NOT IN (SELECT DISTINCT game_id FROM nba_player_game_stats_regulation)
        ORDER BY game_date DESC""")]
    for juego in pendientes[:limite]:
        try:
            caja = llamar(boxscoretraditionalv3.BoxScoreTraditionalV3, game_id=juego, start_period=1, end_period=4,
                          range_type=1, start_range=0, end_range=0, intentos=2)[0]
        except RuntimeError as error:  # Box score aún no publicado: queda pendiente y se reintenta la próxima vez.
            db.calidad(con, "nba_player_game_stats_regulation", juego, "boxscore_ot", "media", str(error))
            continue
        fuente = db.registrar_fuente(con, "NBA (nba_api)", f"BoxScoreTraditionalV3 periodos 1-4 {juego}", URL, LICENCIA)
        con.executemany("INSERT OR REPLACE INTO nba_player_game_stats_regulation VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(juego, int(r.personId), minutos(r.minutes), r.points, r.reboundsTotal, r.assists,
                          r.threePointersMade, r.steals, r.blocks, fuente)
                         for r in caja.itertuples() if minutos(r.minutes)])  # Sin minutos = no jugó: no se guarda.
        con.commit()
    return len(pendientes[:limite])
