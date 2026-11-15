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

from . import config
from .db import clave_nombre
from .nba import lesiones, modelo, proyeccion
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
    ultimos = valores[:10]
    aciertos = sum((v > linea) if lado == "over" else (v < linea) for v in ultimos)
    salida.update({"p_over": round(po, 3), "lado": lado, "p_lado": round(p_lado, 3),
                   "p_modelo": round(po if lado == "over" else pu, 3), "aciertos": [int(aciertos), len(ultimos)]})
    if real:
        p_mercado = real.get("P mercado over (sin margen)")
        salida.update({"edge": limpio(real.get(f"edge {lado}")), "ve": limpio(real.get(f"VE {lado}")),
                       "cuota": limpio(real.get(f"cuota {lado}"), 2), "origen": real["origen"],
                       "p_mercado": None if p_mercado is None else round(p_mercado if lado == "over" else 1 - p_mercado, 3)})
    return salida


def datos(con, fecha: str) -> dict:
    juegos = pd.read_sql("""SELECT g.game_id, g.start_time_utc, a.abbreviation || ' @ ' || h.abbreviation AS partido,
                              g.status, g.away_score, g.home_score FROM games g
                            JOIN teams h ON h.team_id = g.home_team_id JOIN teams a ON a.team_id = g.away_team_id
                            WHERE g.game_date = ? ORDER BY g.start_time_utc""", con, params=(fecha,))
    nombres = dict(zip(juegos.game_id, juegos.partido))
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

    corrida = con.execute("SELECT metrics_json, created_at FROM model_runs ORDER BY run_id DESC LIMIT 1").fetchone()
    backtest = {**json.loads(corrida[0]), "fecha": corrida[1][:10]} if corrida else None
    reporte = con.execute("SELECT MAX(reported_at) FROM nba_injuries WHERE game_date = ? AND entry_method = 'PDF'",
                          (fecha,)).fetchone()[0]
    return {
        "fecha": fecha, "generado": datetime.now(config.PANAMA).strftime("%d-%m-%Y %H:%M"),
        "modelo": config.MODELO_NBA, "corte": limpio(pred.data_cutoff.max()) if not pred.empty else None,
        "reporte_lesiones": reporte,
        "partidos": [{"hora": hora_panama(r.start_time_utc), "p": r.partido, "estado": r.status,
                      "inicio": r.start_time_utc if isinstance(r.start_time_utc, str) else None,
                      "marcador": f"{int(r.away_score)}-{int(r.home_score)}" if pd.notna(r.away_score) else ""}
                     for r in juegos.itertuples()],
        "jugadores": jugadores, "lesiones": lista_lesiones, "props": lineas, "con_precio": props_nba.hay_precio(tabla),
        "backtest": backtest,
    }


