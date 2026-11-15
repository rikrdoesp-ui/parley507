"""Evaluación de líneas de props contra las proyecciones. Lo usan la app y la página para el celular."""
import numpy as np
import pandas as pd

from .. import odds
from . import modelo


def es_consenso(casa: str) -> bool:
    return str(casa).startswith("Consenso")


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
        dos_lados = pd.notna(p.over_odds) and pd.notna(p.under_odds)
        p_mercado = odds.sin_margen(p.over_odds, p.under_odds) if dos_lados else np.nan
        # El consenso de BettingPros ya viene sin margen: su "cuota" no es un precio apostable, no tiene VE.
        apostable = not es_consenso(p.bookmaker)
        filas.append({
            **base, "equipo": r.equipo, "media": r.projected_mean,
            "rango 10-90": f"{r.lower_interval:.0f}-{r.upper_interval:.0f}", "minutos": r.minutes,
            "P over": po, "P under": pu, "cuota justa over": odds.cuota_justa(po), "cuota justa under": odds.cuota_justa(pu),
            "cuota over": p.over_odds, "cuota under": p.under_odds, "P mercado over (sin margen)": p_mercado,
            "edge over": po - p_mercado if dos_lados else np.nan,
            "edge under": pu - (1 - p_mercado) if dos_lados else np.nan,
            "VE over": odds.valor_esperado(po, p.over_odds) if apostable and pd.notna(p.over_odds) else np.nan,
            "VE under": odds.valor_esperado(pu, p.under_odds) if apostable and pd.notna(p.under_odds) else np.nan,
            "partidos": r.sample_games, "estado de datos": "completo" if r.sample_games >= 20 else "parcial",
            "riesgos": r.notes,
        })
    tabla = pd.DataFrame(filas)
    if "VE over" in tabla:
        tabla["mejor VE"] = tabla[["VE over", "VE under"]].max(axis=1)
        tabla["mejor edge"] = tabla[["edge over", "edge under"]].max(axis=1)
        tabla = tabla.sort_values(["mejor VE", "mejor edge"], ascending=False, na_position="last")
    return tabla


def hay_precio(tabla: pd.DataFrame) -> bool:
    return bool(tabla.get("VE over", pd.Series(dtype=float)).notna().any()
                or tabla.get("VE under", pd.Series(dtype=float)).notna().any())
