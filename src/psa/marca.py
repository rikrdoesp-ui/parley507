"""Logo de Parley507: el boleto de un parley con el 507 escrito como en un marcador de estadio.

El 507 va en dígitos de segmentos (no en texto) para que se vea igual en la cabecera, en el ícono de la pestaña
(que no carga fuentes web) y en los PNG. Colores de la bandera de Panamá: 5 azul, 0 azul noche, 7 rojo; el blanco
es el boleto. La geometría vive solo aquí; la usan la cabecera (con colores del tema), el ícono de la pestaña y los
PNG para la pantalla de inicio (tools/iconos.py).
"""

TAMANO = 64  # Lado del lienzo; todas las coordenadas están en esta escala.
COLORES = {"fondo": "#16202C", "boleto": "#EDF0F3", "corte": "#16202C", "ganado": "#3DBB8C",
           "azul": "#0B3D91", "noche": "#16202C", "rojo": "#D21034"}

# Boleto: cuerpo, muescas laterales (círculos del color del fondo) y línea de corte antes del talón.
BOLETO = {"x": 7, "y": 15, "w": 50, "h": 34, "r": 3.5}
MUESCA = 4.2
CORTE_X = 45.5

# Siete segmentos: a arriba, b arriba-derecha, c abajo-derecha, d abajo, e abajo-izquierda, f arriba-izquierda, g medio.
SEGMENTOS = {"5": "afgcd", "0": "abcdef", "7": "abc"}
DIGITO = {"w": 7, "h": 21, "t": 2.5, "separacion": 2.5, "inclinacion": 0.16}


def _segmentos(caracter: str, x: float, y: float) -> list[list[tuple[float, float]]]:
    """Polígonos inclinados (cursiva) de un dígito con esquina superior izquierda en (x, y)."""
    w, h, t, k = DIGITO["w"], DIGITO["h"], DIGITO["t"], DIGITO["inclinacion"]
    medio = h / 2
    cajas = {"a": (x, y, w, t), "d": (x, y + h - t, w, t), "g": (x, y + medio - t / 2, w, t),
             "f": (x, y, t, medio + t / 2), "b": (x + w - t, y, t, medio + t / 2),
             "e": (x, y + medio - t / 2, t, medio + t / 2), "c": (x + w - t, y + medio - t / 2, t, medio + t / 2)}
    centro = y + medio

    def inclinar(px, py):
        return px + (centro - py) * k, py

    return [[inclinar(cx, cy), inclinar(cx + cw, cy), inclinar(cx + cw, cy + ch), inclinar(cx, cy + ch)]
            for cx, cy, cw, ch in (cajas[s] for s in SEGMENTOS[caracter])]


def _piezas() -> list:
    b = BOLETO
    piezas = [
        ("rect", {"x": 0, "y": 0, "w": 64, "h": 64, "r": 14}, "fondo"),
        ("rect", {"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"], "r": b["r"]}, "boleto"),
        ("circulo", {"cx": b["x"], "cy": b["y"] + b["h"] / 2, "r": MUESCA}, "fondo"),
        ("circulo", {"cx": b["x"] + b["w"], "cy": b["y"] + b["h"] / 2, "r": MUESCA}, "fondo"),
    ]
    y = b["y"] + 4.5
    while y < b["y"] + b["h"] - 4:  # Línea de corte punteada.
        piezas.append(("rect", {"x": CORTE_X - 0.7, "y": y, "w": 1.4, "h": 2.4, "r": 0.5}, "corte"))
        y += 4.2
    talon = (CORTE_X + b["x"] + b["w"] - MUESCA) / 2  # Centro del talón, entre el corte y la muesca derecha.
    piezas.append(("circulo", {"cx": talon, "cy": b["y"] + b["h"] / 2, "r": 2.6}, "ganado"))
    ancho = 3 * DIGITO["w"] + 2 * DIGITO["separacion"]
    x = b["x"] + MUESCA + (CORTE_X - 2 - b["x"] - MUESCA - ancho) / 2
    yd = b["y"] + (b["h"] - DIGITO["h"]) / 2
    for caracter, color in zip("507", ("azul", "noche", "rojo")):
        piezas += [("poligono", {"puntos": p}, color) for p in _segmentos(caracter, x, yd)]
        x += DIGITO["w"] + DIGITO["separacion"]
    return piezas


PIEZAS = _piezas()


def svg(colores: dict | None = None, titulo: str = "Parley507") -> str:
    """SVG del logo. `colores` puede traer valores CSS (por ejemplo var(--logo-fondo)) para seguir el tema."""
    c = {**COLORES, **(colores or {})}
    partes = []
    for tipo, p, color in PIEZAS:
        if tipo == "rect":
            partes.append(f'<rect x="{p["x"]:.2f}" y="{p["y"]:.2f}" width="{p["w"]:.2f}" height="{p["h"]:.2f}" '
                          f'rx="{p["r"]}" fill="{c[color]}"/>')
        elif tipo == "circulo":
            partes.append(f'<circle cx="{p["cx"]:.2f}" cy="{p["cy"]:.2f}" r="{p["r"]}" fill="{c[color]}"/>')
        elif tipo == "poligono":
            puntos = " ".join(f"{x:.2f},{y:.2f}" for x, y in p["puntos"])
            partes.append(f'<polygon points="{puntos}" fill="{c[color]}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {TAMANO} {TAMANO}" role="img" aria-label="{titulo}">'
            f'<title>{titulo}</title>{"".join(partes)}</svg>')