def generar(con, fecha: str, destino: Path = DESTINO) -> Path:
    contenido = json.dumps(datos(con, fecha), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    destino.parent.mkdir(parents=True, exist_ok=True)
    (destino.parent / ".nojekyll").touch()
    temporal = destino.with_suffix(".tmp")
    temporal.write_text(PLANTILLA.replace("__VERSION__", version()).replace("__DATOS__", contenido), encoding="utf-8")
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


PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="robots" content="noindex">
<title>parley507 v__VERSION__</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--text:#14171c;--muted:#5d6673;--line:#e3e6eb;--accent:#0b6bcb;--ok:#127a3e;--warn:#a35c00;--bad:#b42318;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#181c22;--text:#e8ebef;--muted:#9aa4b2;--line:#2a3039;--accent:#5aa9ff;--ok:#4cc38a;--warn:#f0a845;--bad:#ff6b5e;--chip:#222831}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
header{padding:14px 16px 6px;max-width:760px;margin:0 auto}
h1{font-size:20px;margin:0}
.version{font-size:13px;font-weight:500;color:var(--muted);vertical-align:middle}
.sub{color:var(--muted);font-size:13px;margin-top:2px}
nav{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);display:flex;gap:4px;padding:8px 12px;overflow-x:auto;max-width:760px;margin:0 auto}
nav button{flex:0 0 auto;border:0;border-radius:999px;padding:8px 14px;background:var(--chip);color:var(--text);font:inherit;font-size:14px}
nav button[aria-selected=true]{background:var(--accent);color:#fff}
main{max-width:760px;margin:0 auto;padding:12px 16px 40px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:10px}
.fila{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.nombre{font-weight:600}
.muted{color:var(--muted);font-size:13px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}
.stat{background:var(--chip);border-radius:8px;padding:6px;text-align:center}
.stat b{display:block;font-size:17px}
.stat span{font-size:11px;color:var(--muted)}
.badge{font-size:12px;padding:2px 8px;border-radius:999px;background:var(--chip);white-space:nowrap}
.Out{color:var(--bad)}.Doubtful,.Questionable{color:var(--warn)}.Probable,.Available{color:var(--ok)}
.aviso{border-left:4px solid var(--warn);background:var(--card);padding:10px 12px;border-radius:8px;margin-bottom:10px;font-size:14px}
.controles{display:flex;gap:8px;margin-bottom:10px}
input,select{font:inherit;font-size:16px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--text);min-width:0}
input{flex:1}
details{margin-top:8px}
summary{color:var(--accent);font-size:13px;cursor:pointer}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:right;padding:6px 4px;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
.pos{color:var(--ok)}.neg{color:var(--bad)}
a.juego{color:inherit;text-decoration:none;display:flex}
a.juego:active{background:var(--chip)}
.volver{display:inline-block;color:var(--accent);text-decoration:none;padding:4px 0 8px;font-size:15px}
h2{font-size:19px;margin:2px 0}
h3{font-size:16px;margin:18px 0 8px}
table.props{margin-top:8px;font-size:12.5px}
table.props td,table.props th{padding:5px 3px;vertical-align:top}
table.props td div{font-size:11px}
.mejor{padding:8px 0;border-top:1px solid var(--line)}
.mejor:first-of-type{border-top:0}
.badge.real{background:var(--accent);color:#fff}
.grupo{margin:18px 2px 8px}
.grupo a.nombre{color:var(--text);text-decoration:none;font-size:16px}
.reloj{font-weight:600}
.vacio{color:var(--muted);text-align:center;padding:30px 0}
</style>
</head>
<body>
<header><h1>parley507 <span class="version">v__VERSION__</span></h1><div class="sub" id="sub"></div></header>
<nav id="tabs" role="tablist"></nav>
<main id="vista"></main>
<script type="application/json" id="datos">__DATOS__</script>
<script>
const D = JSON.parse(document.getElementById('datos').textContent);
const el = (tag, attrs = {}, ...hijos) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) k === 'class' ? n.className = v : n.setAttribute(k, v);
  for (const h of hijos.flat()) if (h !== null && h !== undefined && h !== '') n.append(h instanceof Node ? h : String(h));
  return n;
};
const pct = x => x === null || x === undefined ? '—' : (x * 100).toFixed(1) + ' %';
const num = (x, d = 1) => x === null || x === undefined ? '—' : Number(x).toFixed(d);
const signo = x => x === null || x === undefined ? '' : x > 0 ? 'pos' : 'neg';
document.getElementById('sub').textContent =
  `NBA · ${D.fecha} · actualizado ${D.generado} (Panamá)` + (D.reporte_lesiones ? ` · lesiones ${D.reporte_lesiones}` : '');

