"""Actualización completa: datos NBA, lesiones, referencias de /parley, proyecciones del día y export.

Uso: uv run actualizar [--fecha AAAA-MM-DD] [--sin-ot] [--sin-publicar]
Al final regenera index.html (página para el celular) y la sube a GitHub Pages.
El botón "Actualizar datos" de la app ejecuta esta misma función.
"""
import argparse
import sys
from datetime import date

import requests

from . import config, db, pagina, parley_io
from .nba import backtest, fuente, lesiones, proyeccion


def actualizar(fecha: str | None = None, con_ot: bool = True, aviso=print, publicar: bool = True) -> dict:
    fecha = fecha or config.hoy_panama().isoformat()
    actual = config.temporada_actual(date.fromisoformat(fecha))
    resumen = {"fecha": fecha, "avisos": []}
    with db.conectar() as con:
        fuente.cargar_equipos(con)
        for t in config.temporadas(date.fromisoformat(fecha)):
            ya = con.execute("SELECT 1 FROM nba_player_game_stats WHERE season = ? LIMIT 1", (t,)).fetchone()
            if t == actual or not ya:  # Las temporadas cerradas se descargan una sola vez.
                aviso(f"Box scores {t}...")
                resumen[f"filas_{t}"] = fuente.cargar_logs(con, t)
                con.commit()
        aviso("Calendario...")
        resumen["partidos_calendario"] = fuente.cargar_calendario(con, actual)
        con.commit()
        if con_ot:
            aviso("Estadísticas sin prórroga de partidos con OT...")
            resumen["partidos_ot"] = fuente.cargar_regulacion(con)

        aviso("Reporte de lesiones...")
        try:
            url, hora = lesiones.ultimo_pdf(actual)
            respuesta = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            respuesta.raise_for_status()
            if len(respuesta.content) > 20_000_000:
                raise lesiones.FormatoCambiado("El PDF pesa más de 20 MB; no parece el reporte.")
            resumen["lesiones"] = lesiones.guardar(con, lesiones.leer_pdf(respuesta.content), url, hora)
            resumen["reporte_lesiones"] = hora
        except Exception as error:  # PDF corrupto o red caída: se avisa y el resto de la actualización sigue.
            db.calidad(con, "nba_injuries", fecha, "pdf_lesiones", "alta", str(error))
            resumen["avisos"].append(f"No se leyó el reporte de lesiones ({error}). Ingresa los estados a mano.")
        con.commit()

        if not con.execute("SELECT 1 FROM model_runs WHERE model_version = ?", (config.MODELO_NBA,)).fetchone():
            aviso("Primer ajuste del modelo (backtest)...")
            backtest.correr(con)

        aviso("Proyecciones del día...")
        recalcular(con, fecha, resumen)
        aviso("Página para el celular...")
        publicar_pagina(con, fecha, resumen, publicar)
    return resumen


def publicar_pagina(con, fecha: str, resumen: dict, subir: bool = True) -> dict:
    """Regenera index.html y, si `subir`, la publica con git. Un fallo de red no rompe la actualización."""
    resumen["pagina"] = str(pagina.generar(con, fecha))
    if subir:
        resumen["publicacion"] = pagina.publicar(fecha)
    return resumen


def recalcular(con, fecha: str, resumen: dict | None = None) -> dict:
    """Proyecta el día con los datos ya guardados (lesiones y minutos manuales incluidos) y exporta a /parley."""
    resumen = resumen if resumen is not None else {"fecha": fecha, "avisos": []}
    df = proyeccion.proyectar_dia(con, fecha)
    if df.empty:
        resumen["avisos"].append(f"No hay partidos NBA el {fecha}.")
        return resumen
    resumen["proyecciones"] = proyeccion.guardar(con, df)
    plantilla = df[["player_id", "jugador", "equipo"]].drop_duplicates()
    resumen["lineas_parley"], avisos = parley_io.cargar_referencias(con, fecha, plantilla)
    resumen["avisos"] += avisos
    resumen["lineas_stake"], avisos = parley_io.cargar_lineas_stake(con, fecha, plantilla)
    resumen["avisos"] += avisos
    resumen["export"] = str(parley_io.exportar(df, fecha))
    con.commit()
    return resumen


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Actualiza datos NBA y proyecciones del día.")
    p.add_argument("--fecha", help="AAAA-MM-DD (hora de Panamá); por defecto hoy")
    p.add_argument("--sin-ot", action="store_true", help="No descarga estadísticas sin prórroga")
    p.add_argument("--sin-publicar", action="store_true", help="Genera la página pero no la sube a GitHub")
    args = p.parse_args(argv)
    try:
        r = actualizar(args.fecha, not args.sin_ot, publicar=not args.sin_publicar)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    for clave, valor in r.items():
        if clave != "avisos":
            print(f"{clave}: {valor}")
    for a in r["avisos"]:
        print(f"AVISO: {a}")
    return 0
