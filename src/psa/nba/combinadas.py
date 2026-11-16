"""Parleys por partido con las props de Stake que tienen precio, cada leg con su justificación.

Solo es una propuesta: BET o PASS, monto y topes los decide /parley. Reglas de selección:
- lado más probable de la línea de Stake (probabilidad del mercado sin margen, movida por el modelo);
- jugador sin duda ni baja, con muestra suficiente, 20+ minutos proyectados y minutos estables;
- el lado salió en al menos 6 de sus últimos 10 partidos;
- nada de overs de titulares con riesgo de paliza (pueden jugar menos minutos);
- un leg por jugador y como mucho 2 por equipo, para no amontonar legs que se mueven juntos.
La probabilidad conjunta supone legs independientes: en el mismo partido no lo son del todo, y Stake paga menos que
el producto de las cuotas en los "mismo juego". Por eso se da la cuota justa: el mínimo que Stake debería pagar.
"""
from . import lesiones

P_MINIMA = 0.55
ACIERTOS_MINIMOS = 6
MINUTOS_MINIMOS = 20
MAX_POR_EQUIPO = 2
TAMANOS = (2, 3)
NOMBRES = {"pts": "puntos", "reb": "rebotes", "ast": "asistencias"}


def candidatos(jugadores: list[dict]) -> list[dict]:
    salida = []
    for j in jugadores:
        if j.get("esc") != "base" or j.get("est") in lesiones.NO_JUEGA | lesiones.DUDA:
            continue
        notas = j.get("notas", "")
        if "muestra insuficiente" in notas or "minutos inestables" in notas or (j.get("min") or 0) < MINUTOS_MINIMOS:
            continue
        for corto, p in j.get("props", {}).items():
            alto = p.get("alto") or {}
            if p.get("tipo") != "real" or str(p.get("casa", "")).startswith("Consenso") or not alto.get("cuota"):
                continue
            aciertos, n = p.get("aciertos") or (0, 0)
            if alto["p"] < P_MINIMA or aciertos < ACIERTOS_MINIMOS:
                continue
            if alto["lado"] == "over" and "riesgo de paliza" in notas:
                continue
            salida.append({"p": j["p"], "j": j["j"], "eq": j["eq"], "mercado": NOMBRES[corto], "lado": alto["lado"],
                           "linea": p["linea"], "prob": alto["p"], "pm": alto.get("pm"), "cuota": alto["cuota"],
                           "ve": alto.get("ve"), "media": p.get("media"), "l5": p.get("l5"), "l10": p.get("l10"),
                           "aciertos": [aciertos, n], "min": j.get("min"),
                           "por_que": justificar(p, alto, aciertos, n, j.get("min"))})
    return salida


def justificar(p: dict, alto: dict, aciertos: int, n: int, minutos) -> str:
    lado = "más" if alto["lado"] == "over" else "menos"
    partes = [f"El modelo proyecta {p['media']} contra la línea {p['linea']} ({lado} de {p['linea']})",
              f"cumplió en {aciertos} de sus últimos {n}", f"promedia {p['l5']} en los últimos 5 y {p['l10']} en 10",
              f"{minutos} minutos proyectados"]
    if alto.get("pm") is not None:
        partes.append(f"el mercado sin margen le da {alto['pm']:.0%} y con el modelo queda en {alto['p']:.0%}")
    return "; ".join(partes) + "."


def armar(jugadores: list[dict]) -> list[dict]:
    """Por partido, el parley de 2 y de 3 legs más probable que cumple las reglas."""
    por_partido = {}
    for c in candidatos(jugadores):
        por_partido.setdefault(c["p"], []).append(c)
    parleys = []
    for partido, legs in por_partido.items():
        elegidos, usados, por_equipo = [], set(), {}
        for c in sorted(legs, key=lambda c: (-c["prob"], -(c["ve"] or -1))):
            if c["j"] in usados or por_equipo.get(c["eq"], 0) >= MAX_POR_EQUIPO:
                continue
            elegidos.append(c)
            usados.add(c["j"])
            por_equipo[c["eq"]] = por_equipo.get(c["eq"], 0) + 1
            if len(elegidos) == max(TAMANOS):
                break
        for tam in TAMANOS:
            if len(elegidos) < tam:
                continue
            sel = elegidos[:tam]
            prob, cuota = 1.0, 1.0
            for c in sel:
                prob *= c["prob"]
                cuota *= c["cuota"]
            parleys.append({"partido": partido, "legs": sel, "prob": round(prob, 3), "cuota": round(cuota, 2),
                            "cuota_justa": round(1 / prob, 2), "ve": round(prob * cuota - 1, 3)})
    return parleys