const NOMBRES = {pts: 'Puntos', reb: 'Rebotes', ast: 'Asist.'};
// Cuenta regresiva hasta el inicio y, después, minutos desde que empezó (reloj real, no el del partido).
const duracion = m => m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
function relojTexto(iso, estado) {
  if (estado === 'final') return 'final';
  if (!iso) return '';
  const min = Math.round((Date.parse(iso) - Date.now()) / 60000);
  if (min > 0) return `empieza en ${duracion(min)}`;
  if (-min <= 180) return `en juego · lleva ${duracion(-min)}`;
  return `empezó hace ${duracion(-min)} · ya debería haber terminado`;
}
const reloj = p => el('span', {class: 'reloj', 'data-inicio': p.inicio || '', 'data-estado': p.estado || ''}, relojTexto(p.inicio, p.estado));
setInterval(() => document.querySelectorAll('.reloj').forEach(n => n.textContent = relojTexto(n.dataset.inicio, n.dataset.estado)), 30000);
const lado = p => p.lado === 'over' ? 'Over' : 'Under';
function celdaModelo(p) {
  if (!p.lado) return el('td', {}, '—');
  const ve = p.ve !== null && p.ve !== undefined;
  return el('td', {class: ve && p.ve > 0 ? 'pos' : ''}, el('b', {}, `${lado(p)} ${pct(p.p_lado).replace(' %', '%')}`),
    ve ? el('div', {class: signo(p.ve)}, `VE ${p.ve > 0 ? '+' : ''}${(p.ve * 100).toFixed(1)}`) : '');
}
function tablaProps(j) {
  return el('table', {class: 'props'},
    el('tr', {}, el('th', {}, 'Prop'), el('th', {}, 'L5'), el('th', {}, 'L10'), el('th', {}, 'Temp'), el('th', {}, 'Proy'),
      el('th', {}, 'Línea'), el('th', {}, 'Modelo')),
    ...['pts', 'reb', 'ast'].map(k => {
      const p = j.props[k] || {};
      return el('tr', {}, el('td', {}, NOMBRES[k]), el('td', {}, num(p.l5)), el('td', {}, num(p.l10)), el('td', {}, num(p.temp)),
        el('td', {}, el('b', {}, num(p.media))),
        el('td', {}, p.linea === undefined ? '—' : num(p.linea) + (p.tipo === 'ref' ? '*' : ''),
          p.aciertos ? el('div', {class: 'muted'}, `${p.aciertos[0]}/${p.aciertos[1]}`) : ''),
        celdaModelo(p));
    }));
}
function tarjetaJugador(j) {
  const c = el('div', {class: 'card'},
    el('div', {class: 'fila'}, el('span', {class: 'nombre'}, j.j), j.est ? el('span', {class: 'badge ' + j.est}, j.est) : ''),
    el('div', {class: 'muted'}, `${j.eq} · ${j.p} · ${num(j.min)} min proyectados` + (j.sd ? ` (desv. ${num(j.sd)})` : '') + ` · ${j.n} partidos`),
    tablaProps(j));
  if (j.otros.length) {
    const d = el('details', {}, el('summary', {}, `Escenarios (${j.otros.length})`));
    for (const o of j.otros) d.append(el('div', {class: 'muted'},
      `${o.esc}: ${num(o.min)} min · pts ${num(o.m.pts && o.m.pts[0])} · reb ${num(o.m.reb && o.m.reb[0])} · ast ${num(o.m.ast && o.m.ast[0])}`));
    c.append(d);
  }
  const notas = j.notas.split('; ').filter(n => !n.startsWith('dispersión')).join(' · ');
  if (notas) c.append(el('div', {class: 'muted'}, '⚠ ' + notas));
  return c;
}

const NOTA_LINEA = 'Con línea real, la probabilidad es una mezcla: parte del mercado sin margen y el modelo la mueve como mucho 4 puntos, '
  + 'porque el modelo aún no le gana al mercado. VE = mezcla × cuota − 1. '
  + '* Línea de referencia (media L10 redondeada), sin cuota: solo indica el lado del modelo, no si hay valor. '
  + 'x/10: veces que superó (over) o no llegó (under) a la línea en sus últimos 10. BET/PASS lo decide /parley.';

