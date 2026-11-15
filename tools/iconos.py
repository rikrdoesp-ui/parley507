"""Genera los íconos del logo (SVG y PNG) en la raíz del repositorio, para la pestaña y la pantalla de inicio.

Uso (solo cuando cambia el logo):  uv run --with pillow python tools/iconos.py
Dibuja la misma geometría de src/psa/marca.py; se pinta a 4x y se reduce para suavizar bordes.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from psa import marca  # noqa: E402


def png(lado: int, destino: Path, margen: float = 0.0) -> None:
    """`margen`: fracción de borde libre (íconos 'maskable' de Android necesitan zona segura)."""
    escala = 4
    grande = lado * escala
    img = Image.new("RGBA", (grande, grande), marca.COLORES["fondo"] if margen else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = grande * (1 - 2 * margen) / marca.TAMANO
    o = grande * margen

    def p(x, y):
        return o + x * f, o + y * f

    for tipo, q, color in marca.PIEZAS:
        c = marca.COLORES[color]
        if tipo == "rect":
            radio = 0 if (margen and q["w"] == 64) else q["r"] * f
            d.rounded_rectangle([p(q["x"], q["y"]), p(q["x"] + q["w"], q["y"] + q["h"])], radius=radio, fill=c)
        elif tipo == "curva":
            r = q["r"]
            d.arc([p(q["cx"] - r, q["cy"] - r), p(q["cx"] + r, q["cy"] + r)], start=q["inicio"], end=q["fin"],
                  fill=c, width=max(1, round(q["grosor"] * f)))
        elif tipo == "circulo":
            d.ellipse([p(q["cx"] - q["r"], q["cy"] - q["r"]), p(q["cx"] + q["r"], q["cy"] + q["r"])], fill=c)
        elif tipo == "linea":
            d.line([p(q["x1"], q["y1"]), p(q["x2"], q["y2"])], fill=c, width=max(1, round(q["grosor"] * f)))
    img.resize((lado, lado), Image.LANCZOS).save(destino)


def main() -> None:
    (RAIZ / "icono.svg").write_text(marca.svg(), encoding="utf-8")
    png(180, RAIZ / "icono-180.png", margen=0.0)  # iPhone (apple-touch-icon): iOS redondea las esquinas.
    png(192, RAIZ / "icono-192.png")
    png(512, RAIZ / "icono-512.png")
    png(512, RAIZ / "icono-maskable-512.png", margen=0.1)
    manifiesto = {
        "name": "Parley507", "short_name": "Parley507", "lang": "es", "start_url": "./", "scope": "./",
        "display": "standalone", "background_color": "#EDF0F3", "theme_color": "#16202C",
        "icons": [{"src": "icono-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "icono-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "icono-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
                  {"src": "icono.svg", "sizes": "any", "type": "image/svg+xml"}]}
    (RAIZ / "manifest.webmanifest").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Íconos y manifiesto escritos en", RAIZ)


if __name__ == "__main__":
    main()
