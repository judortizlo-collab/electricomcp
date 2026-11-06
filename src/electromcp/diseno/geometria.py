"""Geometría de apoyo para el diseño: muros, tramos de pared útiles y orientación de salidas."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from ..model import Proyecto, Recinto, Vano

P = tuple[float, float]


def rotacion_frente(nx: float, ny: float) -> float:
    """Rotación del símbolo (grados) para que su frente mire hacia (nx, ny). 0° = frente hacia +Y."""
    return round((math.degrees(math.atan2(ny, nx)) - 90.0) % 360.0, 2)


def dist(a: P, b: P) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


@dataclass
class Contexto:
    """Geometría de un nivel, calculada una sola vez."""

    nivel: str
    solido: BaseGeometry  # muros + columnas
    recintos: dict[str, Recinto]
    poligonos: dict[str, Polygon]
    puertas: list[Vano]
    ventanas: list[Vano]

    @classmethod
    def de_proyecto(cls, p: Proyecto, nivel: str) -> "Contexto":
        anillos = [Polygon(a.puntos) for a in p.arquitectura
                   if a.nivel == nivel and a.cerrado and a.capa in ("ARQ-MUROS", "ARQ-ESTRUCTURA") and len(a.puntos) >= 3]
        # Un muro con huecos se guarda como varios anillos: la regla par-impar (XOR) lo reconstruye.
        solido: BaseGeometry = Polygon()
        for pg in anillos:
            pg = pg.buffer(0) if not pg.is_valid else pg
            solido = solido.symmetric_difference(pg)
        recs = {r.id: r for r in p.recintos if r.nivel == nivel}
        pols = {}
        for r in recs.values():
            pg = Polygon(r.contorno)
            pols[r.id] = pg if pg.is_valid else pg.buffer(0)
        if solido.is_empty and pols:
            # sin arquitectura importada: los muros son una franja alrededor de cada recinto
            solido = unary_union([pg.buffer(0.15, join_style="mitre").difference(pg) for pg in pols.values()])
        vanos = [v for v in p.vanos if v.nivel == nivel]
        return cls(nivel, solido, recs, pols, [v for v in vanos if v.tipo == "puerta"],
                   [v for v in vanos if v.tipo == "ventana"])

    def puertas_de(self, rid: str) -> list[Vano]:
        return [v for v in self.puertas if rid in v.recintos]


@dataclass
class Tramo:
    """Tramo continuo de pared utilizable (sin puertas) a lo largo del perímetro de un recinto."""

    anillo: LineString  # perímetro antihorario (cerrado)
    s0: float
    s1: float  # puede superar la longitud del anillo (tramo que da la vuelta)
    vertices_s: list[float] = field(default_factory=list)

    @property
    def longitud(self) -> float:
        return self.s1 - self.s0

    def punto(self, s: float) -> P:
        q = self.anillo.interpolate(s % self.anillo.length)
        return (q.x, q.y)

    def normal(self, s: float) -> P:
        """Normal hacia el interior del recinto (el anillo es antihorario: interior a la izquierda)."""
        L = self.anillo.length
        a = self.anillo.interpolate((s - 0.02) % L)
        b = self.anillo.interpolate((s + 0.02) % L)
        dx, dy = b.x - a.x, b.y - a.y
        n = math.hypot(dx, dy) or 1.0
        return (-dy / n, dx / n)

    def dist_esquina(self, s: float) -> float:
        L = self.anillo.length
        if not self.vertices_s:
            return 99.0
        return min(min(abs(s % L - v), L - abs(s % L - v)) for v in self.vertices_s)


def anillo_ccw(pg: Polygon) -> LineString:
    pg = pg.simplify(0.01)
    coords = list(pg.exterior.coords)
    if not pg.exterior.is_ccw:
        coords = coords[::-1]
    return LineString(coords)


def tramos_de_pared(ctx: Contexto, rid: str, paso: float = 0.05, excluir: Optional[list[BaseGeometry]] = None,
                    holgura_puerta: float = 0.10) -> list[Tramo]:
    """Divide el perímetro del recinto en tramos de pared continuos.

    Se interrumpe en puertas (210.52(A)(2): la pared se mide sin interrupciones por puertas) y en
    bordes sin muro (aberturas a otro espacio). Las ventanas y las columnas sí cuentan como pared.
    `excluir`: geometrías cuyo frente no lleva tomas generales (p. ej. el mesón de la cocina).
    """
    pg = ctx.poligonos[rid]
    anillo = anillo_ccw(pg)
    L = anillo.length
    n = max(int(L / paso), 8)
    solido = ctx.solido.buffer(0.03) if not ctx.solido.is_empty else ctx.solido
    puertas = [LineString([v.p1, v.p2]) for v in ctx.puertas
               if Polygon(pg.exterior).buffer(0.4).intersects(LineString([v.p1, v.p2]))]
    ventanas = [LineString([v.p1, v.p2]) for v in ctx.ventanas]
    tmp = Tramo(anillo, 0, L)
    ok = []
    for i in range(n):
        s = i * L / n
        x, y = tmp.punto(s)
        nx, ny = tmp.normal(s)
        afuera = Point(x - nx * 0.08, y - ny * 0.08)
        pt = Point(x, y)
        es_muro = (not solido.is_empty and solido.contains(afuera)) or any(w.distance(pt) < 0.20 for w in ventanas)
        en_puerta = any(d.distance(pt) < 0.22 and _proyecta_en(d, pt, holgura_puerta) for d in puertas)
        excluido = bool(excluir) and any(g.distance(pt) < 0.05 for g in excluir)
        ok.append(es_muro and not en_puerta and not excluido)
    # vértices del anillo (para alejar las tomas de las esquinas)
    vs = []
    acc = 0.0
    cs = list(anillo.coords)
    for a, b in zip(cs, cs[1:]):
        vs.append(acc)
        acc += dist(a, b)
    if all(ok):
        return [Tramo(anillo, 0.0, L, vs)]
    # rotar para empezar en una muestra excluida y armar intervalos sin vuelta
    k0 = ok.index(False)
    tramos = []
    i = 0
    while i < n:
        j = (k0 + i) % n
        if ok[j]:
            ini = k0 + i
            while i < n and ok[(k0 + i) % n]:
                i += 1
            fin = k0 + i
            s0, s1 = ini * L / n, fin * L / n
            if s1 - s0 >= paso * 1.5:
                tramos.append(Tramo(anillo, s0, s1, vs))
        else:
            i += 1
    return tramos


def _proyecta_en(seg: LineString, pt: Point, holgura: float) -> bool:
    s = seg.project(pt)
    return -holgura <= s <= seg.length + holgura


def punto_en_pared(ctx: Contexto, rid: str, objetivo: P, evitar: Optional[list[tuple[P, float]]] = None,
                   tramos: Optional[list[Tramo]] = None) -> Optional[tuple[P, P, float]]:
    """Punto de pared útil más cercano a `objetivo`, lejos de los puntos de `evitar` [(punto, radio)].

    Devuelve (punto_sobre_pared, normal_interior, s) o None.
    """
    tramos = tramos if tramos is not None else tramos_de_pared(ctx, rid)
    mejor = None
    for t in tramos:
        s = t.s0 + 0.15
        while s <= t.s1 - 0.15:
            q = t.punto(s)
            if not evitar or all(dist(q, c) >= r for c, r in evitar):
                d = dist(q, objetivo) + (0.3 if t.dist_esquina(s) < 0.25 else 0.0)
                if mejor is None or d < mejor[0]:
                    mejor = (d, q, t.normal(s), s)
            s += 0.05
    if mejor is None:
        return None
    return mejor[1], mejor[2], mejor[3]


def adentro(pg: Polygon, q: P, retiro: float = 0.25) -> P:
    """Lleva q al interior de pg (al menos `retiro` del borde) si quedó afuera."""
    nucleo = pg.buffer(-retiro)
    if nucleo.is_empty:
        nucleo = pg.buffer(-retiro / 3)
        if nucleo.is_empty:
            c = pg.representative_point()
            return (c.x, c.y)
    pt = Point(q)
    if nucleo.contains(pt):
        return q
    a, _ = nearest_points(nucleo, pt)
    return (a.x, a.y)


def rect_orientado(pg: Polygon) -> tuple[P, P, P, float, float]:
    """Rectángulo mínimo: (origen, eje_u, eje_v, largo_u, largo_v) con u el lado largo."""
    r = pg.minimum_rotated_rectangle
    cs = list(r.exterior.coords)[:4]
    e1 = (cs[1][0] - cs[0][0], cs[1][1] - cs[0][1])
    e2 = (cs[3][0] - cs[0][0], cs[3][1] - cs[0][1])
    l1, l2 = math.hypot(*e1) or 1e-9, math.hypot(*e2) or 1e-9
    if l1 >= l2:
        return cs[0], (e1[0] / l1, e1[1] / l1), (e2[0] / l2, e2[1] / l2), l1, l2
    return cs[0], (e2[0] / l2, e2[1] / l2), (e1[0] / l1, e1[1] / l1), l2, l1