// Mejores props del partido: primero las de línea real con edge a favor; luego, con línea de referencia,
// las de mayor probabilidad entre jugadores de rotación (20+ min), para no premiar unders de suplentes.
function mejoresProps(jugadores) {
  const todas = [];
  for (const j of jugadores) for (const k of ['pts', 'reb', 'ast']) {
    const p = j.props[k];
    if (!p || !p.lado || j.notas.includes('muestra insuficiente')) continue;
    if (p.tipo === 'ref' && (j.min || 0) < 20) continue;
    todas.push({j, k, p, orden: p.tipo === 'real' ? [0, -(p.ve ?? p.edge ?? -1)] : [1, -p.p_lado]});
  }
  return todas.filter(x => x.p.tipo === 'ref' || x.p.edge > 0)
    .sort((a, b) => a.orden[0] - b.orden[0] || a.orden[1] - b.orden[1]).slice(0, 8);
}
function vistaJuego(nombre) {
  const p = D.partidos.find(x => x.p === nombre);
  const jug = D.jugadores.filter(j => j.p === nombre);
  const out = [el('a', {href: '#', class: 'volver'}, '← Partidos'),
    el('h2', {}, nombre), el('div', {class: 'muted'}, p ? [`${p.hora} (Panamá) · `, reloj(p), p.marcador ? ' · ' + p.marcador : ''] : '')];
  if (!jug.length) return out.concat(el('p', {class: 'vacio'}, 'Sin proyecciones para este partido.'));
  const mejores = mejoresProps(jug);
  const caja = el('div', {class: 'card'}, el('div', {class: 'nombre'}, 'Mejores props del partido'));
  if (!mejores.length) caja.append(el('div', {class: 'muted'}, 'Ninguna prop destaca.'));
  if (mejores.some(x => x.p.tipo === 'real') && !mejores.some(x => x.p.ve > 0))
    caja.append(el('div', {class: 'aviso'}, 'Ninguna línea de Stake tiene VE positivo: estas son las que el modelo empuja a favor, pero el margen de la casa las deja en negativo.'));
  for (const {j, k, p} of mejores) caja.append(el('div', {class: 'mejor'},
    el('div', {class: 'fila'}, el('span', {}, el('b', {}, j.j), ` ${NOMBRES[k]} ${lado(p)} ${num(p.linea)}`),
      el('span', {class: 'badge ' + (p.tipo === 'real' ? 'real' : '')}, p.tipo === 'real' ? 'línea real' : 'referencia')),
    el('div', {class: 'muted'}, (p.tipo === 'real' && p.p_mercado !== undefined && p.p_mercado !== null
        ? `Mezcla ${pct(p.p_lado)} (mercado ${pct(p.p_mercado)}, modelo ${pct(p.p_modelo)})` : `Modelo ${pct(p.p_lado)}`)
      + ` · proy ${num(p.media)} · L10 ${num(p.l10)} · ${p.aciertos[0]}/${p.aciertos[1]}`
      + (p.ve !== undefined && p.ve !== null ? ` · VE ${p.ve > 0 ? '+' : ''}${(p.ve * 100).toFixed(1)}` : '')
      + (p.cuota && !String(p.casa).startsWith('Consenso') ? ` · cuota ${num(p.cuota, 2)}` : '')
      + (j.est ? ` · ⚠ ${j.est}` : '') + (j.sd > 6 ? ' · ⚠ minutos inestables' : ''))));
  out.push(caja, el('p', {class: 'muted'}, NOTA_LINEA));
  for (const equipo of [...new Set(jug.map(j => j.eq))]) {
    out.push(el('h3', {}, equipo), ...jug.filter(j => j.eq === equipo).map(tarjetaJugador));
  }
  return out;
}

