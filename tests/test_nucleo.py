import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from psa import db, odds, parley_io
from psa.nba import lesiones, modelo

PARLEY = Path.home() / ".claude" / "skills" / "parley" / "scripts" / "parley.py"


# --- Cuotas -----------------------------------------------------------------------

def test_americana_y_decimal():
    assert odds.a_decimal("-150") == pytest.approx(1 + 100 / 150)
    assert odds.a_decimal("+120") == pytest.approx(2.2)
    assert odds.a_decimal("EVEN") == 2.0
    assert odds.a_decimal("1.85") == 1.85
    with pytest.raises(ValueError):
        odds.a_decimal("0.9")


def test_sin_margen_suma_uno_y_reparte_el_margen():
    p = odds.sin_margen(1.80, 2.00)
    assert p + odds.sin_margen(2.00, 1.80) == pytest.approx(1, abs=1e-9)
    assert 0.5 < p < 1 / 1.80  # Sin margen, el favorito queda por debajo de su implícita.


@pytest.mark.skipif(not PARLEY.exists(), reason="skill /parley no instalada")
def test_mismo_metodo_que_parley():
    spec = importlib.util.spec_from_file_location("parley", PARLEY)
    parley = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parley)
    for a, b in [(1.8, 2.0), (1.5, 2.6), (1.95, 1.95), (3.4, 1.3)]:
        assert odds.sin_margen(a, b) == pytest.approx(parley.sin_margen(a, b), abs=1e-12)


def test_valor_esperado():
    assert odds.valor_esperado(0.55, 2.0) == pytest.approx(0.10)


# --- Modelo -----------------------------------------------------------------------

def historial_sintetico(n=12):
    filas = [{"game_id": f"G{i:02d}", "player_id": 1, "game_date": f"2026-01-{i + 1:02d}", "minutes": 30.0,
              "points": 20.0 + i % 3, "rebounds": 5.0, "assists": 4.0} for i in range(n)]
    return pd.DataFrame(filas)


def test_sin_fuga_el_partido_no_entra_en_su_propia_proyeccion():
    base = modelo.con_proyeccion(historial_sintetico())
    cambiado = historial_sintetico()
    cambiado.loc[11, ["points", "minutes"]] = [99.0, 48.0]
    otro = modelo.con_proyeccion(cambiado)
    assert base.loc[11, "mu_points"] == pytest.approx(otro.loc[11, "mu_points"])
    assert base.loc[11, "min_proy"] == pytest.approx(otro.loc[11, "min_proy"])


def test_muestra_minima():
    df = modelo.con_proyeccion(historial_sintetico())
    assert df.loc[: modelo.MUESTRA_MINIMA - 1, "mu_points"].isna().all()
    assert df.loc[modelo.MUESTRA_MINIMA:, "mu_points"].notna().all()


def test_over_y_under_suman_uno_en_media_linea_y_excluyen_push():
    assert modelo.p_over(20, 8, 19.5) + modelo.p_under(20, 8, 19.5) == pytest.approx(1)
    assert modelo.p_over(20, 8, 20) + modelo.p_under(20, 8, 20) < 1


def test_ajustar_k_recupera_la_dispersion():
    azar = np.random.default_rng(1)
    mu = azar.uniform(5, 30, 40_000)
    y = azar.negative_binomial(6.0, 6.0 / (6.0 + mu))
    assert modelo.ajustar_k(mu, y) == pytest.approx(6.0, rel=0.1)


def test_redistribuir_reparte_y_respeta_tope():
    nuevos = modelo.redistribuir({1: 10, 2: 30, 3: 20, 4: 5}, {1})
    assert 1 not in nuevos
    assert nuevos[4] == 5  # Fuera de la rotación no recibe minutos.
    assert nuevos[2] == pytest.approx(30 + 10 * 30 / 50)
    assert nuevos[3] == pytest.approx(20 + 10 * 20 / 50)
    assert modelo.redistribuir({1: 40, 2: 38}, {1})[2] == modelo.TOPE_MINUTOS


