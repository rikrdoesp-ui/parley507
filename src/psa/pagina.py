"""Página estática para el celular (GitHub Pages, raíz del repositorio): foto del día, solo lectura.

Se regenera en cada actualización y se sube con git. El repositorio es público: no se incluyen rutas locales
ni el registro de apuestas, solo proyecciones, lesiones, líneas del día y el resumen del backtest.
"""
import json
import math
import subprocess
import tomllib
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import config, marca
from . import db
from .nba import combinadas
from .db import clave_nombre
from .nba import lesiones, modelo, proyeccion, resultados
from .nba import props as props_nba

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "index.html"  # GitHub Pages publica desde la raíz de main.
CORTOS = {"puntos": "pts", "rebotes": "reb", "asistencias": "ast"}


def version() -> str:
    """Versión de pyproject.toml: una sola fuente para la página y el CHANGELOG."""
    return tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def limpio(valor, decimales: int = 3):
    """NaN -> None (JSON válido); floats redondeados."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return None
    if isinstance(valor, float):
        return round(valor, decimales)
    if hasattr(valor, "item"):  # Tipos de numpy.
        return limpio(valor.item(), decimales)
    return valor


def hora_panama(utc) -> str:
    if not utc or pd.isna(utc):
        return ""
    return datetime.fromisoformat(str(utc).replace("Z", "+00:00")).astimezone(config.PANAMA).strftime("%H:%M")


def analizar_mercado(valores: list, temporada: list, mu, k, real: dict | None) -> dict:
    """Promedios, línea (real o de referencia), probabilidad, lado del modelo y aciertos L10 de un prop.

    `valores`: del partido más reciente al más viejo. Sin línea real, la referencia es la media L10 redondeada
    a x.5 y se marca como tal: sirve para ver qué lado favorece el modelo, no como precio.
    """
    media = lambda v: round(sum(v) / len(v), 1) if v else None
    l10 = media(valores[:10])
    salida = {"l5": media(valores[:5]), "l10": l10, "temp": media(temporada), "media": limpio(mu, 1)}
    if real:
        linea, salida["tipo"], salida["casa"] = real["línea"], "real", real["casa"]
    elif l10 is not None:
        linea, salida["tipo"] = math.floor(l10) + 0.5, "ref"
    else:
        return salida
    salida["linea"] = linea
    if mu is None or pd.isna(mu):
        return salida
    po, pu = float(modelo.p_over(mu, k, linea)), float(modelo.p_under(mu, k, linea))
    if real and real.get("P mezcla over") is not None:
        # Con línea real manda la mezcla anclada al mercado: el lado es el que el modelo empuja sobre el mercado.
        lado = "over" if (real.get("edge over") or 0) >= (real.get("edge under") or 0) else "under"
        p_lado = real[f"P mezcla {lado}"]
    else:
        lado = "over" if po >= pu else "under"
        p_lado = max(po, pu)
    salida.update({"p_over": round(po, 3), "lado": lado, "p_lado": round(p_lado, 3),
                   "p_modelo": round(po if lado == "over" else pu, 3)})
    # El lado más probable (para la tabla del jugador), que no siempre es el que el modelo empuja sobre el mercado.
    if real and real.get("P mezcla over") is not None:
        alto = "over" if real["P mezcla over"] >= real["P mezcla under"] else "under"
        pm = real.get("P mercado over (sin margen)")
        salida["alto"] = {"lado": alto, "p": round(real[f"P mezcla {alto}"], 3), "ve": limpio(real.get(f"VE {alto}")),
                          "cuota": limpio(real.get(f"cuota {alto}"), 2),
                          "pm": None if pm is None else round(pm if alto == "over" else 1 - pm, 3)}
    else:
        alto = lado
        salida["alto"] = {"lado": lado, "p": salida["p_lado"], "ve": None}
    ultimos = valores[:10]  # Aciertos del lado más probable en sus últimos 10.
    salida["aciertos"] = [int(sum((v > linea) if alto == "over" else (v < linea) for v in ultimos)), len(ultimos)]
    if real:
        p_mercado = real.get("P mercado over (sin margen)")
        salida.update({"edge": limpio(real.get(f"edge {lado}")), "ve": limpio(real.get(f"VE {lado}")),
                       "cuota": limpio(real.get(f"cuota {lado}"), 2), "origen": real["origen"],
                       "p_mercado": None if p_mercado is None else round(p_mercado if lado == "over" else 1 - p_mercado, 3)})
    return salida


def favorito(partido: str, margen_local) -> str:
    """'SAS por 20' con el spread estimado propio; vacío si no hay dato o es parejo."""
    if margen_local is None or pd.isna(margen_local) or abs(margen_local) < 1:
        return "parejo" if margen_local is not None and not pd.isna(margen_local) else ""
    visita, _, local = partido.partition(" @ ")
    return f"{local if margen_local > 0 else visita} por {abs(margen_local):.0f}"


def datos(con, fecha: str) -> dict:
    juegos = pd.read_sql("""SELECT g.game_id, g.start_time_utc, a.abbreviation || ' @ ' || h.abbreviation AS partido,
                              g.status, g.away_score, g.home_score, g.home_team_id FROM games g
                            JOIN teams h ON h.team_id = g.home_team_id JOIN teams a ON a.team_id = g.away_team_id
                            WHERE g.game_date = ? ORDER BY g.start_time_utc""", con, params=(fecha,))
    nombres = dict(zip(juegos.game_id, juegos.partido))
    spreads = proyeccion.spreads_estimados(con)
    equipos = dict(con.execute("SELECT team_id, abbreviation FROM teams"))
    pred = proyeccion.ultimas(con, fecha)

    estados = lesiones.vigentes(con, fecha)
    estado = dict(zip(estados.clave, estados.status)) if not estados.empty else {}

    props = pd.read_sql("SELECT * FROM player_props WHERE game_date = ?", con, params=(fecha,))
    tabla = props_nba.evaluar(pred, props) if not (pred.empty or props.empty) else pd.DataFrame()
    lineas = [{k: limpio(v) for k, v in fila.items()} for fila in tabla.to_dict("records")]
    partido_de = {int(r.player_id): nombres.get(r.game_id, "") for r in pred.itertuples()} if not pred.empty else {}
    for fila in lineas:
        fila["partido"] = partido_de.get(int(fila["player_id"]), "") if fila.get("player_id") is not None else ""
    # Línea real por jugador y mercado: la de una casa (manual) manda sobre el consenso de referencia.
    reales = {}
    for fila in sorted(lineas, key=lambda f: not props_nba.es_consenso(f["casa"])):
        if fila.get("P over") is not None and fila.get("player_id") is not None:
            reales[(int(fila["player_id"]), fila["mercado"])] = fila

    jugadores = []
    if not pred.empty:
        hist = proyeccion.historial(con)
        hist = hist[hist.game_date < fecha].sort_values("game_date", ascending=False)
        temporada = config.temporada_actual(date.fromisoformat(fecha))
        previos = {pid: g for pid, g in hist[hist.player_id.isin(pred.player_id.unique())].groupby("player_id")}
        ancho = {}
        for r in pred.itertuples():
            clave = (r.player_id, r.scenario)
            fila = ancho.setdefault(clave, {"j": r.jugador, "eq": r.equipo, "p": nombres.get(r.game_id, ""),
                                            "esc": r.scenario, "min": limpio(r.minutes, 1),
                                            "sd": limpio(r.minutes_sd, 1), "n": limpio(r.sample_games),
                                            "notas": r.notes or "", "m": {}, "props": {}})
            fila["m"][CORTOS[r.market]] = [limpio(r.projected_mean, 1), limpio(r.lower_interval, 0),
                                           limpio(r.upper_interval, 0)]
            if r.scenario == "base":
                g = previos.get(r.player_id, hist.iloc[:0])
                stat = config.MERCADOS_NBA[r.market]
                fila["props"][CORTOS[r.market]] = analizar_mercado(
                    g[stat].dropna().tolist(), g[g.season == temporada][stat].dropna().tolist(),
                    None if pd.isna(r.projected_mean) else r.projected_mean, r.dispersion,
                    reales.get((int(r.player_id), r.market)))
        for (pid, esc), fila in ancho.items():
            if esc != "base":
                continue
            fila["est"] = estado.get(clave_nombre(fila["j"]), "")
            # Escenarios donde a este jugador le cambian los minutos (un compañero en duda no juega).
            fila["otros"] = [{"esc": e, "min": f["min"], "m": f["m"]} for (p, e), f in ancho.items()
                             if p == pid and e != "base" and abs((f["min"] or 0) - (fila["min"] or 0)) >= 0.5]
            jugadores.append(fila)
        jugadores.sort(key=lambda f: -(f["min"] or 0))

    lista_lesiones = [] if estados.empty else [
        {"j": r.player_name, "eq": equipos.get(r.team_id, "") if pd.notna(r.team_id) else "", "est": r.status,
         "motivo": r.reason or "", "manual": bool(r.manual)}
        for r in estados.sort_values(["team_id", "player_name"]).itertuples()]

    corrida = con.execute("SELECT metrics_json, created_at FROM model_runs WHERE model_version = ? ORDER BY run_id DESC LIMIT 1",
                          (config.MODELO_NBA,)).fetchone()
    backtest = {**json.loads(corrida[0]), "fecha": corrida[1][:10]} if corrida else None
    reporte = con.execute("SELECT MAX(reported_at) FROM nba_injuries WHERE game_date = ? AND entry_method = 'PDF'",
                          (fecha,)).fetchone()[0]
    return {
        "fecha": fecha, "generado": datetime.now(config.PANAMA).strftime("%d-%m-%Y %H:%M"),
        "generado_utc": db.ahora_utc(),
        "modelo": config.MODELO_NBA, "corte": limpio(pred.data_cutoff.max()) if not pred.empty else None,
        "reporte_lesiones": reporte,
        "partidos": [{"hora": hora_panama(r.start_time_utc), "p": r.partido, "estado": r.status,
                      "favorito": favorito(r.partido, spreads.get((r.game_id, r.home_team_id))),
                      "inicio": r.start_time_utc if isinstance(r.start_time_utc, str) else None,
                      "marcador": f"{int(r.away_score)}-{int(r.home_score)}" if pd.notna(r.away_score) else ""}
                     for r in juegos.itertuples()],
        "jugadores": jugadores, "lesiones": lista_lesiones, "props": lineas, "con_precio": props_nba.hay_precio(tabla),
        "backtest": backtest,
        "resultados": resultados.ultimas_metricas(con),
        "parleys": combinadas.armar(jugadores),
    }


def generar(con, fecha: str, destino: Path = DESTINO) -> Path:
    contenido = json.dumps(datos(con, fecha), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    destino.parent.mkdir(parents=True, exist_ok=True)
    (destino.parent / ".nojekyll").touch()
    temporal = destino.with_suffix(".tmp")
    logo = marca.svg({"fondo": "var(--logo-fondo)"})  # Las muescas del boleto toman el fondo del tema.
    html = PLANTILLA.replace("__VERSION__", version()).replace("__LOGO__", logo).replace("__DATOS__", contenido)
    temporal.write_text(html, encoding="utf-8")
    temporal.replace(destino)
    return destino


def publicar(fecha: str, raiz: Path = RAIZ) -> str:
    """Commit solo de la página y push. No toca otros cambios que haya en el repositorio."""
    def git(*args):
        return subprocess.run(["git", "-C", str(raiz), *args], capture_output=True, text=True, timeout=120)

    rutas = ["index.html", ".nojekyll"]
    git("add", *rutas)
    if git("diff", "--cached", "--quiet", "--", *rutas).returncode == 0:
        return "La página no cambió; no hay nada que subir."
    hecho = git("commit", "-m", f"Página del {fecha}", "--", *rutas)
    if hecho.returncode:
        return f"No se pudo hacer el commit de la página: {hecho.stderr.strip() or hecho.stdout.strip()}"
    subida = git("push")
    if subida.returncode:
        return f"La página quedó en un commit local, pero el push falló: {subida.stderr.strip()}"
    return "Página publicada en GitHub Pages."


# La plantilla vive aparte para poder editarla como HTML; __VERSION__ y __DATOS__ se reemplazan al generar.
PLANTILLA = Path(__file__).with_name("pagina.html").read_text(encoding="utf-8")
