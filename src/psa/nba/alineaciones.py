"""Alineaciones probables de RotoWire: titulares (confirmados o esperados) y quién puede no jugar.

Complementa el reporte oficial de lesiones: RotoWire suele marcar antes las bajas de último momento. Solo se usa
para lo que el PDF no dice: un jugador sin estado en el reporte oficial toma el de RotoWire.
Fuente: https://www.rotowire.com/basketball/nba-lineups.php (el mismo lector que usa /parley).
"""
import re

import pandas as pd
import requests

from .. import db

URL = "https://www.rotowire.com/basketball/nba-lineups.php"
RE_JUGADOR = re.compile(r'<li class="lineup__player is-pct-play-(\d+)[^"]*"[^>]*>\s*<div class="lineup__pos"[^>]*>\s*(\w+)\s*</div>'
                        r'\s*<a title="([^"]+)"[^>]*>[^<]*</a>(?:\s*<span class="lineup__inj">([^<]+)</span>)?')
ESTADOS = {"confirmed": "confirmada", "expected": "esperada"}
# Abreviaturas de RotoWire en "May not play" -> estado del reporte oficial.
LESION_A_ESTADO = {"out": "Out", "ofs": "Out", "susp": "Out", "doubt": "Doubtful", "gtd": "Questionable",
                   "ques": "Questionable", "prob": "Probable"}


class FormatoCambiado(ValueError):
    pass


def parsear(html: str) -> list[dict]:
    """Una fila por jugador listado: equipo, rival, local o visita, rol (titular o duda) y estado."""
    texto = re.sub(r"\s+", " ", html)
    abreviaturas = re.findall(r'class="lineup__abbr">\s*([A-Z]{2,4})\s*<', texto)
    listas = re.findall(r'<ul class="lineup__list is-(visit|home)">(.*?)</ul>', texto)
    if len(abreviaturas) != len(listas) or len(listas) % 2:
        raise FormatoCambiado(f"RotoWire cambió su página: {len(abreviaturas)} equipos y {len(listas)} alineaciones.")
    filas = []
    for i, (equipo, (lado, lista)) in enumerate(zip(abreviaturas, listas)):
        rival = abreviaturas[i + 1] if lado == "visit" else abreviaturas[i - 1]
        estado = re.search(r"lineup__status is-(\w+)", lista)
        estado = ESTADOS.get(estado.group(1), estado.group(1)) if estado else ""
        antes, _, despues = lista.partition("MAY NOT PLAY")
        for rol, parte in (("titular", antes), ("duda", despues)):
            for pct, pos, nombre, lesion in RE_JUGADOR.findall(parte):
                filas.append({"equipo": equipo, "rival": rival, "local": lado == "home", "rol": rol, "jugador": nombre,
                              "pos": pos, "pct": int(pct), "lesion": (lesion or "").strip(), "alineacion": estado})
    return filas


def descargar() -> list[dict]:
    r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return parsear(r.text)


def guardar(con, fecha: str, filas: list[dict]) -> int:
    """Guarda solo los partidos de RotoWire que coinciden con el calendario de `fecha` (su página cambia de día)."""
    del_dia = {(a, h) for a, h in con.execute(
        """SELECT a.abbreviation, h.abbreviation FROM games g JOIN teams h ON h.team_id = g.home_team_id
           JOIN teams a ON a.team_id = g.away_team_id WHERE g.game_date = ?""", (fecha,))}
    validas = [f for f in filas if ((f["rival"], f["equipo"]) if f["local"] else (f["equipo"], f["rival"])) in del_dia]
    ahora = db.ahora_utc()
    con.execute("DELETE FROM nba_lineups WHERE game_date = ?", (fecha,))
    con.executemany("""INSERT OR REPLACE INTO nba_lineups(game_date, team, player_name, name_key, role, position, pct_play,
                       injury, lineup_status, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(fecha, f["equipo"], f["jugador"], db.clave_nombre(f["jugador"]), f["rol"], f["pos"], f["pct"],
                      f["lesion"], f["alineacion"], ahora) for f in validas])
    con.commit()
    return len(validas)


def del_dia(con, fecha: str) -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM nba_lineups WHERE game_date = ?", con, params=(fecha,))


def rol(df: pd.DataFrame, nombre: str, equipo: str) -> dict:
    """{rol, lesion, alineacion} de un jugador. Sin datos de su equipo: rol vacío (no se afirma nada).

    Si no aparece en la lista de su equipo, es suplente. RotoWire puede usar un apodo: basta el apellido si es único.
    """
    eq = df[df.team == equipo]
    if eq.empty:
        return {"rol": "", "lesion": "", "alineacion": ""}
    clave = db.clave_nombre(nombre)
    fila = eq[eq.name_key == clave]
    if fila.empty:
        apellido = clave.split(" ", 1)[-1]
        fila = eq[eq.name_key.str.split(" ", n=1).str[-1] == apellido]
        if len(fila) != 1:
            return {"rol": "suplente", "lesion": "", "alineacion": eq.lineup_status.iloc[0]}
    f = fila.iloc[0]
    return {"rol": f.role, "lesion": f.injury, "alineacion": f.lineup_status}


def estado_oficial(lesion: str) -> str:
    """'GTD' -> 'Questionable', 'Out' -> 'Out'...; vacío si no se reconoce."""
    return LESION_A_ESTADO.get(str(lesion).strip().lower(), "")
