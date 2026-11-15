"""Logo de Parley507: la trayectoria de un tiro en puntos, el balón, y la barra de probabilidad debajo.

La barra es la misma de cada prop en la página (relleno verde y una marca fina donde está el mercado), así que el
símbolo dice lo que hace la app: medir qué tan probable es un tiro. La geometría vive solo aquí; la usan la
cabecera (con colores del tema), el ícono de la pestaña y los PNG para la pantalla de inicio (tools/iconos.py).
"""

import math

TAMANO = 64  # Lado del lienzo; todas las coordenadas están en esta escala.
COLORES = {"fondo": "#16202C", "arco": "#FFFFFF", "balon": "#E3A008", "costura": "#16202C",
           "pista": "#3A4757", "relleno": "#3DBB8C", "mercado": "#FFFFFF"}


def _trayectoria(n: int = 5) -> list[tuple[float, float]]:
    """Puntos de la parábola del tiro (Bézier cuadrática), como en un mapa de tiro; el balón va al final."""
    (x0, y0), (x1, y1), (x2, y2) = (13, 45), (27, 2), (44, 25)
    salida = []
    for i in range(n):
        t = i * 0.19  # Hasta 0.76: el último punto queda justo antes del balón.
        salida.append(((1 - t) ** 2 * x0 + 2 * (1 - t) * t * x1 + t ** 2 * x2,
                       (1 - t) ** 2 * y0 + 2 * (1 - t) * t * y1 + t ** 2 * y2))
    return salida


BALON = (44, 25, 7.5)  # Centro y radio.
_bx, _by, _br = BALON
# Piezas: (tipo, parámetros, color). Ángulos en grados, horarios desde las 3 (igual en SVG y en Pillow).
PIEZAS = [
    ("rect", {"x": 0, "y": 0, "w": 64, "h": 64, "r": 14}, "fondo"),
    *[("circulo", {"cx": x, "cy": y, "r": 2.3}, "arco") for x, y in _trayectoria()],
    ("circulo", {"cx": _bx, "cy": _by, "r": _br}, "balon"),
    ("linea", {"x1": _bx, "y1": _by - _br, "x2": _bx, "y2": _by + _br, "grosor": 1.4}, "costura"),
    ("linea", {"x1": _bx - _br, "y1": _by, "x2": _bx + _br, "y2": _by, "grosor": 1.4}, "costura"),
    ("curva", {"cx": _bx - 1.35 * _br, "cy": _by, "r": _br, "inicio": -42, "fin": 42, "grosor": 1.4}, "costura"),
    ("curva", {"cx": _bx + 1.35 * _br, "cy": _by, "r": _br, "inicio": 138, "fin": 222, "grosor": 1.4}, "costura"),
    ("rect", {"x": 13, "y": 48, "w": 38, "h": 5.5, "r": 2.75}, "pista"),
    ("rect", {"x": 13, "y": 48, "w": 27, "h": 5.5, "r": 2.75}, "relleno"),
    ("rect", {"x": 34.8, "y": 44.8, "w": 2.6, "h": 12, "r": 1.3}, "mercado"),
]


def svg(colores: dict | None = None, titulo: str = "Parley507") -> str:
    """SVG del logo. `colores` puede traer valores CSS (por ejemplo var(--logo-fondo)) para seguir el tema."""
    c = {**COLORES, **(colores or {})}
    partes = []
    for tipo, p, color in PIEZAS:
        if tipo == "rect":
            partes.append(f'<rect x="{p["x"]}" y="{p["y"]}" width="{p["w"]}" height="{p["h"]}" rx="{p["r"]}" fill="{c[color]}"/>')
        elif tipo == "curva":
            a, b = math.radians(p["inicio"]), math.radians(p["fin"])
            xa, ya = p["cx"] + p["r"] * math.cos(a), p["cy"] + p["r"] * math.sin(a)
            xb, yb = p["cx"] + p["r"] * math.cos(b), p["cy"] + p["r"] * math.sin(b)
            partes.append(f'<path d="M{xa:.2f} {ya:.2f} A{p["r"]} {p["r"]} 0 0 1 {xb:.2f} {yb:.2f}" fill="none" '
                          f'stroke="{c[color]}" stroke-width="{p["grosor"]}" stroke-linecap="round"/>')
        elif tipo == "circulo":
            partes.append(f'<circle cx="{p["cx"]}" cy="{p["cy"]}" r="{p["r"]}" fill="{c[color]}"/>')
        elif tipo == "linea":
            partes.append(f'<line x1="{p["x1"]}" y1="{p["y1"]}" x2="{p["x2"]}" y2="{p["y2"]}" stroke="{c[color]}" '
                          f'stroke-width="{p["grosor"]}" stroke-linecap="round"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {TAMANO} {TAMANO}" role="img" aria-label="{titulo}">'
            f'<title>{titulo}</title>{"".join(partes)}</svg>')
