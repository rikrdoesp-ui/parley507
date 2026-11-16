"""Parleys con las props de Stake que tienen precio, incluidas las líneas alternas (la flecha junto a la línea).

Solo es una propuesta: BET o PASS, monto y topes los decide /parley. Dos escenarios, como juega Ricardo:
1. Uno por juego: el mejor prop de cada partido; el parley mezcla partidos. Escalera de 2 legs en adelante.
2. Dos por juego: cada partido aporta su mejor par de props; el parley es un partido o varios, siempre 2 por partido.

"Mejor" es el más probable, porque el objetivo es acertar. Reglas de un leg:
- probabilidad del mercado sin margen, movida por el modelo (props.mezclar), de P_MINIMA o más;
- jugador sin duda ni baja, con muestra suficiente, 20+ minutos proyectados y minutos estables;
- el lado salió en al menos 6 de sus últimos 10 partidos a esa misma línea;
- nada de overs de titulares con riesgo de paliza (pueden jugar menos minutos);
- un leg por jugador.
Partidos distintos son independientes. Dentro de un partido la probabilidad conjunta usa la correlación histórica
entre jugadores (modelo.correlaciones); es pequeña (0,07 como mucho). En "mismo juego" Stake paga menos que el
producto de las cuotas: la cuota mostrada es el tope y la justa es el mínimo que debería pagar.
"""
import json
from itertools import combinations

import numpy as np

from .. import config, db
from . import lesiones, modelo

P_MINIMA = 0.55
ACIERTOS_MINIMOS = 6
MINUTOS_MINIMOS = 20
POR_JUEGO = 2  # Legs por partido en el escenario 2.
CANDIDATOS_POR_JUEGO = 12  # Los más probables de cada partido entre los que se busca el mejor par.
NOMBRES = {"puntos": "puntos", "rebotes": "rebotes", "asistencias": "asistencias", "pra": "PRA", "pr": "PR", "ra": "RA"}
UNO, DOS = "uno por juego", "dos por juego"


def candidatos(jugadores: list[dict], lineas: list[dict], ultimos: dict) -> list[dict]:
    """Un candidato por línea de Stake y lado que pasa las reglas.

    `lineas`: filas de props.evaluar (todas las líneas, alternas incluidas). `ultimos`: {(player_id, mercado):
    valores de los últimos 10 partidos}.
    """
    aptos = {}
    for j in jugadores:
        notas = j.get("notas", "")
        if (j.get("esc") == "base" and j.get("est") not in lesiones.NO_JUEGA | lesiones.DUDA
                and "muestra insuficiente" not in notas and "minutos inestables" not in notas
                and (j.get("min") or 0) >= MINUTOS_MINIMOS):
            aptos[j["pid"]] = j
    salida = []
    for l in lineas:
        j = aptos.get(l.get("player_id"))
        if j is None or l.get("casa") != "Stake" or l.get("P mezcla over") is None:
            continue
        valores = ultimos.get((j["pid"], l["mercado"]), [])
        for lado in ("over", "under"):
            prob, cuota = l.get(f"P mezcla {lado}"), l.get(f"cuota {lado}")
            if not cuota or prob is None or prob < P_MINIMA:
                continue
            if lado == "over" and "riesgo de paliza" in j.get("notas", ""):
                continue
            aciertos = sum((v > l["línea"]) if lado == "over" else (v < l["línea"]) for v in valores)
            if aciertos < ACIERTOS_MINIMOS:
                continue
            pm = l.get("P mercado over (sin margen)")
            salida.append({"p": j["p"], "j": j["j"], "pid": j["pid"], "eq": j["eq"], "clave": l["mercado"],
                           "mercado": NOMBRES[l["mercado"]], "lado": lado, "linea": l["línea"],
                           "prob": round(prob, 3), "cuota": cuota, "ve": l.get(f"VE {lado}"),
                           "pm": None if pm is None else round(pm if lado == "over" else 1 - pm, 3),
                           "principal": bool(l.get("principal")), "media": l.get("media"), "min": j.get("min"),
                           "aciertos": [aciertos, len(valores)]})
    return salida


def _orden(c: dict):
    return (-c["prob"], -(c["ve"] if c["ve"] is not None else -1))


def _escalon(legs: list[dict], prob: float) -> dict:
    cuota = float(np.prod([c["cuota"] for c in legs]))
    return {"n": len(legs), "prob": round(prob, 3), "cuota": round(cuota, 2), "justa": round(1 / prob, 2),
            "ve": round(prob * cuota - 1, 3)}


