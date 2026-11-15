"""Fórmulas de cuotas, comunes a todos los deportes. Sin regla de apuesta: BET/PASS lo decide /parley."""


def a_decimal(valor) -> float:
    """Acepta cuota decimal (1.85) o americana (-136, +102, EVEN)."""
    texto = str(valor).strip().upper().replace("+", "")
    if texto in ("EVEN", "EV"):
        return 2.0
    numero = float(texto)
    if abs(numero) >= 100:
        return 1 + numero / 100 if numero > 0 else 1 + 100 / abs(numero)
    if numero <= 1:
        raise ValueError(f"Cuota no válida: {valor}")
    return numero


def sin_margen(cuota: float, contraria: float) -> float:
    """Probabilidad justa del primer lado con el método de potencia (mismo método que parley.sin_margen)."""
    if cuota <= 1 or contraria <= 1:
        raise ValueError("Las cuotas deben ser decimales mayores que 1.")
    a, b = 1 / cuota, 1 / contraria
    if a + b <= 1:
        return a / (a + b)
    bajo, alto = 1.0, 2.0
    while a ** alto + b ** alto > 1:
        alto *= 2
    for _ in range(80):
        medio = (bajo + alto) / 2
        if a ** medio + b ** medio > 1:
            bajo = medio
        else:
            alto = medio
    return a ** ((bajo + alto) / 2)


def valor_esperado(p: float, cuota: float) -> float:
    """VE por unidad apostada, sin push."""
    return p * cuota - 1


def cuota_justa(p: float) -> float | None:
    return 1 / p if p > 0 else None
