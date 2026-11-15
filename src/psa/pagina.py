"""Página estática para el celular (GitHub Pages, carpeta docs/): foto del día, solo lectura.

Se regenera en cada actualización y se sube con git. El repositorio es público: no se incluyen rutas locales
ni el registro de apuestas, solo proyecciones, lesiones, líneas del día y el resumen del backtest.
"""
import json
import math
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config
from .db import clave_nombre
from .nba import lesiones, proyeccion
from .nba import props as props_nba

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "docs" / "index.html"
CORTOS = {"puntos": "pts", "rebotes": "reb", "asistencias": "ast"}


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
    jugadores = []
    if not pred.empty:
        ancho = {}
        for r in pred.itertuples():
            clave = (r.player_id, r.scenario)
            fila = ancho.setdefault(clave, {"j": r.jugador, "eq": r.equipo, "p": nombres.get(r.game_id, ""),
                                            "esc": r.scenario, "min": limpio(r.minutes, 1),
                                            "sd": limpio(r.minutes_sd, 1), "n": limpio(r.sample_games),
                                            "notas": r.notes or "", "m": {}})
            fila["m"][CORTOS[r.market]] = [limpio(r.projected_mean, 1), limpio(r.lower_interval, 0),
                                           limpio(r.upper_interval, 0)]
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

    props = pd.read_sql("SELECT * FROM player_props WHERE game_date = ?", con, params=(fecha,))
    tabla = props_nba.evaluar(pred, props) if not (pred.empty or props.empty) else pd.DataFrame()
    lineas = [{k: limpio(v) for k, v in fila.items()} for fila in tabla.to_dict("records")]

    corrida = con.execute("SELECT metrics_json, created_at FROM model_runs ORDER BY run_id DESC LIMIT 1").fetchone()
    backtest = {**json.loads(corrida[0]), "fecha": corrida[1][:10]} if corrida else None
    reporte = con.execute("SELECT MAX(reported_at) FROM nba_injuries WHERE game_date = ? AND entry_method = 'PDF'",
                          (fecha,)).fetchone()[0]
    return {
        "fecha": fecha, "generado": datetime.now(config.PANAMA).strftime("%d-%m-%Y %H:%M"),
        "modelo": config.MODELO_NBA, "corte": limpio(pred.data_cutoff.max()) if not pred.empty else None,
        "reporte_lesiones": reporte,
        "partidos": [{"hora": hora_panama(r.start_time_utc), "p": r.partido, "estado": r.status,
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
    temporal.write_text(PLANTILLA.replace("__DATOS__", contenido), encoding="utf-8")
    temporal.replace(destino)
    return destino


def publicar(fecha: str, raiz: Path = RAIZ) -> str:
    """Commit solo de docs/ y push. No toca otros cambios que haya en el repositorio."""
    def git(*args):
        return subprocess.run(["git", "-C", str(raiz), *args], capture_output=True, text=True, timeout=120)

    rutas = ["docs/index.html", "docs/.nojekyll"]
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
<title>parley507</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--text:#14171c;--muted:#5d6673;--line:#e3e6eb;--accent:#0b6bcb;--ok:#127a3e;--warn:#a35c00;--bad:#b42318;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#181c22;--text:#e8ebef;--muted:#9aa4b2;--line:#2a3039;--accent:#5aa9ff;--ok:#4cc38a;--warn:#f0a845;--bad:#ff6b5e;--chip:#222831}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
header{padding:14px 16px 6px;max-width:760px;margin:0 auto}
h1{font-size:20px;margin:0}
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
.vacio{color:var(--muted);text-align:center;padding:30px 0}
</style>
</head>
<body>
<header><h1>parley507</h1><div class="sub" id="sub"></div></header>
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

function stat(nombre, v) {
  return el('div', {class: 'stat'}, el('b', {}, v ? num(v[0]) : '—'), el('span', {}, v ? `${nombre} ${num(v[1], 0)}-${num(v[2], 0)}` : nombre));
}
function tarjetaJugador(j) {
  const c = el('div', {class: 'card'},
    el('div', {class: 'fila'}, el('span', {class: 'nombre'}, j.j), j.est ? el('span', {class: 'badge ' + j.est}, j.est) : ''),
    el('div', {class: 'muted'}, `${j.eq} · ${j.p} · ${num(j.min)} min` + (j.sd ? ` (desv. ${num(j.sd)})` : '') + ` · ${j.n} partidos`),
    el('div', {class: 'stats'}, el('div', {class: 'stat'}, el('b', {}, num(j.min)), el('span', {}, 'minutos')),
      stat('pts', j.m.pts), stat('reb', j.m.reb), stat('ast', j.m.ast)));
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

const vistas = {
  Partidos() {
    if (!D.partidos.length) return [el('p', {class: 'vacio'}, 'Sin partidos NBA este día.')];
    return D.partidos.map(p => el('div', {class: 'card fila'},
      el('span', {}, el('span', {class: 'nombre'}, p.p), el('div', {class: 'muted'}, p.estado + (p.marcador ? ' · ' + p.marcador : ''))),
      el('span', {class: 'badge'}, p.hora)));
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
    for (const p of D.props) {
      if (p['P over'] === undefined || p['P over'] === null) {
        out.push(el('div', {class: 'card'}, el('div', {class: 'nombre'}, `${p.jugador} · ${p.mercado} ${p['línea']}`),
          el('div', {class: 'muted'}, p['estado de datos'])));
        continue;
      }
      out.push(el('div', {class: 'card'},
        el('div', {class: 'fila'}, el('span', {class: 'nombre'}, `${p.jugador} · ${p.mercado} ${p['línea']}`),
          el('span', {class: 'badge'}, `media ${num(p.media)}`)),
        el('div', {class: 'muted'}, `${p.casa} · ${num(p.minutos)} min · rango ${p['rango 10-90']}`),
        el('table', {},
          el('tr', {}, el('th', {}, ''), el('th', {}, 'P modelo'), el('th', {}, 'cuota justa'),
            el('th', {}, p.origen === 'PARLEY_REF' ? 'ref. sin margen' : 'cuota casa'), el('th', {}, 'edge'), el('th', {}, 'VE')),
          ...[['Over', 'over'], ['Under', 'under']].map(([t, k]) => el('tr', {},
            el('td', {}, t), el('td', {}, pct(p['P ' + k])), el('td', {}, num(p['cuota justa ' + k], 2)),
            el('td', {}, num(p['cuota ' + k], 2)), el('td', {class: signo(p['edge ' + k])}, pct(p['edge ' + k])),
            el('td', {class: signo(p['VE ' + k])}, pct(p['VE ' + k]))))),
        p.riesgos && p.riesgos.split('; ').filter(n => !n.startsWith('dispersión')).length
          ? el('div', {class: 'muted'}, '⚠ ' + p.riesgos.split('; ').filter(n => !n.startsWith('dispersión')).join(' · ')) : ''));
    }
    return out.concat(el('p', {class: 'muted'}, 'Edge: modelo menos mercado sin margen, misma línea. VE solo con precio de una casa; el consenso BettingPros es referencia.'));
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
let actual = 'Jugadores';
function mostrar(nombre) {
  actual = nombre;
  for (const b of tabs.children) b.setAttribute('aria-selected', b.textContent === nombre);
  vista.replaceChildren(...vistas[nombre]());
  try { localStorage.setItem('pestana', nombre); } catch (e) {}
}
for (const nombre of Object.keys(vistas)) {
  const b = el('button', {role: 'tab'}, nombre);
  b.addEventListener('click', () => mostrar(nombre));
  tabs.append(b);
}
let guardada = null; try { guardada = localStorage.getItem('pestana'); } catch (e) {}
mostrar(vistas[guardada] ? guardada : actual);
</script>
</body>
</html>
"""