def uno_por_juego(cands: list[dict]) -> dict:
    """El leg más probable de cada partido, del más al menos probable, y la escalera de 2 legs en adelante."""
    mejores = {}
    for c in sorted(cands, key=_orden):
        mejores.setdefault(c["p"], c)
    legs = sorted(mejores.values(), key=_orden)
    escalera, prob = [], 1.0
    for n, c in enumerate(legs, 1):
        prob *= c["prob"]
        if n >= 2:
            escalera.append(_escalon(legs[:n], prob))
    return {"legs": legs, "escalera": escalera}


def _rho(a: dict, b: dict, corr: dict) -> float:
    tabla = corr.get("mismo" if a["eq"] == b["eq"] else "rival", {})
    r = tabla.get(f"{config.MERCADOS_NBA[a['clave']]}|{config.MERCADOS_NBA[b['clave']]}", 0.0)
    return r * (1 if a["lado"] == b["lado"] else -1)  # Un under invierte el signo.


def conjunta(legs: list[dict], corr: dict) -> float:
    rho = np.eye(len(legs))
    for (i, a), (k, b) in combinations(enumerate(legs), 2):
        rho[i, k] = rho[k, i] = _rho(a, b, corr)
    return modelo.p_conjunta([c["prob"] for c in legs], rho)


def dos_por_juego(cands: list[dict], corr: dict) -> dict:
    """Por partido, el grupo de POR_JUEGO legs (jugadores distintos) con mayor probabilidad conjunta, y la escalera
    por número de partidos."""
    por_partido = {}
    for c in sorted(cands, key=_orden):
        lista = por_partido.setdefault(c["p"], [])
        # Un leg por jugador: de cada uno solo su mejor línea entra a la búsqueda.
        if len(lista) < CANDIDATOS_POR_JUEGO and all(x["pid"] != c["pid"] for x in lista):
            lista.append(c)
    grupos = []
    for partido, lista in por_partido.items():
        if len(lista) < POR_JUEGO:
            continue
        # Una sola evaluación por par: la integral de SciPy es numérica y dos llamadas no dan idéntico resultado.
        prob, mejor = max(((conjunta(list(g), corr), g) for g in combinations(lista, POR_JUEGO)), key=lambda x: x[0])
        grupos.append({"partido": partido, "legs": list(mejor), **_escalon(list(mejor), prob),
                       "independiente": round(float(np.prod([c["prob"] for c in mejor])), 3)})
    grupos.sort(key=lambda g: -g["prob"])
    escalera, prob, legs = [], 1.0, []
    for n, g in enumerate(grupos, 1):
        prob *= g["prob"]
        legs += g["legs"]
        escalera.append({"partidos": n, **_escalon(legs, prob)})
    return {"grupos": grupos, "escalera": escalera}


def armar(jugadores: list[dict], lineas: list[dict], ultimos: dict, corr: dict) -> dict:
    cands = candidatos(jugadores, lineas, ultimos)
    return {"uno": uno_por_juego(cands), "dos": dos_por_juego(cands, corr), "candidatos": len(cands)}


def propuestas(parleys: dict) -> list[dict]:
    """Cada escalón de las dos escaleras como un parley para guardar: tipo, legs y números."""
    salida = []
    uno, dos = parleys["uno"], parleys["dos"]
    for e in uno["escalera"]:
        salida.append({"tipo": UNO, "legs": uno["legs"][:e["n"]], **e})
    legs = []
    for g, e in zip(dos["grupos"], dos["escalera"]):
        legs = legs + g["legs"]
        salida.append({"tipo": DOS, "legs": legs, **e})
    return salida


