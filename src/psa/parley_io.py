"""Intercambio con /parley (carpeta CODE/stake): líneas de referencia, legs reales y proyecciones exportadas."""
import json
import statistics
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config, db, odds
from .nba import modelo

CASAS_MINIMAS = 3  # Igual que /parley: consenso solo con 3 casas o más en la misma línea.
# /parley escribe los partidos con abreviaturas de ESPN o BettingPros; la NBA usa otras.
A_NBA = {"GS": "GSW", "SA": "SAS", "NO": "NOP", "NY": "NYK", "UTAH": "UTA", "UTH": "UTA", "WSH": "WAS", "PHO": "PHX"}
SUFIJOS = {"jr", "sr", "ii", "iii", "iv", "v"}


def equipos_partido(partido: str) -> set[str]:
    visita, _, local = partido.strip().lstrip("#").partition("@")
    return {A_NBA.get(e.strip().upper(), e.strip().upper()) for e in (visita, local)}


def inicial_apellido(nombre: str) -> str:
    """'M. Bridges' y 'Mikal Bridges' -> 'mbridges' (BettingPros abrevia el nombre de pila)."""
    partes = [p for p in nombre.replace(".", " ").split() if db.clave_nombre(p) not in SUFIJOS]
    return db.clave_nombre(partes[0])[:1] + db.clave_nombre(partes[-1]) if partes else ""


def resolver_jugador(nombre: str, plantilla: pd.DataFrame) -> int | None:
    """player_id dentro de la plantilla del partido; None si no aparece o es ambiguo."""
    exactos = plantilla[plantilla.jugador.map(db.clave_nombre) == db.clave_nombre(nombre)]
    if len(exactos) == 1:
        return int(exactos.player_id.iloc[0])
    parecidos = plantilla[plantilla.jugador.map(inicial_apellido) == inicial_apellido(nombre)]
    return int(parecidos.player_id.iloc[0]) if len(parecidos) == 1 else None


def parsear_referencia(texto: str) -> list[dict]:
    """`#AWAY@HOME` y renglones `Jugador|mercado linea o/u*n,o/u;...` -> consenso sin margen por línea."""
    salida, partido = [], ""
    for renglon in texto.splitlines():
        renglon = renglon.strip()
        if renglon.startswith("#"):
            partido = renglon[1:]
            continue
        if "|" not in renglon:
            continue
        nombre, resto = renglon.split("|", 1)
        for item in resto.split(";"):
            partes = item.split()
            if len(partes) != 3:
                continue
            mercado, linea, parejas = partes[0].lower(), float(partes[1]), []
            for trozo in partes[2].split(","):
                pareja, _, veces = trozo.partition("*")
                sobre, _, debajo = pareja.partition("/")
                parejas += [(odds.a_decimal(sobre), odds.a_decimal(debajo))] * int(veces or 1)
            if len(parejas) >= CASAS_MINIMAS:
                p = statistics.median(odds.sin_margen(a, b) for a, b in parejas)
                salida.append({"partido": partido, "jugador": nombre.strip(), "mercado": mercado, "linea": linea,
                               "p_over": p, "casas": len(parejas)})
    return salida


def cargar_referencias(con, fecha: str, plantilla: pd.DataFrame) -> tuple[int, list[str]]:
    """Guarda en player_props el consenso de /parley (referencias/FECHA.txt) para los mercados del modelo."""
    ruta = config.STAKE / "referencias" / f"{fecha}.txt"
    if not ruta.exists():
        return 0, [f"Sin archivo de referencias de /parley para {fecha}."]
    avisos, filas = [], []
    for r in parsear_referencia(ruta.read_text(encoding="utf-8")):
        if r["mercado"] not in config.MERCADOS_NBA:
            continue
        equipos = equipos_partido(r["partido"]) if r["partido"] else set(plantilla.equipo)
        pid = resolver_jugador(r["jugador"], plantilla[plantilla.equipo.isin(equipos)])
        if pid is None:
            avisos.append(f"{r['jugador']} ({r['partido']}): no se pudo identificar en la plantilla.")
        filas.append((fecha, r["partido"], pid, r["jugador"], r["mercado"], r["linea"], round(1 / r["p_over"], 4),
                      round(1 / (1 - r["p_over"]), 4), f"Consenso BettingPros sin margen ({r['casas']} casas)",
                      db.ahora_utc(), ruta.name))
    con.executemany("""INSERT OR IGNORE INTO player_props(game_date, matchup, player_id, player_name, market, line,
                       over_odds, under_odds, bookmaker, captured_at, entry_method, source_ref)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PARLEY_REF', ?)""", filas)
    return len(filas), avisos


def exportar(df: pd.DataFrame, fecha: str) -> Path:
    """Escribe CODE/stake/proyecciones/FECHA.json con P(over) en las líneas x.5 cercanas a la media."""
    jugadores = []
    for r in df.itertuples():
        mercados = {}
        for mercado, stat in config.MERCADOS_NBA.items():
            mu, k = getattr(r, f"mu_{stat}"), getattr(r, f"k_{stat}")
            if pd.isna(mu):
                continue
            mercados[mercado] = {"media": round(mu, 2), "p10": getattr(r, f"p10_{stat}"), "p90": getattr(r, f"p90_{stat}"),
                                 "p_over": {f"{x:g}": round(float(modelo.p_over(mu, k, x)), 4)
                                            for x in modelo.lineas_cercanas(mu, k)}}
        jugadores.append({"jugador": r.jugador, "equipo": r.equipo, "partido": r.partido, "escenario": r.escenario,
                          "estado": r.estado, "minutos": round(r.minutos, 1), "partidos_muestra": r.n_previos,
                          "notas": r.notas, "mercados": mercados})
    destino = config.STAKE / "proyecciones" / f"{fecha}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".tmp")
    temporal.write_text(json.dumps({"generado": db.ahora_utc(), "modelo": config.MODELO_NBA, "fecha": fecha,
                                    "aviso": "Proyección estadística informativa; no cambia el cálculo de /parley.",
                                    "jugadores": jugadores}, ensure_ascii=False, indent=1), encoding="utf-8")
    temporal.replace(destino)
    return destino


def legs_reales() -> pd.DataFrame:
    """Legs de props NBA ya decididos en el registro de /parley, con la fecha local del ticket."""
    tickets, legs = config.STAKE / "registro.csv", config.STAKE / "registro_legs.csv"
    if not tickets.exists() or not legs.exists():
        return pd.DataFrame()
    t = pd.read_csv(tickets, dtype=str)
    l = pd.read_csv(legs, dtype=str).merge(t[["id", "fecha", "deporte"]], left_on="ticket_id", right_on="id")
    l = l[(l.deporte == "nba") & l.mercado.isin(config.MERCADOS_NBA) & l.resultado.isin(["gano", "perdio"])
          & l.lado.isin(["over", "under"]) & l.linea.notna() & l.jugador.notna()].copy()
    l["fecha"] = l.fecha.map(lambda f: datetime.fromisoformat(f).astimezone(config.PANAMA).date().isoformat())
    l["linea"] = l.linea.astype(float)
    for c in ("p_mercado", "p_final"):
        l[c] = pd.to_numeric(l[c], errors="coerce")
    return l[["ticket_id", "leg_id", "fecha", "jugador", "mercado", "linea", "lado", "resultado", "p_mercado", "p_final"]]