def test_efecto_de_uso_va_al_que_mas_produce_y_tiene_tope():
    presentes = {1: (30, {"points": 0.6, "rebounds": 0.2, "assists": 0.25}),
                 2: (30, {"points": 0.4, "rebounds": 0.3, "assists": 0.05})}
    ausente = {9: (34, {"points": 24, "rebounds": 5, "assists": 7})}
    mins, sin = modelo.ajustar_ausencias(presentes, ausente, alfa=0.0, fraccion=0.0)
    assert mins == {1: 30, 2: 30} and sin[1]["assists"] == pytest.approx(7.5)  # Sin ajuste: igual que antes.
    _, con = modelo.ajustar_ausencias(presentes, ausente, alfa=0.25, fraccion=0.0)
    ganancia = {p: con[p]["assists"] - sin[p]["assists"] for p in (1, 2)}
    assert ganancia[1] > ganancia[2] > 0  # El que más asiste se lleva más asistencias.
    assert ganancia[1] + ganancia[2] == pytest.approx(0.25 * 7)
    _, todo = modelo.ajustar_ausencias(presentes, ausente, alfa=1.0, fraccion=0.0)
    assert todo[1]["points"] <= sin[1]["points"] * (1 + modelo.TOPE_AUMENTO_USO) + 1e-9


def test_spread_estimado_sin_fuga_y_con_localia():
    juegos = pd.DataFrame({"game_id": ["G1", "G2", "G3"], "game_date": ["2026-01-01", "2026-01-02", "2026-01-03"],
                           "home_team_id": [1, 1, 2], "away_team_id": [2, 2, 1],
                           "home_score": [120, 110, None], "away_score": [100, 100, None]})
    m = modelo.margenes_esperados(juegos).set_index(["game_id", "team_id"]).margen
    assert m[("G1", 1)] == pytest.approx(modelo.VENTAJA_LOCAL)  # Sin historia: solo la localía.
    assert m[("G1", 1)] == pytest.approx(-m[("G1", 2)])
    assert m[("G3", 1)] > 0  # El equipo 1 ganó sus dos partidos previos: favorito aun de visita.
    cambiado = juegos.copy()
    cambiado.loc[1, "home_score"] = 200  # El resultado de G2 no cambia el spread de G2.
    assert modelo.margenes_esperados(cambiado).set_index(["game_id", "team_id"]).margen[("G2", 1)] == pytest.approx(m[("G2", 1)])


def test_redistribuir_no_infla_a_un_suplente():
    # Tres bajas que liberan 90 minutos: nadie gana más del máximo, aunque sobren minutos.
    nuevos = modelo.redistribuir({1: 34, 2: 30, 3: 26, 4: 30, 5: 12}, {1, 2, 3})
    assert nuevos[5] == pytest.approx(12 + modelo.GANANCIA_MAXIMA)
    assert nuevos[4] == pytest.approx(30 + modelo.GANANCIA_MAXIMA)


# --- Lesiones ---------------------------------------------------------------------

def palabra(texto, x, top):
    return {"text": texto, "x0": x, "top": top}


ENCABEZADO = [palabra(t, x, 50) for t, x in [("GameDate", 23), ("GameTime", 120), ("Matchup", 200), ("Team", 264),
                                            ("PlayerName", 425), ("CurrentStatus", 586), ("Reason", 666)]]


def test_pagina_con_motivo_partido_y_titulo():
    palabras = ENCABEZADO + [
        palabra("Injury", 289, 20), palabra("Report:", 356, 20),
        palabra("Injury/Illness-RightFootPlantar", 667, 94),
        palabra("11/15/2026", 24, 100), palabra("01:00(ET)", 121, 100), palabra("IND@PHI", 201, 100),
        palabra("Philadelphia76ers", 265, 100), palabra("Embiid,Joel", 426, 100), palabra("Out", 587, 100),
        palabra("FasciaInjuryManagement", 667, 106),
        palabra("James,Bronny", 426, 120), palabra("Questionable", 587, 120), palabra("Injury/Illness-Illness", 667, 120),
    ]
    filas, _ = lesiones.filas_de_palabras(palabras, None)
    jugadores = lesiones.jugadores_de_pagina(filas, {"GameDate": None, "GameTime": None, "Matchup": None, "Team": None})
    assert [j["PlayerName"] for j in jugadores] == ["Embiid,Joel", "James,Bronny"]
    assert jugadores[0]["Reason"] == "Injury/Illness-RightFootPlantarFasciaInjuryManagement"
    assert jugadores[1]["Reason"] == "Injury/Illness-Illness"
    assert jugadores[1]["Team"] == "Philadelphia76ers"  # El equipo sigue de la fila anterior.