def guardar(con, fecha: str, parleys: dict, inicios: dict) -> int:
    """Guarda cada escalón mientras ninguno de sus partidos haya empezado (reemplaza la versión anterior).

    Lo que se propone ya empezado un partido no se guarda: calificarlo sería hacer trampa.
    """
    ahora = db.ahora_utc()
    # Un partido sin hora (NaT) no cuenta como "por empezar".
    sin_empezar = lambda legs: all(isinstance(inicios.get(l.get("p")), str) and _utc(inicios[l["p"]]) > ahora for l in legs)
    nuevos = [p for p in propuestas(parleys) if sin_empezar(p["legs"])]
    # Los escalones del día que aún no empiezan se rehacen enteros: si ahora hay menos partidos elegibles, el
    # escalón más largo de antes no debe quedar guardado con legs que ya no se proponen.
    for tipo, tam, legs_json in con.execute("SELECT matchup, size, legs_json FROM parley_proposals WHERE game_date = ?"
                                            " AND matchup IN (?, ?)", (fecha, UNO, DOS)).fetchall():
        if sin_empezar(json.loads(legs_json)):
            con.execute("DELETE FROM parley_proposals WHERE game_date = ? AND matchup = ? AND size = ?", (fecha, tipo, tam))
    con.executemany("""INSERT OR REPLACE INTO parley_proposals(game_date, matchup, size, legs_json, prob, odds, fair_odds,
                       ev, generated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [(fecha, p["tipo"], len(p["legs"]),
                      json.dumps([{k: l[k] for k in ("j", "p", "mercado", "lado", "linea", "prob", "cuota")}
                                  for l in p["legs"]], ensure_ascii=False),
                      p["prob"], p["cuota"], p["justa"], p["ve"], ahora) for p in nuevos])
    con.commit()
    return len(nuevos)


def _utc(texto: str) -> str:
    """'2026-11-16T00:00:00Z' -> '2026-11-16T00:00:00+00:00', para comparar con db.ahora_utc()."""
    return str(texto).replace("Z", "+00:00")


def calificar(con) -> dict:
    """Cada parley guardado con el resultado de sus legs (box score oficial). Push o jugador sin minutos = pendiente."""
    filas = con.execute("""SELECT game_date, matchup, size, legs_json, prob, odds, fair_odds, ev, generated_at FROM parley_proposals
                           ORDER BY game_date DESC, matchup, size""").fetchall()
    inicios = {(f, f"{a} @ {h}"): i for f, a, h, i in con.execute(
        """SELECT g.game_date, a.abbreviation, h.abbreviation, g.start_time_utc FROM games g
           JOIN teams h ON h.team_id = g.home_team_id JOIN teams a ON a.team_id = g.away_team_id""")}
    salida = []
    for fecha, partido, tam, legs_json, prob, cuota, justa, ve, generado in filas:
        legs = json.loads(legs_json)
        for l in legs:
            stat = config.MERCADOS_NBA[l["mercado"].lower()]
            valor = con.execute(f"""SELECT {'+'.join(_partes(stat))}, s.minutes FROM nba_player_game_stats s
                                    JOIN players p USING(player_id) JOIN games g ON g.game_id = s.game_id
                                    WHERE p.full_name = ? AND s.game_date = ? AND g.status = 'final'""",
                                (l["j"], fecha)).fetchone()
            l["real"] = None if not valor or not valor[1] else valor[0]
            l["ok"] = None if l["real"] is None or l["real"] == l["linea"] else (
                l["real"] > l["linea"] if l["lado"] == "over" else l["real"] < l["linea"])
        estado = ("perdio" if any(l["ok"] is False for l in legs) else
                  "gano" if all(l["ok"] is True for l in legs) else "pendiente")
        # Los de antes de los dos escenarios eran de un solo partido y lo llevan en `matchup`.
        tipo = partido if partido in (UNO, DOS) else "un partido"
        empiezan = [inicios.get((fecha, l.get("p", partido))) for l in legs]
        # Propuesto con algún partido empezado: no cuenta.
        tarde = any(i and generado >= _utc(i) for i in empiezan)
        salida.append({"f": fecha, "partido": partido, "tipo": tipo, "tam": tam, "legs": legs, "prob": prob,
                       "cuota": cuota, "justa": justa, "ve": ve, "estado": estado, "tarde": tarde})
    decididos = [p for p in salida if p["estado"] != "pendiente" and not p["tarde"]]
    tarde = [p for p in salida if p["estado"] != "pendiente" and p["tarde"]]

    def cuenta(lista: list[dict]) -> dict:
        return {"decididos": len(lista), "ganados": sum(p["estado"] == "gano" for p in lista),
                "esperados": round(sum(p["prob"] for p in lista), 2)}

    return {"parleys": salida, **cuenta(decididos), "tarde": cuenta(tarde),
            "por_tipo": {t: cuenta([p for p in decididos if p["tipo"] == t]) for t in (UNO, DOS, "un partido")}}


def _partes(stat: str) -> list[str]:
    return [f"s.{s}" for s in modelo.COMBOS.get(stat, [stat])]
