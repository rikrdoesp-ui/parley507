"""Evaluación de líneas de props contra las proyecciones. Lo usan la app y la página para el celular.

La probabilidad con la que se calculan edge y VE parte del mercado sin margen y se mueve hacia el modelo solo un
PESO_MODELO, con el mismo tope que usa /parley. Motivo: contra los legs reales el modelo todavía no le gana al
mercado, y sin ancla sus errores (minutos, roles, bajas) aparecen como "edge". La probabilidad del modelo puro se
sigue mostrando como dato.
"""
import numpy as np
import pandas as pd

from .. import odds
from . import modelo

# shortcut: peso fijo inicial; ajustarlo por Brier cuando haya 100 legs comparables (página Backtest).
PESO_MODELO = 0.25
MAX_DESVIO = {"consenso": 0.03, "dos_lados": 0.04, "un_lado": 0.05}  # Mismos límites que /parley.
MARGEN_UN_LADO = 0.08  # Con una sola cuota, su implícita lleva todo el margen: se descuenta como en /parley.


def es_consenso(casa: str) -> bool:
    return str(casa).startswith("Consenso")


def mercado_over(over, under, casa: str) -> tuple[float, str]:
    """Probabilidad sin margen del over y de dónde sale (para el tope de desvío)."""
    if pd.notna(over) and pd.notna(under):
        return odds.sin_margen(over, under), "consenso" if es_consenso(casa) else "dos_lados"
    if pd.notna(over):
        return (1 / over) / (1 + MARGEN_UN_LADO), "un_lado"
    if pd.notna(under):
        return 1 - (1 / under) / (1 + MARGEN_UN_LADO), "un_lado"
    return np.nan, ""


def mezclar(p_mercado: float, p_modelo: float, fuente: str) -> float:
    """El mercado manda; el modelo lo mueve un PESO_MODELO, sin pasar el tope de su fuente."""
    tope = MAX_DESVIO[fuente]
    return float(np.clip(p_mercado + PESO_MODELO * (p_modelo - p_mercado), p_mercado - tope, p_mercado + tope))


def evaluar(pred: pd.DataFrame, props: pd.DataFrame, escenario: str = "base") -> pd.DataFrame:
    """Una fila por línea (última captura): probabilidades, cuotas justas, edge y VE, ordenadas por VE y edge."""
    proy = pred[pred.scenario == escenario].set_index(["player_id", "market"])
    props = props.groupby(["player_name", "market", "line", "bookmaker", "entry_method"]).tail(1)  # Última captura.
    filas = []
    for p in props.itertuples():
        clave = (p.player_id, p.market)
        base = {"player_id": p.player_id, "jugador": p.player_name, "mercado": p.market, "línea": p.line,
                "casa": p.bookmaker, "origen": p.entry_method}
        if pd.isna(p.player_id) or clave not in proy.index:
            filas.append({**base, "estado de datos": "sin proyección (jugador no identificado o fuera)"})
            continue
        r = proy.loc[clave]
        if pd.isna(r.projected_mean):
            filas.append({**base, "estado de datos": "muestra insuficiente"})
            continue
        po = float(modelo.p_over(r.projected_mean, r.dispersion, p.line))
        pu = float(modelo.p_under(r.projected_mean, r.dispersion, p.line))
        empate = max(0.0, 1 - po - pu)  # Push en línea entera.
        p_mercado, fuente = mercado_over(p.over_odds, p.under_odds, p.bookmaker)
        hay_mercado = pd.notna(p_mercado)
        mo = mezclar(p_mercado, po, fuente) if hay_mercado else np.nan
        mu_ = (1 - mo - empate) if hay_mercado else np.nan
        # El consenso de BettingPros ya viene sin margen: su "cuota" no es un precio apostable, no tiene VE.
        apostable = not es_consenso(p.bookmaker)
        filas.append({
            **base, "equipo": r.equipo, "media": r.projected_mean,
            "rango 10-90": f"{r.lower_interval:.0f}-{r.upper_interval:.0f}", "minutos": r.minutes,
            "P over": po, "P under": pu, "P mercado over (sin margen)": p_mercado,
            "P mezcla over": mo, "P mezcla under": mu_,
            "cuota justa over": odds.cuota_justa(mo) if hay_mercado else odds.cuota_justa(po),
            "cuota justa under": odds.cuota_justa(mu_) if hay_mercado else odds.cuota_justa(pu),
            "cuota over": p.over_odds, "cuota under": p.under_odds,
            "edge over": mo - p_mercado if hay_mercado else np.nan,
            "edge under": mu_ - (1 - p_mercado - empate) if hay_mercado else np.nan,
            "edge modelo over": po - p_mercado if hay_mercado else np.nan,
            "VE over": odds.valor_esperado(mo, p.over_odds) if apostable and hay_mercado and pd.notna(p.over_odds) else np.nan,
            "VE under": odds.valor_esperado(mu_, p.under_odds) if apostable and hay_mercado and pd.notna(p.under_odds) else np.nan,
            "partidos": r.sample_games, "estado de datos": "completo" if r.sample_games >= 20 else "parcial",
            "riesgos": r.notes,
        })
    tabla = pd.DataFrame(filas)
    if "VE over" in tabla:
        tabla["mejor VE"] = tabla[["VE over", "VE under"]].max(axis=1)
        tabla["mejor edge"] = tabla[["edge over", "edge under"]].max(axis=1)
        tabla = tabla.sort_values(["mejor VE", "mejor edge"], ascending=False, na_position="last")
    return tabla


def marcar_principales(lineas: list[dict]) -> list[dict]:
    """Pone `principal` en cada fila: de las líneas de un jugador, mercado y casa (Stake trae alternas), la más
    pareja según el mercado sin margen, que es la que la casa muestra por defecto."""
    grupos = {}
    for f in lineas:
        grupos.setdefault((f.get("player_id") or f["jugador"], f["mercado"], f["casa"]), []).append(f)
    for grupo in grupos.values():
        # Sin precio de los dos lados no se sabe si es pareja: queda al final.
        pareja = min(grupo, key=lambda f: abs(f["P mercado over (sin margen)"] - 0.5)
                     if f.get("P mercado over (sin margen)") is not None else float("inf"))
        for f in grupo:
            f["principal"] = f is pareja
    return lineas


def hay_precio(tabla: pd.DataFrame) -> bool:
    return bool(tabla.get("VE over", pd.Series(dtype=float)).notna().any()
                or tabla.get("VE under", pd.Series(dtype=float)).notna().any())
