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


def test_resolver_jugador_abreviado_y_ambiguo():
    plantilla = pd.DataFrame({"player_id": [1, 2, 3], "jugador": ["Mikal Bridges", "Jalen Williams", "Jaylin Williams"]})
    assert parley_io.resolver_jugador("M. Bridges", plantilla) == 1
    assert parley_io.resolver_jugador("Jalen Williams", plantilla) == 2
    assert parley_io.resolver_jugador("J. Williams", plantilla) is None
