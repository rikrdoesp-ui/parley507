"""Reporte oficial de lesiones de la NBA (PDF) y correcciones manuales.

El PDF se lee por la posición horizontal de cada columna del encabezado. Si el formato cambia y no se
encuentran las columnas, se lanza un error claro: la app avisa y se usa el ingreso manual.
Un motivo (Reason) partido en varias líneas se vuelve a unir; si el PDF lo corta distinto, puede quedar incompleto.
"""
import io
import re
from datetime import datetime

import pandas as pd
import pdfplumber
import requests

from .. import db

PAGINA = "https://official.nba.com/nba-injury-report-{temporada}-season/"
RE_PDF = re.compile(r"https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf")
COLUMNAS = ["GameDate", "GameTime", "Matchup", "Team", "PlayerName", "CurrentStatus", "Reason"]
ESTADOS = {"Out", "Questionable", "Doubtful", "Probable", "Available"}
NO_JUEGA = {"Out"}
DUDA = {"Questionable", "Doubtful"}


class FormatoCambiado(Exception):
    """El PDF ya no tiene la estructura esperada."""


def ultimo_pdf(temporada: str) -> tuple[str, str]:
    """URL del reporte más reciente publicado en la página oficial y su hora (ET)."""
    html = requests.get(PAGINA.format(temporada=temporada), headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    enlaces = {m.group(0): m for m in RE_PDF.finditer(html)}
    if not enlaces:
        raise FormatoCambiado("La página oficial no tiene enlaces a reportes PDF.")

    def momento(m):
        return datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)} {m.group(4)}", "%Y-%m-%d %I:%M %p")

    url, m = max(enlaces.items(), key=lambda par: momento(par[1]))
    return url, momento(m).strftime("%Y-%m-%d %H:%M ET")


def filas_de_palabras(palabras: list[dict], limites: dict | None) -> tuple[list[dict], dict | None]:
    """Convierte las palabras de una página (texto, x0, top) en filas de jugadores.

    Devuelve las filas y los límites de columna, que se reutilizan si una página no repite el encabezado.
    """
    encabezado = {p["text"]: p["x0"] for p in palabras if p["text"] in COLUMNAS}
    if len(encabezado) == len(COLUMNAS):
        limites = encabezado
    if not limites:
        raise FormatoCambiado("No se encontraron las columnas del reporte.")
    orden = sorted(limites.items(), key=lambda x: x[1])

    def columna(x):
        nombre = orden[0][0]
        for c, inicio in orden:
            if x >= inicio - 3:
                nombre = c
        return nombre

    lineas: list[list[dict]] = []
    for p in sorted(palabras, key=lambda p: (p["top"], p["x0"])):
        if lineas and abs(lineas[-1][0]["top"] - p["top"]) < 3:
            lineas[-1].append(p)
        else:
            lineas.append([p])
    filas = []
    for linea in lineas:
        celdas: dict[str, str] = {"_top": min(p["top"] for p in linea)}
        for p in linea:
            c = columna(p["x0"])
            celdas[c] = (celdas.get(c, "") + " " + p["text"]).strip()
        filas.append(celdas)
    return filas, limites


def jugadores_de_pagina(filas: list[dict], contexto: dict) -> list[dict]:
    """Filas de una página -> jugadores. `contexto` (fecha, partido, equipo) sigue de una página a la otra."""
    de_pagina, sueltos = [], []
    for celdas in filas:
        top = celdas.pop("_top")
        texto = " ".join(celdas.values())
        # El título "Injury Report: ..." de cada página cae en las columnas Team/PlayerName: no es una fila.
        if celdas.get("GameDate") == "GameDate" or texto.startswith(("Injury Report", "Page")):
            continue
        for campo in contexto:
            if celdas.get(campo) and re.search(r"\d|@|[a-z]", celdas[campo]):
                contexto[campo] = celdas[campo]
        estado = celdas.get("CurrentStatus", "")
        nombre = celdas.get("PlayerName", "")
        if estado in ESTADOS and nombre:
            de_pagina.append({**contexto, "PlayerName": nombre, "CurrentStatus": estado,
                              "_partes": [(top, celdas.get("Reason", ""))]})
        elif set(celdas) == {"Reason"} and "SUBMITTED" not in celdas["Reason"].upper():
            sueltos.append((top, celdas["Reason"]))
    # Un motivo largo se parte en líneas arriba y abajo de la fila: cada trozo va a la fila más cercana.
    for top, texto in sueltos:
        if de_pagina:
            min(de_pagina, key=lambda j: abs(j["_partes"][0][0] - top))["_partes"].append((top, texto))
    for j in de_pagina:
        j["Reason"] = "".join(t for _, t in sorted(j.pop("_partes")))
    return de_pagina


