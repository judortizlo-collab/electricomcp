"""Biblioteca de símbolos según las convenciones de Julián.

Cada símbolo se describe con primitivas geométricas simples (círculos, líneas,
polilíneas rellenas, textos) en metros, centradas en (0, 0) y orientadas con
el "frente" hacia +Y (la cara del muro queda en -Y). Los backends convierten
estas primitivas en bloques de AutoCAD (BLOCK/INSERT), así cada salida del
plano es un bloque real que se puede contar, editar y extraer con DATAEXTRACTION.

Tamaño base pensado para impresión a 1:50 (r = 0.15 m -> 3 mm en papel).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

# ---------------------------------------------------------------- primitivas


@dataclass(frozen=True)
class Circulo:
    centro: tuple[float, float]
    radio: float
    relleno: bool = False


@dataclass(frozen=True)
class Linea:
    p1: tuple[float, float]
    p2: tuple[float, float]


@dataclass(frozen=True)
class Polilinea:
    puntos: tuple[tuple[float, float], ...]
    cerrada: bool = True
    relleno: bool = False


@dataclass(frozen=True)
class Texto:
    texto: str
    posicion: tuple[float, float]
    altura: float = 0.08
    alineacion: Literal["centro", "izquierda"] = "centro"


Primitiva = Union[Circulo, Linea, Polilinea, Texto]


@dataclass(frozen=True)
class Simbolo:
    clave: str
    descripcion: str
    capa: str
    color: int  # ACI (rojo=1, amarillo=2, verde=3, cian=4, azul=5, magenta=6)
    primitivas: tuple[Primitiva, ...]
    altura_montaje: float | None = None  # m sobre NPT
    potencia_va: float | None = None  # carga típica para el cuadro de cargas
    grupo: str = "tomas"
    atributos: tuple[str, ...] = field(default=("CIRCUITO",))


R = 0.15  # radio base


def _semicirculo(r: float, n: int = 12, abajo: bool = True) -> tuple[tuple[float, float], ...]:
    import math

    ini, fin = (math.pi, 2 * math.pi) if abajo else (0.0, math.pi)
    pts = [(r * math.cos(ini + (fin - ini) * i / n), r * math.sin(ini + (fin - ini) * i / n)) for i in range(n + 1)]
    return tuple(pts)


def _toma_base() -> tuple[Primitiva, ...]:
    # Círculo con dos líneas horizontales que sobresalen (convención de toma doble)
    return (
        Circulo((0, 0), R),
        Linea((-R * 1.6, R * 0.35), (R * 1.6, R * 0.35)),
        Linea((-R * 1.6, -R * 0.35), (R * 1.6, -R * 0.35)),
    )


def _triangulo(r: float, relleno: bool = False) -> Polilinea:
    return Polilinea(((0, r), (-r * 0.87, -r * 0.5), (r * 0.87, -r * 0.5)), True, relleno)


SIMBOLOS: dict[str, Simbolo] = {s.clave: s for s in [
    # ------------------------------------------------ tomacorrientes
    Simbolo("TOMA_DOBLE", "Tomacorriente doble 120 V 20 A polo a tierra, h = 0.30 m",
            "E-TOMAS", 1, _toma_base(), 0.30, 180),
    Simbolo("TOMA_GFCI", "Tomacorriente doble GFCI 120 V 20 A (baños, cocina, exterior)",
            "E-TOMAS", 1, _toma_base() + (Polilinea(_semicirculo(R), True, True),
                                           Texto("GFCI", (0, -R * 2.2), 0.07)), 1.10, 180),
    Simbolo("TOMA_220", "Tomacorriente 220 V 20 A con tierra",
            "E-TOMAS-ESPECIALES", 6, _toma_base() + (Texto("220", (0, -R * 2.2), 0.07),), 0.30, 1500),
    Simbolo("SALIDA_ESPECIAL", "Salida especial dedicada (nevera, horno, lavadora, DVR)",
            "E-TOMAS-ESPECIALES", 6, (Circulo((0, 0), R * 1.3), _triangulo(R * 1.05, True)), 0.30, 1200),
    Simbolo("TOMA_AA", "Salida aire acondicionado 220 V (unidad interior)",
            "E-FUERZA", 6, (Polilinea(((-R * 1.5, -R), (R * 1.5, -R), (R * 1.5, R), (-R * 1.5, R))),
                            Texto("AA", (0, 0), 0.12)), 2.20, 1800, "fuerza"),
    Simbolo("CONDENSADORA", "Unidad condensadora AA (cubierta)",
            "E-FUERZA", 6, (Polilinea(((-R * 2, -R * 2), (R * 2, -R * 2), (R * 2, R * 2), (-R * 2, R * 2))),
                            Circulo((0, 0), R * 1.4),
                            Linea((-R, -R), (R, R)), Linea((-R, R), (R, -R))), None, None, "fuerza"),
    Simbolo("GUARDAMOTOR", "Guardamotor (cuarto técnico piscina)",
            "E-FUERZA", 6, (Polilinea(((-R * 1.2, -R * 1.2), (R * 1.2, -R * 1.2), (R * 1.2, R * 1.2), (-R * 1.2, R * 1.2))),
                            Texto("GM", (0, 0), 0.10)), 1.50, None, "fuerza"),
    Simbolo("MOTOR", "Motor (bomba piscina / blower jacuzzi)",
            "E-FUERZA", 6, (Circulo((0, 0), R * 1.6), Texto("M", (0, 0), 0.16)), None, 1100, "fuerza"),
    Simbolo("TRAFO_12V", "Transformador / controlador 12 V iluminación piscina",
            "E-FUERZA", 6, (Circulo((-R * 0.5, 0), R), Circulo((R * 0.5, 0), R)), 0.60, 300, "fuerza"),
    # ------------------------------------------------ comunicaciones
    Simbolo("COM", "Salida de comunicaciones (datos / TV)",
            "COM-SALIDAS", 3, (_triangulo(R), Texto("COM", (0, -R * 2.0), 0.07)), 0.30, None, "com", ()),
    Simbolo("GABINETE_COM", "Gabinete de comunicaciones",
            "COM-SALIDAS", 3, (Polilinea(((-R * 2.4, -R), (R * 2.4, -R), (R * 2.4, R), (-R * 2.4, R))),
                               Linea((-R * 2.4, -R), (R * 2.4, R))), 1.60, None, "com", ()),
    # ------------------------------------------------ tableros y medida
    Simbolo("TABLERO", "Tablero de distribución, h = 1.60 m (borde sup.)",
            "E-TABLEROS", 1, (Polilinea(((-R * 2.6, -R), (R * 2.6, -R), (R * 2.6, R), (-R * 2.6, R))),
                              Polilinea(((-R * 2.6, -R), (R * 2.6, -R), (R * 2.6, R)), True, True)),
            1.60, None, "tableros", ("NOMBRE",)),
    Simbolo("MEDIDOR", "Medidor de energía",
            "E-TABLEROS", 1, (Polilinea(((-R * 1.6, -R * 1.6), (R * 1.6, -R * 1.6), (R * 1.6, R * 1.6), (-R * 1.6, R * 1.6))),
                              Texto("kWh", (0, 0), 0.10)), 1.60, None, "tableros", ()),
    # ------------------------------------------------ iluminación (planos de referencia)
    *[Simbolo(f"BALA_LED_{w}W", f"Bala LED de incrustar {w} W", "E-ILUMINACION", 3,
              (Circulo((0, 0), R * (0.8 + w / 40)), Linea((-R * 0.6, 0), (R * 0.6, 0)), Linea((0, -R * 0.6), (0, R * 0.6))),
              None, float(w), "iluminacion") for w in (3, 5, 9, 12, 18)],
    Simbolo("LUM_COLGANTE", "Salida para luminaria especial colgante", "E-ILUMINACION", 3,
            (Circulo((0, 0), R * 1.2), Circulo((0, 0), R * 0.5, True)), None, 60, "iluminacion"),
    Simbolo("LUM_APLIQUE", "Luminaria aplique de muro", "E-ILUMINACION", 3,
            (Polilinea(_semicirculo(R * 1.2, abajo=False), True, False), Linea((-R * 1.2, 0), (R * 1.2, 0))),
            2.00, 20, "iluminacion"),
    Simbolo("CINTA_LED", "Cinta LED decorativa (por metro)", "E-ILUMINACION", 6,
            (Linea((-R * 3, 0), (R * 3, 0)), Linea((-R * 3, R * 0.3), (R * 3, R * 0.3))), None, 10, "iluminacion"),
    Simbolo("EXTRACTOR", "Salida para extractor de baño (ventilación mecánica)", "E-ILUMINACION", 3,
            (Polilinea(((-R, -R), (R, -R), (R, R), (-R, R))), Linea((-R, -R), (R, R)), Linea((-R, R), (R, -R)),
             Circulo((0, 0), R * 0.45)), None, 40, "iluminacion"),
    Simbolo("SENSOR_MOV", "Sensor de movimiento", "E-INTERRUPTORES", 1,
            (Circulo((0, 0), R), Polilinea(_semicirculo(R * 0.6, abajo=False), False, True)), 2.40, None, "iluminacion"),
    # ------------------------------------------------ interruptores (h = 1.20 m)
    Simbolo("INT_SENCILLO", "Interruptor sencillo", "E-INTERRUPTORES", 7,
            (Circulo((0, 0), R * 0.5, True), Linea((0, 0), (R * 1.4, R * 1.4))), 1.20, None, "iluminacion"),
    Simbolo("INT_DOBLE", "Interruptor doble", "E-INTERRUPTORES", 7,
            (Circulo((0, 0), R * 0.5, True), Linea((0, 0), (R * 1.4, R * 1.4)), Linea((R * 0.7, R * 0.7), (R * 1.2, R * 0.2))),
            1.20, None, "iluminacion"),
    Simbolo("INT_TRIPLE", "Interruptor triple", "E-INTERRUPTORES", 7,
            (Circulo((0, 0), R * 0.5, True), Linea((0, 0), (R * 1.4, R * 1.4)), Linea((R * 0.7, R * 0.7), (R * 1.2, R * 0.2)),
             Linea((R * 1.05, R * 1.05), (R * 1.55, R * 0.55))), 1.20, None, "iluminacion"),
    Simbolo("INT_CONMUTABLE", "Interruptor conmutable sencillo (3 vías)", "E-INTERRUPTORES", 7,
            (Circulo((0, 0), R * 0.5, False), Linea((0, R * 0.5), (R * 1.4, R * 1.9)), Linea((0, -R * 0.5), (-R * 1.4, -R * 1.9))),
            1.20, None, "iluminacion"),
]}


def caja(s: Simbolo) -> tuple[float, float, float, float]:
    """Caja envolvente aproximada (x0, y0, x1, y1) de las primitivas del símbolo."""
    xs: list[float] = []
    ys: list[float] = []
    for p in s.primitivas:
        if isinstance(p, Circulo):
            xs += [p.centro[0] - p.radio, p.centro[0] + p.radio]
            ys += [p.centro[1] - p.radio, p.centro[1] + p.radio]
        elif isinstance(p, Linea):
            xs += [p.p1[0], p.p2[0]]
            ys += [p.p1[1], p.p2[1]]
        elif isinstance(p, Polilinea):
            xs += [q[0] for q in p.puntos]
            ys += [q[1] for q in p.puntos]
        elif isinstance(p, Texto):
            w = 0.6 * p.altura * len(p.texto)
            xs += [p.posicion[0] - w / 2, p.posicion[0] + w / 2]
            ys += [p.posicion[1] - p.altura / 2, p.posicion[1] + p.altura / 2]
    return (min(xs), min(ys), max(xs), max(ys))


def etiquetas(s: Simbolo) -> list[tuple[str, Texto]]:
    """Textos fijos del símbolo. Se guardan como atributos para que se lean siempre
    horizontales aunque el símbolo esté girado (p. ej. 'GFCI' en un muro norte)."""
    return [(f"ETQ{i + 1}", p) for i, p in enumerate(q for q in s.primitivas if isinstance(q, Texto))]


def simbolo(clave: str) -> Simbolo:
    try:
        return SIMBOLOS[clave]
    except KeyError as exc:
        raise KeyError(f"Símbolo desconocido {clave!r}. Disponibles: {sorted(SIMBOLOS)}") from exc