def test_vigentes_usa_el_ultimo_pdf_y_la_correccion_manual(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    for hora, jugadores in (("09:00", [("Ana Uno", "Out"), ("Beto Dos", "Questionable")]), ("17:00", [("Beto Dos", "Out")])):
        fuente = db.registrar_fuente(con, "NBA", f"PDF {hora}", f"url-{hora}")
        for nombre, estado in jugadores:
            con.execute("INSERT INTO nba_injuries(game_date, player_name, status, reported_at, entry_method, source_id,"
                        " captured_at) VALUES ('2026-11-15', ?, ?, ?, 'PDF', ?, ?)", (nombre, estado, hora, fuente, hora))
    lesiones.corregir(con, "2026-11-15", "Ana Uno", None, None, "Available", "volvió a entrenar")
    lesiones.corregir(con, "2026-11-15", "Beto Dos", None, None, "Questionable", "x")
    con.execute("UPDATE nba_injuries SET captured_at = '00:00' WHERE entry_method = 'MANUAL' AND player_name = 'Beto Dos'")
    vig = dict(zip(lesiones.vigentes(con, "2026-11-15").player_name, lesiones.vigentes(con, "2026-11-15").status))
    assert vig == {"Ana Uno": "Available", "Beto Dos": "Questionable"}  # La corrección manual manda ese día.
    con.execute("DELETE FROM nba_injuries WHERE entry_method = 'MANUAL'")
    vig = dict(zip(lesiones.vigentes(con, "2026-11-15").player_name, lesiones.vigentes(con, "2026-11-15").status))
    assert vig == {"Beto Dos": "Out"}  # Ana ya no figura en el reporte de las 17:00.


def test_formato_cambiado():
    with pytest.raises(lesiones.FormatoCambiado):
        lesiones.filas_de_palabras([palabra("Otra", 10, 10)], None)


def test_nombres():
    assert lesiones.nombre_natural("McConnell,T.J.") == "T.J. McConnell"
    assert db.clave_nombre("Luka Dončić") == db.clave_nombre("luka doncic")
    assert db.clave_nombre(lesiones.nombre_natural("JacksonJr.,Jaren")) == db.clave_nombre("Jaren Jackson Jr.")


# --- Intercambio con /parley -----------------------------------------------------

def test_referencia_consenso_y_minimo_de_casas():
    texto = "#MIL@NY\nM. Bridges|puntos 18.5 -110/-110*3;rebotes 4.5 -120/100*2\n"
    filas = parley_io.parsear_referencia(texto)
    assert len(filas) == 1  # Rebotes solo tiene 2 casas.
    assert filas[0]["p_over"] == pytest.approx(0.5)
    assert parley_io.equipos_partido(filas[0]["partido"]) == {"MIL", "NYK"}


def test_lineas_de_stake_con_precio():
    filas = parley_io.parsear_lineas("#SA@UTAH\nVictor Wembanyama|puntos 27.5 1.82 1.85;rebotes 10.5 -110 +100\n")
    assert [f["mercado"] for f in filas] == ["puntos", "rebotes"]
    assert filas[1]["sobre"] == pytest.approx(1 + 100 / 110) and filas[1]["debajo"] == 2.0
    assert parley_io.equipos_partido(filas[0]["partido"]) == {"SAS", "UTA"}
    from psa.nba import props
    assert props.es_consenso("Consenso BettingPros sin margen (5 casas)") and not props.es_consenso("Stake")


def test_mezcla_anclada_al_mercado():
    from psa.nba import props
    p_mkt = odds.sin_margen(1.90, 1.90)
    assert props.mezclar(p_mkt, 0.90, "dos_lados") == pytest.approx(0.54)  # Tope de 4 puntos aunque el modelo diga 90 %.
    assert props.mezclar(p_mkt, 0.52, "dos_lados") == pytest.approx(0.505)  # Dentro del tope: 25 % del camino.
    assert props.mezclar(p_mkt, 0.10, "consenso") == pytest.approx(0.47)
    p, fuente = props.mercado_over(1.90, None, "Stake")
    assert fuente == "un_lado" and p == pytest.approx((1 / 1.90) / 1.08)


def test_resolver_jugador_abreviado_y_ambiguo():
    plantilla = pd.DataFrame({"player_id": [1, 2, 3], "jugador": ["Mikal Bridges", "Jalen Williams", "Jaylin Williams"]})
    assert parley_io.resolver_jugador("M. Bridges", plantilla) == 1
    assert parley_io.resolver_jugador("Jalen Williams", plantilla) == 2
    assert parley_io.resolver_jugador("J. Williams", plantilla) is None


# --- Resultados ---------------------------------------------------------------------

def test_factor_sesgo_se_encoge_con_poca_muestra_y_tiene_tope():
    from psa.nba import resultados
    assert resultados.factor_sesgo(110, 100, 0) == 1.0
    assert 1 < resultados.factor_sesgo(110, 100, 100) < 1.01  # Poca muestra: casi no corrige.
    assert resultados.factor_sesgo(200, 100, 10**7) == pytest.approx(1 + resultados.TOPE_FACTOR)


def test_calificar_usa_la_proyeccion_previa_y_guarda_el_factor_usado(tmp_path):
    from psa.nba import resultados
    con = db.conectar(tmp_path / "t.sqlite")
    con.execute("INSERT INTO players VALUES (1, 'Ana Pérez', 'ana perez')")
    con.execute("INSERT INTO games(game_id, season, season_type, game_date, start_time_utc, status) "
                "VALUES ('g1', '2026-27', 'Regular', '2026-11-14', '2026-11-15T00:00:00+00:00', 'en vivo')")
    con.execute("INSERT INTO nba_player_game_stats(game_id, player_id, team_id, season, game_date, minutes, points, "
                "rebounds, assists, source_id) VALUES ('g1', 1, 9, '2026-27', '2026-11-14', 30, 25, 5, 4, 0)")
    for generado, media in (("2026-11-14T20:00:00+00:00", 22.0), ("2026-11-15T03:00:00+00:00", 99.0)):  # Antes / después.
        con.execute("INSERT INTO predictions(game_id, game_date, player_id, market, scenario, projected_mean, dispersion,"
                    " lower_interval, upper_interval, model_version, generated_at, data_cutoff) VALUES "
                    "('g1', '2026-11-14', 1, 'puntos', 'base', ?, 8, 15, 30, 'm', ?, '2026-11-13')", (media, generado))
    con.execute("INSERT INTO player_props(game_date, player_id, player_name, market, line, over_odds, under_odds, "
                "bookmaker, captured_at, entry_method) VALUES ('2026-11-14', 1, 'Ana Pérez', 'puntos', 19.5, 1.9, 1.9, "
                "'Stake', 'x', 'MANUAL')")
    assert resultados.calificar(con).empty  # En juego: el box score es parcial y no se califica.
    con.execute("UPDATE games SET status = 'final' WHERE game_id = 'g1'")
    df = resultados.calificar(con)
    assert len(df) == 1
    fila = df.iloc[0]
    assert fila.projected_mean == 22.0  # La de antes del partido, no la de después.
    assert fila.lado == "over" and fila.acierto == 1 and fila.p_mercado == pytest.approx(0.5)
    metricas = resultados.actualizar(con, {"points": 0.97, "rebounds": 1.0, "assists": 1.0})
    assert metricas["lineas"]["aciertos"] == 1 and metricas["por_stat"]["points"]["factor"] == 0.97
    assert resultados.ultimas_metricas(con)["por_stat"]["points"]["factor"] == 0.97


def test_factores_temporada_corrige_con_lo_jugado():
    from psa.nba import resultados
    n = 20000
    df = pd.DataFrame({"mu_points": [10.0] * n, "points": [9.0] * n, "mu_rebounds": [5.0] * n, "rebounds": [5.0] * n,
                       "mu_assists": [3.0] * n, "assists": [np.nan] * n})
    f = resultados.factores_temporada(df)
    assert 0.9 < f["points"] < 0.95 and f["rebounds"] == 1.0 and f["assists"] == 1.0  # Sin datos reales: sin corrección.


def test_k_por_minutos():
    rng = np.random.default_rng(1)
    minutos = np.r_[np.full(4000, 10.0), np.full(4000, 34.0)]
    mu = np.r_[np.full(4000, 4.0), np.full(4000, 20.0)]
    k_real = np.r_[np.full(4000, 1.0), np.full(4000, 12.0)]
    y = rng.negative_binomial(k_real, k_real / (k_real + mu))
    k = modelo.ajustar_k_tramos(minutos, mu, y)
    assert modelo.k_para(k, 10.0) < 2 and modelo.k_para(k, 34.0) > 8  # Suplente más disperso que titular.
    assert modelo.k_para(6.0, 20.0) == 6.0 and list(modelo.k_para(k, np.array([10.0, 34.0]))) == [k[0], k[4]]


# --- Parleys por partido -------------------------------------------------------------

def _jugador(nombre, eq, p, lado="over", aciertos=7, est="", notas="", minutos=30, casa="Stake"):
    prop = {"tipo": "real", "casa": casa, "linea": 10.5, "media": 12.0, "l5": 12, "l10": 11.5,
            "aciertos": [aciertos, 10], "alto": {"lado": lado, "p": p, "ve": -0.02, "cuota": 1.8, "pm": p - 0.02}}
    return {"j": nombre, "eq": eq, "p": "AAA @ BBB", "esc": "base", "min": minutos, "est": est, "notas": notas,
            "props": {"pts": prop}}


def test_parley_filtra_y_elige_los_mas_probables():
    from psa.nba import combinadas
    jugadores = [_jugador("A", "AAA", 0.70), _jugador("B", "AAA", 0.68), _jugador("C", "AAA", 0.66),  # 3.º del mismo equipo
                 _jugador("D", "BBB", 0.60), _jugador("Duda", "BBB", 0.90, est="Questionable"),
                 _jugador("Poco", "BBB", 0.90, aciertos=5), _jugador("Paliza", "BBB", 0.90, notas="riesgo de paliza"),
                 _jugador("Consenso", "BBB", 0.90, casa="Consenso BettingPros"), _jugador("Banca", "BBB", 0.90, minutos=12),
                 _jugador("Bajo", "BBB", 0.50)]
    parleys = combinadas.armar(jugadores)
    assert [len(p["legs"]) for p in parleys] == [2, 3]
    assert [l["j"] for l in parleys[1]["legs"]] == ["A", "B", "D"]  # Máximo 2 por equipo: C queda fuera.
    assert parleys[0]["prob"] == pytest.approx(0.70 * 0.68, abs=1e-3)
    assert parleys[0]["cuota_justa"] == pytest.approx(1 / (0.70 * 0.68), abs=0.01)
    assert "7 de sus últimos 10" in parleys[0]["legs"][0]["por_que"]


def test_combinadas_suman_sus_partes_y_lo_real():
    filas = [{"player_id": 1, "game_id": f"g{i}", "game_date": f"2026-11-{i + 1:02d}", "minutes": 30.0,
              "points": 20 + i % 3, "rebounds": 5 + i % 2, "assists": 4} for i in range(8)]
    df = modelo.con_proyeccion(pd.DataFrame(filas))
    ultima = df.iloc[-1]
    assert ultima.mu_pra == pytest.approx(ultima.mu_points + ultima.mu_rebounds + ultima.mu_assists)
    assert ultima.mu_ra == pytest.approx(ultima.mu_rebounds + ultima.mu_assists)
    assert ultima.pr == ultima.points + ultima.rebounds
    assert set(modelo.COMBOS) <= set(modelo.K_DEFECTO)


def test_parleys_se_guardan_antes_del_inicio_y_se_califican(tmp_path):
    from psa.nba import combinadas
    con = db.conectar(tmp_path / "t.sqlite")
    con.execute("INSERT INTO players VALUES (1, 'Ana Pérez', 'ana perez'), (2, 'Bea Ruiz', 'bea ruiz')")
    leg = lambda j, mercado, lado, linea: {"j": j, "mercado": mercado, "lado": lado, "linea": linea, "prob": 0.6, "cuota": 1.8}
    parley = lambda partido: {"partido": partido, "legs": [leg("Ana Pérez", "PRA", "over", 30.5), leg("Bea Ruiz", "rebotes", "under", 6.5)],
                              "prob": 0.36, "cuota": 3.24, "cuota_justa": 2.78, "ve": 0.17}
    inicios = {"A @ B": "2099-01-01T00:00:00Z", "C @ D": "2000-01-01T00:00:00Z"}  # Uno futuro, uno ya empezado.
    assert combinadas.guardar(con, "2026-11-14", [parley("A @ B"), parley("C @ D")], inicios) == 1
    assert combinadas.calificar(con)["parleys"][0]["estado"] == "pendiente"  # Sin box score todavía.
    con.execute("INSERT INTO nba_player_game_stats(game_id, player_id, team_id, season, game_date, minutes, points, rebounds,"
                " assists, source_id) VALUES ('g', 1, 9, '2026-27', '2026-11-14', 30, 20, 8, 5, 0),"
                " ('g', 2, 9, '2026-27', '2026-11-14', 25, 10, 4, 2, 0)")
    con.execute("INSERT INTO games(game_id, season, season_type, game_date, status) VALUES ('g', '2026-27', 'Regular', "
                "'2026-11-14', 'en vivo')")
    assert combinadas.calificar(con)["parleys"][0]["estado"] == "pendiente"  # Parcial: no se califica.
    con.execute("UPDATE games SET status = 'final'")
    r = combinadas.calificar(con)
    assert r["parleys"][0]["legs"][0]["real"] == 33 and r["parleys"][0]["estado"] == "gano"
    assert (r["decididos"], r["ganados"], r["esperados"]) == (1, 1, 0.36)


def test_linea_segura():
    over = modelo.linea_segura(37.0, 13.5, "over")
    under = modelo.linea_segura(37.0, 13.5, "under")
    assert over[0] < 37 < under[0] and over[1] >= 0.75 and under[1] >= 0.75
    assert modelo.p_over(37.0, 13.5, over[0] + 1) < 0.75  # Es la más exigente que pasa el 75 %.
    assert modelo.linea_segura(float("nan"), 5, "over") is None