def leer_pdf(contenido: bytes) -> list[dict]:
    jugadores = []
    contexto = {"GameDate": None, "GameTime": None, "Matchup": None, "Team": None}
    limites = None
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            filas, limites = filas_de_palabras(pagina.extract_words(), limites)
            jugadores += jugadores_de_pagina(filas, contexto)
    if not jugadores:
        raise FormatoCambiado("El PDF no tiene filas de jugadores reconocibles.")
    return jugadores


def nombre_natural(nombre: str) -> str:
    """'Haliburton,Tyrese' -> 'Tyrese Haliburton'."""
    apellido, _, pila = nombre.partition(",")
    return f"{pila.strip()} {apellido.strip()}".strip()


def guardar(con, jugadores: list[dict], url: str, reportado: str) -> int:
    if con.execute("SELECT 1 FROM data_sources WHERE source_url = ?", (url,)).fetchone():
        return 0  # Este reporte ya se cargó.
    fuente = db.registrar_fuente(con, "NBA (reporte oficial de lesiones)", f"PDF {reportado}", url,
                                 "Publicación oficial NBA")
    equipos = {db.clave_nombre(n): i for i, n in con.execute("SELECT team_id, full_name FROM teams")}
    equipos.update({db.clave_nombre(a): i for i, a in con.execute("SELECT team_id, abbreviation FROM teams")})
    equipos["laclippers"] = equipos.get("losangelesclippers")
    claves = pd.read_sql("SELECT player_id, name_key FROM players", con).groupby("name_key")["player_id"].agg(list)
    ahora = db.ahora_utc()
    filas = []
    for j in jugadores:
        nombre = nombre_natural(j["PlayerName"])
        ids = claves.get(db.clave_nombre(nombre), [])
        equipo = equipos.get(db.clave_nombre(j["Team"] or ""))
        if equipo is None:
            db.calidad(con, "nba_injuries", nombre, "equipo_desconocido", "media", f"Equipo no reconocido: {j['Team']}")
        fecha = datetime.strptime(j["GameDate"], "%m/%d/%Y").date().isoformat() if j["GameDate"] else None
        filas.append((fecha, j["Matchup"], equipo, nombre, ids[0] if len(ids) == 1 else None, j["CurrentStatus"],
                      j["Reason"], reportado, fuente, ahora))
    con.executemany("""INSERT INTO nba_injuries(game_date, matchup, team_id, player_name, player_id, status, reason,
                       reported_at, entry_method, source_id, captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PDF', ?, ?)""",
                    filas)
    return len(filas)


def corregir(con, fecha: str, nombre: str, player_id: int | None, team_id: int | None, estado: str, motivo: str) -> None:
    con.execute("""INSERT INTO nba_injuries(game_date, team_id, player_name, player_id, status, reason, entry_method,
                   captured_at) VALUES (?, ?, ?, ?, ?, ?, 'MANUAL', ?)""",
                (fecha, team_id, nombre, player_id, estado, motivo, db.ahora_utc()))


def vigentes(con, fecha: str) -> pd.DataFrame:
    """Estado vigente por jugador: una corrección manual manda ese día; si no hay, el último PDF."""
    df = pd.read_sql("SELECT * FROM nba_injuries WHERE game_date = ?", con, params=(fecha,))
    if df.empty:
        return df
    df["clave"] = df.player_name.map(db.clave_nombre)
    df["manual"] = df.entry_method.eq("MANUAL")
    # Solo cuenta el PDF más reciente: quien sale de un reporte posterior ya no está reportado.
    pdf = df[~df.manual]
    df = df[df.manual | df.source_id.eq(pdf.source_id.max())]
    return df.sort_values(["manual", "captured_at", "injury_id"]).groupby("clave").tail(1).reset_index(drop=True)
