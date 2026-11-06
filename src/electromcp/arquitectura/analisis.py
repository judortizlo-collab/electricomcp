"""Interpretación del plano: muros, columnas, puertas, ventanas, recintos y unidades.

Flujo:

1. **Muros**: figuras cerradas delgadas de las capas de muro, más las caras delgadas que salen de
   poligonizar su linework (muros dibujados con líneas sueltas), más los achurados sólidos de muro.
2. **Columnas**: figuras cuadradas pequeñas de capas de estructura, pegadas a los muros.
3. **Puertas**: se detectan por el barrido (arco de 60° a 100°, radio 0,45 m a 1,30 m) con la bisagra
   sobre un muro. La hoja cerrada define el vano; con eso se cierra el recinto.
4. **Ventanas**: el linework de ventana cierra el vano del muro.
5. **Recintos**: el espacio libre que queda entre muros, columnas y vanos cerrados. El que toca el
   borde es el exterior.
6. **Nombres y usos**: los textos que caen dentro de cada recinto ("Alcoba 2", "Cocina", "Baño").
7. **Unidades** (apartamentos, locales): recintos unidos por puertas, sin pasar por zonas comunes.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import shapely
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from ..model import UsoRecinto
from .capas import (ESPESOR_MURO_MAX, ESPESOR_MURO_MIN, Categoria, InfoCapa, es_columna, es_muro,
                    espesor_y_largo, normalizar)
from .lectura import Elemento, PlanoLeido

AREA_MIN_RECINTO = 0.25  # m²
HOLGURA = 0.04  # m; rendijas menores a 8 cm entre muros se consideran cerradas


# ---------------------------------------------------------------- resultados
@dataclass
class Puerta:
    bisagra: tuple[float, float]
    extremo: tuple[float, float]  # extremo de la hoja cerrada
    ancho: float
    capa: str
    recintos: list[str] = field(default_factory=list)  # ids a cada lado ("EXT" = exterior)
    tipo: str = "batiente"
    abierta: Optional[tuple[float, float]] = None  # extremo de la hoja abierta (dibujo)
    arco: list[tuple[float, float]] = field(default_factory=list)  # barrido (dibujo)

    @property
    def vano(self) -> LineString:
        return LineString([self.bisagra, self.extremo])


@dataclass
class Ventana:
    poligono: Polygon
    ancho: float
    capa: str
    recintos: list[str] = field(default_factory=list)


@dataclass
class Aparato:
    tipo: str  # inodoro, lavamanos, ducha, lavaplatos, estufa, nevera, lavadora, lavadero, aparato
    centro: tuple[float, float]
    bloque: str
    capa: str
    recinto: Optional[str] = None


@dataclass
class RecintoDetectado:
    id: str
    nombre: str
    uso: UsoRecinto
    poligono: Polygon
    etiquetas: list[str] = field(default_factory=list)
    unidad: Optional[str] = None
    comun: bool = False
    avisos: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)  # ventilacion_mecanica, ruta_evacuacion...
    zonas: list[dict] = field(default_factory=list)  # subzonas de un espacio abierto

    @property
    def area(self) -> float:
        return self.poligono.area

    @property
    def perimetro(self) -> float:
        return self.poligono.exterior.length

    def resumen(self) -> dict:
        c = self.poligono.representative_point()
        return {"id": self.id, "nombre": self.nombre, "uso": self.uso.value, "unidad": self.unidad,
                "area_m2": round(self.area, 2), "perimetro_m": round(self.perimetro, 2),
                "punto_interior": [round(c.x, 3), round(c.y, 3)], "etiquetas": self.etiquetas,
                "zona_comun": self.comun, "notas": self.notas,
                "zonas": [{"nombre": z["nombre"], "uso": z["uso"].value, "area_m2": round(z["poligono"].area, 2)}
                          for z in self.zonas],
                "avisos": self.avisos}


@dataclass
class Interpretacion:
    muros: BaseGeometry
    muros_bajos: BaseGeometry
    columnas: list[Polygon]
    puertas: list[Puerta]
    ventanas: list[Ventana]
    aparatos: list[Aparato]
    recintos: list[RecintoDetectado]
    unidades: dict[str, list[str]]
    exterior: Optional[Polygon]
    escaleras: list[BaseGeometry]
    capas: dict[str, InfoCapa]
    avisos: list[str] = field(default_factory=list)
    vacios: list[Polygon] = field(default_factory=list)
    lineas_vanos: list[BaseGeometry] = field(default_factory=list)  # carpintería de ventanas y puentes
    aparatos_geom: list[BaseGeometry] = field(default_factory=list)
    ejes: list[BaseGeometry] = field(default_factory=list)
    textos_ejes: list[tuple[Point, str, float]] = field(default_factory=list)

    def recinto(self, rid: str) -> RecintoDetectado:
        return next(r for r in self.recintos if r.id == rid)


# ---------------------------------------------------------------- usos
_USOS: list[tuple[UsoRecinto, tuple[str, ...]]] = [
    (UsoRecinto.DUCTO, ("ducto", "ven. mecanica", "ven mecanica", "ventilacion mecanica", "shaft", "buitron",
                        "ducto de ventilacion")),
    (UsoRecinto.ESCALERA, ("escalera", "punto fijo", "sube", "baja", "ascensor")),
    (UsoRecinto.CUARTO_TECNICO, ("cuarto tecnico", "subestacion", "cuarto de bombas", "cuarto util",
                                 "deposito", "basuras", "shut", "tablero", "medidores")),
    (UsoRecinto.ROPAS, ("ropas", "lavanderia", "zona de ropas", "patio de ropas", "labores")),
    (UsoRecinto.PATIO, ("patio", "jardin", "vacio")),
    (UsoRecinto.COCINA, ("cocina", "kitchen", "cocineta")),
    (UsoRecinto.BANO, ("bano", "wc", "aseo", "sanitario", "toilet", "bath")),
    (UsoRecinto.VESTIER, ("vestier", "closet", "walk-in", "walk in")),
    (UsoRecinto.ALCOBA, ("alcoba", "habitacion", "dormitorio", "recamara", "hab.", "bedroom", "cuarto")),
    (UsoRecinto.ESTUDIO, ("estudio", "oficina", "biblioteca", "office")),
    (UsoRecinto.COMEDOR, ("comedor", "dining")),
    (UsoRecinto.SALA, ("sala", "living", "estar")),
    (UsoRecinto.CIRCULACION, ("hall", "circulacion", "pasillo", "corredor", "acceso", "recibidor", "vestibulo",
                              "lobby", "porteria")),
    (UsoRecinto.GARAJE, ("garaje", "garage", "parqueadero", "parqueo")),
    (UsoRecinto.TERRAZA, ("terraza",)),
    (UsoRecinto.BALCON, ("balcon",)),
]
# Notas que aparecen dentro de un recinto pero no son su nombre (se guardan como observación)
_NOTAS = {
    "ventilacion_mecanica": ("ven. mecanica", "ven mecanica", "ventilacion mecanica", "extractor"),
    "ruta_evacuacion": ("ruta de evacuacion", "evacuacion"),
    "detector_incendio": ("deteccion de incendios", "detector de humo", "alarma"),
    "gabinete_incendio": ("gabinete contra", "extintor"),
}
_ORDEN_NOMBRE = [UsoRecinto.SALA, UsoRecinto.COMEDOR, UsoRecinto.ESTUDIO, UsoRecinto.ALCOBA, UsoRecinto.VESTIER,
                 UsoRecinto.COCINA, UsoRecinto.ROPAS, UsoRecinto.BANO, UsoRecinto.PATIO]
_ZONAS_COMUNES = {UsoRecinto.CIRCULACION, UsoRecinto.ESCALERA, UsoRecinto.DUCTO, UsoRecinto.CUARTO_TECNICO}
_RE_UNIDAD = re.compile(r"^(apto|apartamento|apt|unidad|local|oficina|casa|suite)\.?\s*[-#nº°o]*\s*(\w+)$")
_RE_BASURA = re.compile(r"^[#\d.,\s\-+=xX/%²m]*$")  # números, áreas, campos rotos "#####"


def nota_desde_texto(texto: str) -> Optional[str]:
    n = normalizar(texto)
    for clave, frases in _NOTAS.items():
        if any(f in n for f in frases):
            return clave
    return None


def uso_desde_texto(texto: str) -> Optional[UsoRecinto]:
    n = normalizar(texto)
    for uso, claves in _USOS:
        for k in claves:
            if k in ("wc", "sube", "baja", "estar", "hab.", "shut") and not re.search(rf"(^|\W){re.escape(k)}(\W|$)", n):
                continue
            if k in n:
                return uso
    return None


_APARATOS = [
    ("inodoro", ("wc", "inodoro", "sanitario", "toilet", "sanit")),
    ("lavamanos", ("lavamanos", "lavam", "lavabo")),
    ("ducha", ("ducha", "shower", "banera", "tina")),
    ("lavaplatos", ("lavaplatos", "poceta", "sink", "fregadero", "lavap")),
    ("estufa", ("estufa", "cooktop", "horno", "stove", "parrilla")),
    ("nevera", ("nevera", "refrig", "nevecon", "fridge")),
    ("lavadora", ("lavadora", "washer", "secadora")),
    ("lavadero", ("lavadero",)),
    ("calentador", ("calentador", "heater")),
]


def tipo_aparato(nombre_bloque: str) -> str:
    n = normalizar(nombre_bloque)
    for tipo, claves in _APARATOS:
        if any(k in n for k in claves):
            return tipo
    return "aparato"


# ---------------------------------------------------------------- utilidades
def _poligonos(g: BaseGeometry) -> list[Polygon]:
    if g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    if hasattr(g, "geoms"):
        out = []
        for h in g.geoms:
            out += _poligonos(h)
        return out
    return []


def _lineas(g: BaseGeometry) -> list[BaseGeometry]:
    if g.geom_type == "Polygon":
        return [g.exterior] + list(g.interiors)
    if g.geom_type in ("LineString", "LinearRing"):
        return [g]
    return []


def _cerrar(g: BaseGeometry, d: float = 0.01) -> BaseGeometry:
    """Une piezas que se tocan o casi se tocan sin engordarlas."""
    return g.buffer(d, join_style="mitre", mitre_limit=3).buffer(-d, join_style="mitre", mitre_limit=3)


# ---------------------------------------------------------------- muros
def _detectar_muros(els_muro: list[Elemento], info: dict[str, InfoCapa]) -> BaseGeometry:
    delgados: list[Polygon] = []
    lineas: list[BaseGeometry] = []
    for el in els_muro:
        confiable = info[el.capa].origen in ("nombre", "usuario")
        if el.tipo == "HATCH" and not el.relleno_solido and not confiable:
            continue  # achurado con patrón en capa deducida: closets, mesones...
        for g in el.geom:
            if g.geom_type == "Polygon":
                if es_muro(g) or (confiable and espesor_y_largo(g)[0] <= 0.6 and g.area >= 0.005):
                    delgados.append(g)
                elif el.tipo != "HATCH":
                    lineas += _lineas(g)
            elif g.geom_type == "LineString" and g.length > 0.02:
                lineas.append(g)
    caras: list[Polygon] = []
    if lineas:
        red = shapely.set_precision(unary_union(lineas), 0.002)
        dudosas = []
        for cara in polygonize(red):
            if es_muro(cara):
                caras.append(cara)
            elif cara.area <= 0.6 and ESPESOR_MURO_MIN * 0.5 <= espesor_y_largo(cara)[0] <= ESPESOR_MURO_MAX:
                dudosas.append(cara)  # tramos cortos: jambas, remates, encuentros de muros
        # un tramo corto es muro si comparte un borde con un muro ya aceptado
        for _ in range(3):
            if not dudosas or not caras:
                break
            union = unary_union(caras)
            nuevas = [c for c in dudosas if c.boundary.intersection(union.boundary).length > 0.04]
            if not nuevas:
                break
            caras += nuevas
            dudosas = [c for c in dudosas if c not in nuevas]
    todo = unary_union([shapely.set_precision(p, 0.001) for p in delgados + caras])
    return _cerrar(todo, 0.01)


def _detectar_columnas(els: list[Elemento], info: dict[str, InfoCapa], muros: BaseGeometry) -> list[Polygon]:
    cand: list[Polygon] = []
    for el in els:
        confiable = info[el.capa].origen in ("nombre", "usuario")
        for g in el.geom:
            if g.geom_type == "Polygon" and es_columna(g):
                if confiable or muros.is_empty or g.distance(muros) <= 0.10:
                    cand.append(g)
    return [p for p in _poligonos(unary_union(cand)) if p.area >= 0.02]


# ---------------------------------------------------------------- puertas
def _barrido_puerta(el: Elemento) -> bool:
    if el.tipo != "ARC" or el.centro is None or not (0.45 <= el.radio <= 1.30):
        return False
    a0, a1 = el.angulos
    barrido = abs((a1 - a0 + 180) % 360 - 180)
    return 60 <= barrido <= 100


def _hoja_cerrada(c, p1, p2, solido: BaseGeometry) -> Optional[tuple]:
    """Escoge el extremo del arco que corresponde a la hoja cerrada (a lo largo del muro)."""
    puntaje = []
    for p in (p1, p2):
        dx, dy = p[0] - c[0], p[1] - c[1]
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        hits = sum(1 for s in (0.06, 0.12, 0.20, 0.30)
                   if solido.distance(Point(c[0] - ux * s, c[1] - uy * s)) < 0.02)
        puntaje.append(hits)
    if puntaje[0] == puntaje[1] == 0:
        return None
    if puntaje[0] == puntaje[1]:  # desempate: el extremo más cercano a un muro
        return p1 if solido.distance(Point(p1)) <= solido.distance(Point(p2)) else p2
    return p1 if puntaje[0] > puntaje[1] else p2


def _detectar_puertas(elementos: list[Elemento], info: dict[str, InfoCapa], solido: BaseGeometry) -> list[Puerta]:
    excluir = {Categoria.MOBILIARIO, Categoria.APARATOS, Categoria.COTAS, Categoria.TEXTOS, Categoria.EJES,
               Categoria.ACHURADOS, Categoria.IGNORAR, Categoria.ESCALERAS}
    puertas: list[Puerta] = []
    for el in elementos:
        if info[el.capa].categoria in excluir or not _barrido_puerta(el):
            continue
        c = el.centro
        if solido.distance(Point(c)) > 0.12:
            continue
        p = _hoja_cerrada(c, el.extremos[0], el.extremos[1], solido)
        if p is None:
            continue
        otro = el.extremos[1] if p == el.extremos[0] else el.extremos[0]
        nueva = Puerta((round(c[0], 4), round(c[1], 4)), (round(p[0], 4), round(p[1], 4)), round(el.radio, 3),
                       el.capa, abierta=otro, arco=list(el.geom[0].coords))
        # duplicados (el mismo barrido dibujado dos veces, o en dos capas)
        if any(Point(q.bisagra).distance(Point(nueva.bisagra)) < 0.05 and
               Point(q.extremo).distance(Point(nueva.extremo)) < 0.05 for q in puertas):
            continue
        puertas.append(nueva)
    # puertas dobles: dos hojas que se encuentran en el centro
    for q in puertas:
        for r in puertas:
            if q is not r and Point(q.extremo).distance(Point(r.extremo)) < 0.08:
                q.tipo = r.tipo = "doble"
    return puertas


def _cierre_puerta(p: Puerta, espesor: float = 0.30) -> Polygon:
    (x0, y0), (x1, y1) = p.bisagra, p.extremo
    L = math.hypot(x1 - x0, y1 - y0) or 1.0
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    a = (x0 - ux * 0.05, y0 - uy * 0.05)
    b = (x1 + ux * 0.05, y1 + uy * 0.05)
    return LineString([a, b]).buffer(espesor / 2, cap_style="flat")


def _puertas_sin_barrido(els_puerta: list[Elemento], puertas: list[Puerta], solido: BaseGeometry) -> list[Polygon]:
    """Puertas corredizas o vanos dibujados sin arco: rectángulo delgado de la carpintería."""
    por_inst: dict = defaultdict(list)
    for el in els_puerta:
        por_inst[el.instancia if el.instancia is not None else id(el)] += el.geom
    cierres = []
    for geoms in por_inst.values():
        g = unary_union(geoms)
        if g.is_empty:
            continue
        if any(g.distance(Point(p.bisagra)) < 0.15 for p in puertas):
            continue
        r = g.minimum_rotated_rectangle
        if r.geom_type != "Polygon":
            continue
        c = list(r.exterior.coords)
        a, b = LineString(c[0:2]).length, LineString(c[1:3]).length
        lo, hi = sorted((a, b))
        if lo <= 0.35 and 0.5 <= hi <= 3.5 and r.distance(solido) < 0.05:
            cierres.append(r.buffer(0.03))
    return cierres


# ---------------------------------------------------------------- ventanas
def _detectar_ventanas(els: list[Elemento], solido: BaseGeometry) -> list[Ventana]:
    piezas = []
    for el in els:
        for g in el.geom:
            if not solido.is_empty and g.distance(solido) > 0.30:
                continue  # ventana suelta fuera de los muros (leyenda, detalle, basura)
            if g.geom_type in ("LineString", "Polygon"):
                piezas.append((g.buffer(0.04, cap_style="flat") if g.geom_type == "LineString" else g.buffer(0.02),
                               el.capa))
    if not piezas:
        return []
    union = unary_union([p for p, _ in piezas])
    out = []
    for pg in _poligonos(union):
        if pg.area < 0.01:
            continue
        r = pg.minimum_rotated_rectangle
        c = list(r.exterior.coords) if r.geom_type == "Polygon" else []
        ancho = max(LineString(c[0:2]).length, LineString(c[1:3]).length) if c else 0.0
        capa = next((cp for p, cp in piezas if p.intersects(pg)), "")
        out.append(Ventana(pg, round(ancho, 2), capa))
    return out


# ---------------------------------------------------------------- cierres adicionales
def _vacios(els: list[Elemento]) -> list[Polygon]:
    """Vacíos y patios de luz: rectángulo de proyección con sus dos diagonales (la "X")."""
    cerrados = [g for el in els for g in el.geom if g.geom_type == "Polygon" and g.area >= 1.0]
    lineas = [g for el in els for g in el.geom if g.geom_type == "LineString"]
    out = []
    for pg in cerrados:
        diag = [ln for ln in lineas if ln.length > 0.5 * math.hypot(pg.bounds[2] - pg.bounds[0], pg.bounds[3] - pg.bounds[1])
                and pg.buffer(0.05).contains(ln)]
        if len(diag) >= 2:
            out.append(pg)
    return out


def _segmentos(g: BaseGeometry):
    if g.geom_type == "LineString":
        c = list(g.coords)
        for a, b in zip(c, c[1:]):
            yield a, b
    elif g.geom_type == "Polygon":
        c = list(g.exterior.coords)
        for a, b in zip(c, c[1:]):
            yield a, b


def _puentes(els: list[Elemento], solido: BaseGeometry, largo_min: float = 0.3, largo_max: float = 6.0) -> list[LineString]:
    """Líneas que unen dos muros en la dirección del muro: ventanas, vidrios o barandas dibujadas en
    capas sin nombre útil. Si la línea al prolongarse se mete en el muro por ambos lados, está
    cerrando un vano."""
    out = []
    for el in els:
        for g in el.geom:
            for a, b in _segmentos(g):
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                if not (largo_min <= L <= largo_max):
                    continue
                ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
                ok = True
                for (px, py), s in ((a, -1), (b, 1)):
                    if solido.distance(Point(px, py)) > 0.03:
                        ok = False
                        break
                    q = Point(px + s * ux * 0.25, py + s * uy * 0.25)
                    if solido.distance(q) > 0.01:
                        ok = False
                        break
                if not ok:
                    continue
                seg = LineString([a, b])
                if seg.difference(solido.buffer(0.01)).length < 0.2:
                    continue  # ya está dentro del muro: no cierra nada
                out.append(seg)
    return out


# ---------------------------------------------------------------- recintos
def _etiquetas(textos: list[Elemento]) -> list[tuple[Point, str, float]]:
    out = []
    for el in textos:
        t = el.texto.strip()
        if len(t) > 40 or _RE_BASURA.match(t):
            continue
        out.append((el.geom[0], t, el.altura_texto))
    return out


def _nombre_y_uso(etqs: list[tuple[Point, str]], pg: Polygon, hay_escalera: bool):
    """Devuelve nombre, uso, avisos, notas y zonas (para espacios abiertos con varios usos)."""
    avisos: list[str] = []
    notas: list[str] = []
    con_uso: list[tuple[Point, str, UsoRecinto]] = []
    for p, t in etqs:
        nota = nota_desde_texto(t)
        if nota:
            notas.append(nota)
            continue
        u = uso_desde_texto(t)
        if u is not None:
            con_uso.append((p, t, u))
    # una nota de ducto dentro de un baño no es un ducto
    if len({u for *_, u in con_uso}) > 1:
        con_uso = [c for c in con_uso if c[2] != UsoRecinto.DUCTO] or con_uso
    notas = sorted(set(notas))
    if not con_uso:
        if hay_escalera:
            return "Escalera", UsoRecinto.ESCALERA, avisos, notas, []
        t, largo = espesor_y_largo(pg)
        if pg.area < 1.2:
            return "Ducto", UsoRecinto.DUCTO, ["Sin nombre: se asume ducto por su tamaño."], notas, []
        if "ruta_evacuacion" in notas or (t * 2 < 1.8 and largo > 3 * t * 2):
            return "Circulación común", UsoRecinto.CIRCULACION, avisos, notas, []
        return "Sin nombre", UsoRecinto.OTRO, ["Recinto sin nombre: asigne el uso manualmente."], notas, []
    usos = list(dict.fromkeys(u for *_, u in con_uso))
    if len(usos) == 1:
        uso = usos[0]
        nombre = con_uso[0][1] if len(con_uso) == 1 else _bonito(usos[0])
        if uso == UsoRecinto.ESCALERA:
            nombre = "Escalera"
        return nombre, uso, avisos, notas, []
    ordenados = sorted(usos, key=lambda u: _ORDEN_NOMBRE.index(u) if u in _ORDEN_NOMBRE else 99)
    nombre = " - ".join(next(t for _, t, uu in con_uso if uu == u) for u in ordenados)
    if set(usos) == {UsoRecinto.SALA, UsoRecinto.COMEDOR}:
        uso = UsoRecinto.SALA_COMEDOR
    else:
        prioridad = [UsoRecinto.COCINA, UsoRecinto.BANO, UsoRecinto.ROPAS, UsoRecinto.ALCOBA, UsoRecinto.SALA,
                     UsoRecinto.COMEDOR, UsoRecinto.ESTUDIO]
        uso = next((u for u in prioridad if u in usos), usos[0])
    zonas = _zonificar(pg, con_uso)
    avisos.append("Espacio abierto con varios usos: se dividió en zonas aproximadas para el diseño (" +
                  ", ".join(f"{z['nombre']} {z['poligono'].area:.1f} m²" for z in zonas) + ").")
    return nombre, uso, avisos, notas, zonas


def _bonito(uso: UsoRecinto) -> str:
    return {UsoRecinto.BANO: "Baño", UsoRecinto.SALA_COMEDOR: "Sala - Comedor"}.get(
        uso, uso.value.replace("_", " ").capitalize())


def _zonificar(pg: Polygon, con_uso) -> list[dict]:
    """Reparte un espacio abierto entre sus etiquetas (diagrama de Voronoi recortado al recinto)."""
    from shapely.geometry import MultiPoint
    from shapely.ops import voronoi_diagram

    pts = [p for p, *_ in con_uso]
    if len(pts) < 2:
        return []
    celdas = voronoi_diagram(MultiPoint(pts), envelope=pg.envelope.buffer(5))
    por_uso: dict[UsoRecinto, list] = defaultdict(list)
    nombres: dict[UsoRecinto, str] = {}
    for celda in celdas.geoms:
        for p, t, u in con_uso:
            if celda.contains(p):
                por_uso[u].append(celda.intersection(pg))
                nombres.setdefault(u, t)
                break
    zonas = []
    for u, partes in por_uso.items():
        g = unary_union(partes)
        g = max(_poligonos(g), key=lambda q: q.area) if g.geom_type != "Polygon" else g
        zonas.append({"nombre": nombres[u], "uso": u, "poligono": g})
    zonas.sort(key=lambda z: _ORDEN_NOMBRE.index(z["uso"]) if z["uso"] in _ORDEN_NOMBRE else 99)
    return zonas


def interpretar(plano: PlanoLeido, capas: dict[str, InfoCapa]) -> Interpretacion:
    por_cat: dict[Categoria, list[Elemento]] = defaultdict(list)
    for el in plano.elementos:
        por_cat[capas[el.capa].categoria].append(el)
    avisos: list[str] = []

    muros = _detectar_muros(por_cat[Categoria.MUROS], capas)
    if muros.is_empty:
        avisos.append("No se encontraron muros. Indique la capa de muros con mapa_capas.")
    columnas = _detectar_columnas(por_cat[Categoria.COLUMNAS], capas, muros)
    bajos = unary_union([g.buffer(0.05, cap_style="flat") if g.geom_type == "LineString" else g
                         for el in por_cat[Categoria.MUROS_BAJOS] for g in el.geom]) \
        if por_cat[Categoria.MUROS_BAJOS] else Polygon()
    solido = unary_union([muros] + columnas)

    puertas = _detectar_puertas(plano.elementos, capas, solido)
    cierres_extra = _puertas_sin_barrido(por_cat[Categoria.PUERTAS], puertas, solido)
    ventanas = _detectar_ventanas(por_cat[Categoria.VENTANAS], solido)

    vacios = _vacios(por_cat[Categoria.PROYECCIONES])
    base = unary_union([solido, bajos] + [_cierre_puerta(p) for p in puertas] + cierres_extra +
                       [v.poligono for v in ventanas])
    puentes = _puentes(por_cat[Categoria.OTROS] + por_cat[Categoria.MUROS_BAJOS] + por_cat[Categoria.VENTANAS],
                       base)
    barrera = unary_union([base] + [ln.buffer(0.04, cap_style="flat") for ln in puentes] +
                          [v.exterior.buffer(0.03) for v in vacios])
    escaleras: list[BaseGeometry] = [g for el in por_cat[Categoria.ESCALERAS] for g in el.geom]

    recintos: list[RecintoDetectado] = []
    exterior = None
    unidades: dict[str, list[str]] = {}
    if not barrera.is_empty:
        dom = box(*barrera.bounds).buffer(1.0, join_style="mitre")
        libre = dom.difference(barrera)
        # apertura morfológica: corta las fugas de pelo (< 2·HOLGURA) que dejan los errores de dibujo
        piezas = []
        for pz in _poligonos(libre):
            for nucleo in _poligonos(pz.buffer(-HOLGURA, join_style="mitre")):
                piezas += _poligonos(nucleo.buffer(HOLGURA, join_style="mitre").intersection(pz))
        piezas = sorted(piezas, key=lambda p: -p.area)
        borde = dom.exterior
        interiores = []
        for pg in piezas:
            if pg.exterior.distance(borde) < 0.05 and exterior is None:
                exterior = pg
                continue
            if pg.area >= AREA_MIN_RECINTO:
                interiores.append(pg.simplify(0.005))

        textos = [el for el in plano.elementos if el.texto and capas[el.capa].categoria not in
                  (Categoria.COTAS, Categoria.EJES, Categoria.IGNORAR)]
        etqs = _etiquetas(textos)
        etqs_unidad = [(p, t) for p, t, _ in etqs if _RE_UNIDAD.match(normalizar(t))]
        # orden de lectura: de arriba hacia abajo, de izquierda a derecha
        interiores.sort(key=lambda p: (-round(p.centroid.y, 0), p.centroid.x))
        sin_ubicar = []
        for i, pg in enumerate(interiores, 1):
            dentro = [(p, t) for p, t, _ in etqs if pg.contains(p) and not _RE_UNIDAD.match(normalizar(t))]
            hay_escalera = any(pg.intersects(g) for g in escaleras) or \
                any(re.search(r"(^|\W)(sube|baja)(\W|$)", normalizar(t)) for _, t in dentro)
            nombre, uso, av, notas, zonas = _nombre_y_uso(dentro, pg, hay_escalera)
            r = RecintoDetectado(f"R{i:03d}", nombre, uso, pg, [t for _, t in dentro], avisos=av, notas=notas,
                                 zonas=zonas)
            if "ventilacion_mecanica" in notas:
                r.avisos.append("Ventilación mecánica indicada: prever salida para extractor.")
            r.comun = uso in _ZONAS_COMUNES or (uso == UsoRecinto.OTRO and pg.area > 15)
            recintos.append(r)
        if exterior is not None:
            for p, t, _ in etqs:
                if exterior.contains(p) and uso_desde_texto(t) not in (None, UsoRecinto.PATIO):
                    sin_ubicar.append(t)
        if sin_ubicar:
            avisos.append("Nombres de recinto que quedaron por fuera (posible muro o vano sin cerrar): " +
                          ", ".join(sorted(set(sin_ubicar))))

        _lados_de_vanos(puertas, ventanas, recintos)
        unidades = _unidades(recintos, puertas, etqs_unidad)

    aparatos = _aparatos(por_cat[Categoria.APARATOS], recintos)

    for r in recintos:
        if r.uso == UsoRecinto.BANO and not any(a.recinto == r.id for a in aparatos):
            r.avisos.append("Baño sin aparatos sanitarios detectados.")
    lineas_vanos = [g for el in por_cat[Categoria.VENTANAS] for g in el.geom
                    if solido.is_empty or g.distance(solido) <= 0.30] + puentes
    # dibujo de escaleras: linework sin categoría que cae dentro de los recintos de escalera
    escalera_geo = unary_union([r.poligono for r in recintos if r.uso == UsoRecinto.ESCALERA])
    if not escalera_geo.is_empty:
        for el in por_cat[Categoria.OTROS] + por_cat[Categoria.ESCALERAS]:
            for g in el.geom:
                if g.geom_type in ("LineString", "Polygon") and escalera_geo.buffer(0.05).contains(g):
                    escaleras.append(g)
    ejes = [g for el in por_cat[Categoria.EJES] for g in el.geom]
    circ = [g for g in ejes if g.geom_type == "Polygon"]
    textos_ejes = [(el.geom[0], el.texto, el.altura_texto) for el in plano.elementos
                   if el.texto and any(cg.buffer(0.05).contains(el.geom[0]) for cg in circ)]
    return Interpretacion(muros, bajos, columnas, puertas, ventanas, aparatos, recintos, unidades, exterior,
                          escaleras, capas, avisos, vacios=vacios, lineas_vanos=lineas_vanos,
                          aparatos_geom=[g for el in por_cat[Categoria.APARATOS] for g in el.geom],
                          ejes=ejes, textos_ejes=textos_ejes)


def _recinto_en(p: Point, recintos: list[RecintoDetectado]) -> Optional[str]:
    for r in recintos:
        if r.poligono.contains(p):
            return r.id
    return None


def _lados_de_vanos(puertas: list[Puerta], ventanas: list[Ventana], recintos: list[RecintoDetectado]) -> None:
    for p in puertas:
        (x0, y0), (x1, y1) = p.bisagra, p.extremo
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        nx, ny = -(y1 - y0) / L, (x1 - x0) / L
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        lados = []
        for s in (1, -1):
            rid = None
            for d in (0.25, 0.4, 0.6):
                rid = _recinto_en(Point(mx + s * nx * d, my + s * ny * d), recintos)
                if rid:
                    break
            lados.append(rid or "EXT")
        p.recintos = lados
    for v in ventanas:
        cerca = [r.id for r in recintos if r.poligono.distance(v.poligono) < 0.05]
        v.recintos = cerca or ["EXT"]


def _unidades(recintos: list[RecintoDetectado], puertas: list[Puerta], etqs_unidad) -> dict[str, list[str]]:
    privados = {r.id for r in recintos if not r.comun}
    ady: dict[str, set[str]] = defaultdict(set)
    for p in puertas:
        a, b = p.recintos
        if a in privados and b in privados:
            ady[a].add(b)
            ady[b].add(a)
    visto: set[str] = set()
    grupos: list[list[str]] = []
    for r in recintos:
        if r.id not in privados or r.id in visto:
            continue
        pila, comp = [r.id], []
        while pila:
            x = pila.pop()
            if x in visto:
                continue
            visto.add(x)
            comp.append(x)
            pila += list(ady[x] - visto)
        grupos.append(comp)

    por_id = {r.id: r for r in recintos}
    unidades: dict[str, list[str]] = {}
    n_sin = 0
    for comp in grupos:
        if len(comp) == 1 and por_id[comp[0]].uso in (UsoRecinto.PATIO, UsoRecinto.OTRO):
            continue  # patio o recinto suelto: no es una unidad
        nombre = None
        geo = unary_union([por_id[c].poligono for c in comp])
        for p, t in etqs_unidad:
            if geo.buffer(0.3).contains(p):
                nombre = t.upper()
                break
        if nombre is None:
            # la etiqueta de unidad puede estar en la circulación de acceso: la más cercana
            if etqs_unidad:
                p, t = min(etqs_unidad, key=lambda pt: geo.distance(pt[0]))
                if geo.distance(p) < 1.0 and t.upper() not in unidades:
                    nombre = t.upper()
        if nombre is None or nombre in unidades:
            n_sin += 1
            nombre = f"UNIDAD {n_sin}"
        unidades[nombre] = sorted(comp)
        for c in comp:
            por_id[c].unidad = nombre
    return dict(sorted(unidades.items()))


def _aparatos(els: list[Elemento], recintos: list[RecintoDetectado]) -> list[Aparato]:
    por_inst: dict = defaultdict(list)
    for el in els:
        if el.instancia is None or not el.geom:
            continue
        por_inst[el.instancia].append(el)
    out = []
    for grupo in por_inst.values():
        g = unary_union([x for el in grupo for x in el.geom])
        if g.is_empty or g.area > 6 or (g.bounds[2] - g.bounds[0]) > 4:
            continue  # bloque que agrupa un apartamento completo, no un aparato
        c = g.centroid
        nombre = grupo[0].bloque_interno or grupo[0].bloque or ""
        a = Aparato(tipo_aparato(nombre), (round(c.x, 3), round(c.y, 3)), nombre, grupo[0].capa)
        a.recinto = _recinto_en(c, recintos)
        if a.tipo == "aparato":
            capa = normalizar(grupo[0].capa)
            if "bano" in capa or "sanit" in capa:
                a.tipo = "aparato_sanitario"
            elif "cocina" in capa or "kitchen" in capa:
                a.tipo = "aparato_cocina"
        out.append(a)
    return out