function tarjetaProp(p) {
  if (p['P over'] === undefined || p['P over'] === null)
    return el('div', {class: 'card'}, el('div', {class: 'nombre'}, `${p.jugador} · ${p.mercado} ${p['línea']}`),
      el('div', {class: 'muted'}, p['estado de datos']));
  return el('div', {class: 'card'},
        el('div', {class: 'fila'}, el('span', {class: 'nombre'}, `${p.jugador} · ${p.mercado} ${p['línea']}`),
          el('span', {class: 'badge'}, `media ${num(p.media)}`)),
        el('div', {class: 'muted'}, `${p.casa} · ${num(p.minutos)} min · rango ${p['rango 10-90']}`),
        el('table', {},
          el('tr', {}, el('th', {}, ''), el('th', {}, 'P mezcla'), el('th', {}, 'cuota justa'),
            el('th', {}, String(p.casa).startsWith('Consenso') ? 'ref. sin margen' : 'cuota casa'), el('th', {}, 'edge'), el('th', {}, 'VE')),
          ...[['Over', 'over'], ['Under', 'under']].map(([t, k]) => el('tr', {},
            el('td', {}, t), el('td', {}, pct(p['P mezcla ' + k] ?? p['P ' + k])), el('td', {}, num(p['cuota justa ' + k], 2)),
            el('td', {}, num(p['cuota ' + k], 2)), el('td', {class: signo(p['edge ' + k])}, pct(p['edge ' + k])),
            el('td', {class: signo(p['VE ' + k])}, pct(p['VE ' + k]))))),
        p.riesgos && p.riesgos.split('; ').filter(n => !n.startsWith('dispersión')).length
          ? el('div', {class: 'muted'}, '⚠ ' + p.riesgos.split('; ').filter(n => !n.startsWith('dispersión')).join(' · ')) : '');
}

