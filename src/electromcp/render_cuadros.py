"""Lámina de cuadros de carga y diagramas unifilares.

Por cada tablero: el cuadro de cargas (circuito, descripción, salidas, carga por fase, corriente,
protección, conductor, tubo, longitud y regulación), el cálculo de demanda con la protección
general y el alimentador, y a la derecha el diagrama unifilar (medidor, protección general, barraje,
un ramal por circuito, barra de neutro y de tierra, DPS). Se reparten en tantos pliegos como haga falta.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .diseno.cuadro import CuadroCargas, cuadros_del_proyecto
from .model import Proyecto


def _n(x: float, d: int = 0) -> str:
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


COLUMNAS = [  # (título, ancho mm, clave, formato)
    ("CTO", 13, "circuito", None),
    ("DESCRIPCIÓN", 70, "descripcion", None),
    ("LUM", 10, "luminarias", "i"),
    ("TOM", 10, "tomas", "i"),
    ("ESP", 10, "especiales", "i"),
    ("CARGA VA", 18, "va", "0"),
    ("FASE A", 16, "fase_a_va", "0"),
    ("FASE B", 16, "fase_b_va", "0"),
    ("I (A)", 13, "corriente_a", "1"),
    ("PROT.", 16, "prot", None),
    ("CONDUCTORES", 40, "conductor", None),
    ("TUBO", 18, "tubo", None),
    ("L (m)", 12, "longitud_m", "1"),
    ("ΔV %", 12, "regulacion_pct", "2"),
]
FILA_MM = 5.0
TXT_MM = 2.0
ANCHO_TABLA = sum(c[1] for c in COLUMNAS)
ANCHO_UNIFILAR = 150.0


@dataclass
class Bloque:
    cuadro: CuadroCargas
    titulo: str

    @property
    def alto_mm(self) -> float:
        filas = len(self.cuadro.filas) + 3  # encabezado, totales, reserva
        unif = 40 + 9 * len(self.cuadro.filas)
        tabla = 10 + FILA_MM * filas + 8 + 4.2 * (len(self.cuadro.demanda) + 4)
        return max(tabla, unif) + 12


@dataclass
class Hoja:
    bloques: list[tuple[Bloque, float, float]] = field(default_factory=list)  # (bloque, x_mm, y_mm sup)

    def dibujar(self, r, origen) -> None:
        pl = r.pl
        ox, oy = origen
        for b, x, y in self.bloques:
            _dibujar_bloque(r.b, pl, b, ox + pl.mm(x), oy + pl.mm(y))


def paginar(p: Proyecto, pl) -> list[Hoja]:
    cuadros = cuadros_del_proyecto(p)
    bloques = []
    for tid, cq in cuadros.items():
        t = next(t for t in p.tableros if t.id == tid)
        bloques.append(Bloque(cq, f"{tid}  ·  {t.nombre.upper()}"))
    hojas: list[Hoja] = []
    margen, alto_util = 20.0, pl.alto_mm - 20.0
    ancho_bloque = ANCHO_TABLA + ANCHO_UNIFILAR + 10
    cols = max(1, int((pl.ancho_mm - 2 * margen) // ancho_bloque))
    hoja, col, y = Hoja(), 0, alto_util
    for b in bloques:
        # la última columna deja libre el rótulo (150 mm de alto abajo a la derecha)
        piso = margen + (160.0 if col == cols - 1 else 0.0)
        if y - b.alto_mm < piso:
            col += 1
            y = alto_util
            if col >= cols:
                hojas.append(hoja)
                hoja, col = Hoja(), 0
            piso = margen + (160.0 if col == cols - 1 else 0.0)
        hoja.bloques.append((b, margen + col * ancho_bloque, y))
        y -= b.alto_mm
    if hoja.bloques:
        hojas.append(hoja)
    return hojas


def _dibujar_bloque(be, pl, b: Bloque, x0: float, y0: float) -> None:
    m = pl.mm
    cq = b.cuadro
    capa = "ANOT-TEXTOS"
    h = m(TXT_MM)
    be.relleno_solido([(x0, y0), (x0 + m(3), y0), (x0 + m(3), y0 - m(7)), (x0, y0 - m(7))], capa, color=2)
    be.texto(f"CUADRO DE CARGAS  {b.titulo}", (x0 + m(6), y0 - m(3.5)), m(4), capa)
    be.texto(cq.sistema.upper(), (x0 + m(ANCHO_TABLA), y0 - m(3.5)), m(2.4), capa, color=8)
    y = y0 - m(10)
    fila = m(FILA_MM)
    filas = cq.filas
    n_filas = len(filas) + 3
    # cuadrícula
    be.polilinea([(x0, y), (x0 + m(ANCHO_TABLA), y), (x0 + m(ANCHO_TABLA), y - fila * n_filas),
                  (x0, y - fila * n_filas)], capa, True)
    xs = [x0]
    for _, w, _, _ in COLUMNAS:
        xs.append(xs[-1] + m(w))
    for xv in xs[1:-1]:
        be.linea((xv, y), (xv, y - fila * n_filas), capa)
    for k in range(1, n_filas):
        be.linea((x0, y - fila * k), (x0 + m(ANCHO_TABLA), y - fila * k), capa)
    be.relleno_solido([(x0, y), (x0 + m(ANCHO_TABLA), y), (x0 + m(ANCHO_TABLA), y - fila), (x0, y - fila)],
                      capa, color=254)
    for (tit, w, _, _), xa in zip(COLUMNAS, xs):
        be.texto(tit, (xa + m(w) / 2, y - fila / 2), h * 0.9, capa, centrado=True)

    def celda(k, valores):
        yc = y - fila * (k + 0.5)
        for (tit, w, clave, fmt), xa in zip(COLUMNAS, xs):
            v = valores.get(clave, "")
            if fmt == "i":
                txt = str(v) if v else "-"
            elif fmt and isinstance(v, (int, float)):
                txt = _n(v, int(fmt)) if v else "-"
            else:
                txt = str(v)
            if clave == "descripcion":
                txt = txt[:46]
                be.texto(txt, (xa + m(1.5), yc), h, capa)
            else:
                be.texto(txt, (xa + m(w) / 2, yc), h, capa, centrado=True)

    for k, f in enumerate(filas, 1):
        v = dict(f)
        v["prot"] = f"{f['polos']}x{f['proteccion_a']:.0f} A"
        v["conductor"] = f["conductor"].replace("1F+1N ", "F+N ")
        celda(k, v)
    celda(len(filas) + 1, {"circuito": "R", "descripcion": f"Reserva ({max(cq.n_espacios - len(filas), 0)} espacios)",
                           "prot": "-"})
    celda(len(filas) + 2, {"descripcion": "TOTAL CARGA INSTALADA", "va": cq.total_va, "fase_a_va": cq.fase_a_va,
                           "fase_b_va": cq.fase_b_va,
                           "luminarias": sum(f["luminarias"] for f in filas), "tomas": sum(f["tomas"] for f in filas),
                           "especiales": sum(f["especiales"] for f in filas),
                           "corriente_a": max(cq.fase_a_va, cq.fase_b_va) / 120.0,
                           "prot": f"Desb. {_n(cq.desbalance_pct, 1)} %"})
    # demanda
    yd = y - fila * n_filas - m(6)
    be.texto("CÁLCULO DE DEMANDA (NTC 2050 SECCIÓN 220)", (x0, yd), m(2.6), capa)
    yd -= m(4.5)
    for d in cq.demanda:
        be.texto(d["concepto"], (x0 + m(2), yd), h, capa)
        be.texto(f"{_n(d['va'])} VA", (x0 + m(ANCHO_TABLA - 4), yd), h, capa, centrado=True)
        yd -= m(4.2)
    for etq, val in (("DEMANDA TOTAL", f"{_n(cq.demanda_va)} VA  ->  I = {_n(cq.corriente_a, 1)} A a 240 V"),
                     ("PROTECCIÓN GENERAL", f"2x{cq.proteccion_general_a:.0f} A, termomagnético"),
                     ("ALIMENTADOR", cq.alimentador + (f",  L = {_n(cq.longitud_alimentador_m, 1)} m,  "
                                                       f"ΔV = {_n(cq.regulacion_alimentador_pct, 2)} %"
                                                       if cq.longitud_alimentador_m else ""))):
        be.texto(etq + ":", (x0 + m(2), yd), h, capa)
        be.texto(val, (x0 + m(42), yd), h, capa)
        yd -= m(4.2)
    _unifilar(be, pl, cq, x0 + m(ANCHO_TABLA + 10), y0 - m(10))


def _unifilar(be, pl, cq: CuadroCargas, x0: float, y0: float) -> None:
    """Diagrama unifilar: medidor -> protección general -> barraje -> ramales."""
    m = pl.mm
    capa = "E-TABLEROS"
    capa_t = "ANOT-TEXTOS"
    h = m(TXT_MM)
    xb = x0 + m(45)  # barraje vertical
    # acometida y medidor
    yc = y0 - m(4)
    be.texto("DIAGRAMA UNIFILAR", (x0, yc), m(2.6), capa_t)
    ym = y0 - m(14)
    be.polilinea([(x0 + m(4), ym - m(4)), (x0 + m(16), ym - m(4)), (x0 + m(16), ym + m(4)), (x0 + m(4), ym + m(4))],
                 capa, True)
    be.texto("kWh", (x0 + m(10), ym), h, capa_t, centrado=True)
    be.texto("Desde red / medidor", (x0, ym + m(7)), h * 0.9, capa_t, color=8)
    # protección general
    be.linea((x0 + m(16), ym), (x0 + m(24), ym), capa)
    _breaker(be, pl, (x0 + m(24), ym), m(8), capa)
    be.texto(f"2x{cq.proteccion_general_a:.0f} A", (x0 + m(28), ym + m(4)), h, capa_t, centrado=True)
    be.linea((x0 + m(32), ym), (xb, ym), capa)
    be.texto(f"#{cq.calibre_alimentador} AWG", (x0 + m(38), ym - m(3)), h * 0.85, capa_t, centrado=True)
    # barraje
    n = len(cq.filas)
    y_fin = ym - m(8) - m(9) * max(n - 1, 0)
    be.polilinea([(xb, ym), (xb, y_fin)], capa, ancho=m(0.8))
    for k, f in enumerate(cq.filas):
        y = ym - m(8) - m(9) * k if k else ym - m(8) + m(0)
        y = ym - m(8) - m(9) * k
        be.linea((xb, y), (xb + m(8), y), capa)
        _breaker(be, pl, (xb + m(8), y), m(8), capa)
        be.linea((xb + m(16), y), (xb + m(30), y), capa)
        be.circulo((xb + m(31), y), m(1), capa)
        be.texto(f"{f['polos']}x{f['proteccion_a']:.0f} A", (xb + m(12), y + m(3.2)), h * 0.85, capa_t, centrado=True)
        be.texto(f"{f['circuito']} {f['fase']}", (xb + m(34), y + m(1.2)), h, capa_t)
        be.texto(f"#{f['calibre_awg']} · {_n(f['va'])} VA", (xb + m(34), y - m(2.2)), h * 0.85, capa_t, color=8)
    # puesta a tierra y DPS
    yt = y_fin - m(10)
    be.linea((x0 + m(10), ym - m(4)), (x0 + m(10), yt), capa)
    for k, w in enumerate((6, 4, 2)):
        be.linea((x0 + m(10) - m(w) / 2, yt - m(1.2) * k), (x0 + m(10) + m(w) / 2, yt - m(1.2) * k), capa)
    be.texto("SPT (RETIE)", (x0 + m(14), yt), h * 0.85, capa_t)
    be.polilinea([(x0 + m(20), ym - m(14)), (x0 + m(28), ym - m(14)), (x0 + m(28), ym - m(8)), (x0 + m(20), ym - m(8))],
                 capa, True)
    be.texto("DPS", (x0 + m(24), ym - m(11)), h * 0.85, capa_t, centrado=True)
    be.linea((x0 + m(24), ym - m(8)), (x0 + m(24), ym - m(0.5)), capa)


def _breaker(be, pl, p0, largo, capa) -> None:
    """Interruptor termomagnético: arco sobre el tramo."""
    import math

    x, y = p0
    pts = [(x + largo / 2 - largo / 2 * math.cos(math.pi * i / 10), y + largo * 0.35 * math.sin(math.pi * i / 10))
           for i in range(11)]
    be.polilinea(pts, capa)
    be.circulo((x, y), pl.mm(0.6), capa)
    be.circulo((x + largo, y), pl.mm(0.6), capa)