const vistas = {
  Partidos() {
    if (!D.partidos.length) return [el('p', {class: 'vacio'}, 'Sin partidos NBA este día.')];
    return [el('p', {class: 'muted'}, 'Toca un partido para ver sus props.'),
      ...D.partidos.map(p => el('a', {class: 'card fila juego', href: '#juego=' + encodeURIComponent(p.p)},
        el('span', {}, el('span', {class: 'nombre'}, p.p), el('div', {class: 'muted'}, reloj(p), p.marcador ? ' · ' + p.marcador : '')),
        el('span', {class: 'badge'}, p.hora + ' ›')))];
  },
  Jugadores() {
    const buscar = el('input', {type: 'search', placeholder: 'Buscar jugador', 'aria-label': 'Buscar jugador'});
    const partido = el('select', {'aria-label': 'Partido'}, el('option', {value: ''}, 'Todos'),
      ...D.partidos.map(p => el('option', {value: p.p}, p.p)));
    const lista = el('div');
    const pintar = () => {
      const q = buscar.value.trim().toLowerCase();
      const filas = D.jugadores.filter(j => (!q || j.j.toLowerCase().includes(q)) && (!partido.value || j.p === partido.value));
      const tope = 120;
      lista.replaceChildren(...(filas.length ? filas.slice(0, tope).map(tarjetaJugador) : [el('p', {class: 'vacio'}, 'Sin jugadores.')]),
        filas.length > tope ? el('p', {class: 'muted'}, `Mostrando ${tope} de ${filas.length}: filtra por partido o busca un nombre.`) : '');
    };
    buscar.addEventListener('input', pintar); partido.addEventListener('change', pintar); pintar();
    return [el('div', {class: 'controles'}, buscar, partido),
      el('p', {class: 'muted'}, 'Media proyectada y rango 10-90 %. Solo informativo: BET/PASS lo decide /parley.'), lista];
  },
  Props() {
    const out = [];
    if (!D.con_precio) out.push(el('div', {class: 'aviso'}, 'PROYECCIÓN ESTADÍSTICA — SIN VALOR DE APUESTA CONFIRMADO'));
    if (!D.props.length) return out.concat(el('p', {class: 'vacio'}, 'No hay líneas cargadas para este día.'));
    // Agrupadas por partido, en orden de inicio; dentro de cada partido, por VE (ya vienen ordenadas).
    const grupos = new Map(D.partidos.map(p => [p.p, []]));
    for (const p of D.props) {
      const clave = p.partido || 'Sin partido identificado';
      if (!grupos.has(clave)) grupos.set(clave, []);
      grupos.get(clave).push(p);
    }
    for (const [nombre, lista] of grupos) {
      if (!lista.length) continue;
      const juego = D.partidos.find(x => x.p === nombre);
      out.push(el('div', {class: 'grupo'}, el('a', {class: 'nombre', href: '#juego=' + encodeURIComponent(nombre)}, nombre),
        el('div', {class: 'muted'}, juego ? [`${juego.hora} (Panamá) · `, reloj(juego), ` · ${lista.length} líneas`] : '')));
      out.push(...lista.map(tarjetaProp));
    }
    return out.concat(el('p', {class: 'muted'}, 'P mezcla: mercado sin margen movido por el modelo (máx. 4 puntos). Edge: mezcla menos mercado. VE solo con precio de una casa; el consenso BettingPros es referencia.'));
  },
  Lesiones() {
    if (!D.lesiones.length) return [el('p', {class: 'vacio'}, 'Sin reporte de lesiones para este día.')];
    return D.lesiones.map(l => el('div', {class: 'card'},
      el('div', {class: 'fila'}, el('span', {class: 'nombre'}, `${l.j}`), el('span', {class: 'badge ' + l.est}, l.est + (l.manual ? ' (manual)' : ''))),
      el('div', {class: 'muted'}, `${l.eq} · ${l.motivo}`)));
  },
  Modelo() {
    const b = D.backtest;
    if (!b) return [el('p', {class: 'vacio'}, 'Aún no hay backtest.')];
    const out = [el('p', {class: 'muted'}, `${D.modelo} · backtest del ${b.fecha} · datos hasta ${D.corte || '—'}. Brier: menor es mejor.`)];
    for (const [temp, m] of Object.entries(b.metricas)) {
      out.push(el('div', {class: 'card'}, el('div', {class: 'nombre'}, `Temporada ${temp}`),
        el('table', {}, el('tr', {}, el('th', {}, ''), el('th', {}, 'Brier modelo'), el('th', {}, 'Brier L10'), el('th', {}, 'MAE'), el('th', {}, 'cob. 10-90')),
          ...Object.entries(m).map(([s, v]) => el('tr', {}, el('td', {}, s), el('td', {}, num(v.brier_modelo, 3)),
            el('td', {}, num(v.brier_acierto_l10, 3)), el('td', {}, num(v.mae_modelo, 2)), el('td', {}, pct(v.cobertura_10_90)))))));
    }
    const l = b.legs_reales;
    if (l && l.legs_decididos) out.push(el('div', {class: 'card'}, el('div', {class: 'nombre'}, 'Legs reales de /parley'),
      el('div', {class: 'muted'}, `${l.legs_comparables} de 100 legs comparables · Brier app ${num(l.comparables_brier_app, 3)} · mercado ${num(l.comparables_brier_mercado, 3)} · /parley ${num(l.comparables_brier_parley, 3)}`),
      el('div', {class: 'muted'}, l.muestra_suficiente ? 'Muestra suficiente para decidir.' : 'Muestra insuficiente: la app sigue siendo informativa.')));
    return out;
  },
};
const tabs = document.getElementById('tabs'), vista = document.getElementById('vista');
let actual = 'Partidos';
function mostrar(nombre) {
  actual = nombre;
  for (const b of tabs.children) b.setAttribute('aria-selected', b.textContent === nombre);
  vista.replaceChildren(...vistas[nombre]());
  try { localStorage.setItem('pestana', nombre); } catch (e) {}
}
// #juego=NOMBRE abre un partido; así el botón "atrás" del celular vuelve a la lista.
function ruta() {
  const m = location.hash.match(/^#juego=(.+)$/);
  if (m) {
    for (const b of tabs.children) b.setAttribute('aria-selected', b.textContent === 'Partidos');
    vista.replaceChildren(...vistaJuego(decodeURIComponent(m[1])));
    scrollTo(0, 0);
  } else {
    mostrar(actual);
  }
}
for (const nombre of Object.keys(vistas)) {
  const b = el('button', {role: 'tab'}, nombre);
  b.addEventListener('click', () => { actual = nombre; location.hash ? (location.hash = '') : mostrar(nombre); });
  tabs.append(b);
}
let guardada = null; try { guardada = localStorage.getItem('pestana'); } catch (e) {}
if (vistas[guardada]) actual = guardada;
addEventListener('hashchange', ruta);
ruta();
</script>
</body>
</html>
"""
