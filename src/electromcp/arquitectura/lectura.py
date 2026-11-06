"""Lectura del plano arquitectónico y explosión de bloques.

Convierte un DXF cualquiera (bloques anidados, bloques dinámicos, bloques espejados,
entidades en capa 0 que heredan la capa del bloque) en una lista plana de
:class:`Elemento`, cada uno con su geometría Shapely en metros y coordenadas de mundo.

Nada de esto modifica el archivo original.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

import ezdxf
from ezdxf import path as zpath
from ezdxf.document import Drawing
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

# $INSUNITS -> factor a metros
_UNIDADES = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 14: 0.1}
_NOMBRE_UNIDAD = {0.001: "mm", 0.01: "cm", 0.1: "dm", 1.0: "m", 0.0254: "in", 0.3048: "ft"}

TOL_CURVAS = 0.01  # m, tolerancia de aproximación de arcos y curvas


@dataclass
class Elemento:
    """Una entidad del plano ya explotada y llevada a metros."""

    tipo: str  # tipo DXF: LINE, ARC, HATCH, MTEXT...
    capa: str  # capa efectiva (la capa 0 hereda la del bloque)
    geom: list[BaseGeometry]  # una o varias geometrías (un HATCH puede tener varias islas)
    bloque: Optional[str] = None  # bloque de nivel superior que lo contiene
    instancia: Optional[int] = None  # id del INSERT más interno (agrupa puertas, aparatos...)
    bloque_interno: Optional[str] = None  # nombre del bloque más interno
    texto: Optional[str] = None
    altura_texto: float = 0.0
    relleno_solido: bool = False
    patron: str = ""
    # datos de arco (para detectar el barrido de puertas)
    centro: Optional[tuple[float, float]] = None
    radio: float = 0.0
    angulos: tuple[float, float] = (0.0, 0.0)  # grados, sentido antihorario
    extremos: tuple[tuple[float, float], ...] = ()

    @property
    def cerrado(self) -> bool:
        return any(g.geom_type == "Polygon" for g in self.geom)


@dataclass
class PlanoLeido:
    ruta: str
    factor_m: float  # factor aplicado para llevar a metros
    unidad_origen: str
    elementos: list[Elemento]
    descartados: list[Elemento] = field(default_factory=list)  # fuera de la zona del plano
    capas_doc: dict[str, dict] = field(default_factory=dict)
    n_bloques: int = 0
    n_entidades_modelo: int = 0
    avisos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
def _recorrer(entidades, capa_padre: Optional[str], bloque: Optional[str], inst: Optional[int],
              contador: list[int], profundidad: int = 0, interno: Optional[str] = None) -> Iterator[tuple]:
    for e in entidades:
        capa = e.dxf.get("layer", "0")
        if capa == "0" and capa_padre:
            capa = capa_padre
        t = e.dxftype()
        if t == "INSERT":
            if profundidad > 12:
                continue
            contador[0] += 1
            yo = contador[0]
            try:
                hijos = list(e.virtual_entities())
            except Exception:  # bloque corrupto o escala nula
                continue
            nombre = e.dxf.name
            if nombre.startswith("*U") and interno:  # bloque dinámico anónimo: conserva el nombre útil
                nombre = interno
            yield from _recorrer(hijos, capa, bloque or e.dxf.name, yo, contador, profundidad + 1, nombre)
        else:
            yield e, capa, bloque, inst, interno


def _escalar(g: BaseGeometry, f: float) -> BaseGeometry:
    if f == 1.0:
        return g
    from shapely import affinity

    return affinity.scale(g, f, f, origin=(0, 0))


def _geometria(e, f: float) -> list[BaseGeometry]:
    t = e.dxftype()
    out: list[BaseGeometry] = []
    try:
        if t == "HATCH" or t == "MPOLYGON":
            for p in zpath.from_hatch(e):
                pts = [(v.x * f, v.y * f) for v in p.flattening(TOL_CURVAS / max(f, 1e-9))]
                if len(pts) >= 3:
                    pg = Polygon(pts).buffer(0)
                    if not pg.is_empty:
                        out.append(pg)
        elif t == "SOLID" or t == "TRACE":
            pts = [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx3, e.dxf.vtx2]
            out.append(Polygon([(v.x * f, v.y * f) for v in pts]).buffer(0))
        elif t in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
            if t == "POLYLINE" and (e.is_poly_face_mesh or e.is_polygon_mesh):
                return []
            p = zpath.make_path(e)
            pts = [(v.x * f, v.y * f) for v in p.flattening(TOL_CURVAS / max(f, 1e-9))]
            # quitar duplicados consecutivos
            limpio = [pts[0]] if pts else []
            for q in pts[1:]:
                if abs(q[0] - limpio[-1][0]) > 1e-9 or abs(q[1] - limpio[-1][1]) > 1e-9:
                    limpio.append(q)
            if len(limpio) < 2:
                return []
            cerrado = t == "CIRCLE" or (t in ("LWPOLYLINE", "POLYLINE") and e.closed)
            if t == "ELLIPSE" and abs((e.dxf.end_param - e.dxf.start_param) - math.tau) < 1e-6:
                cerrado = True
            if not cerrado and len(limpio) >= 4 and Point(limpio[0]).distance(Point(limpio[-1])) < 1e-6:
                cerrado = True
            if cerrado and len(limpio) >= 3:
                pg = Polygon(limpio)
                if not pg.is_valid:
                    pg = pg.buffer(0)
                if not pg.is_empty and pg.area > 0:
                    out.append(pg)
                    return out
            out.append(LineString(limpio))
        elif t == "POINT":
            v = e.dxf.location
            out.append(Point(v.x * f, v.y * f))
    except Exception:
        return []
    return out


def _factor_unidades(doc: Drawing, forzar: Optional[str]) -> tuple[float, str, list[str]]:
    avisos = []
    if forzar:
        inv = {v: k for k, v in _NOMBRE_UNIDAD.items()}
        if forzar not in inv:
            raise ValueError(f"Unidad desconocida {forzar!r}; use mm, cm, m")
        return inv[forzar], forzar, avisos
    cod = doc.header.get("$INSUNITS", 0)
    if cod in _UNIDADES:
        f = _UNIDADES[cod]
        return f, _NOMBRE_UNIDAD.get(f, str(cod)), avisos
    avisos.append("El dibujo no declara unidades ($INSUNITS); se deducen del tamaño.")
    return 0.0, "?", avisos  # se deduce luego del tamaño


def leer_plano(ruta: str | Path, unidades: Optional[str] = None) -> PlanoLeido:
    """Lee un DXF, explota todos los bloques y devuelve elementos en metros."""
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".dwg":
        raise ValueError("ezdxf no lee DWG directamente. Use convertir_dwg_a_dxf primero.")
    try:
        doc = ezdxf.readfile(str(ruta))
    except ezdxf.DXFStructureError:
        from ezdxf import recover

        doc, _aud = recover.readfile(str(ruta))
    msp = doc.modelspace()

    f, nombre_u, avisos = _factor_unidades(doc, unidades)

    crudos = list(_recorrer(msp, None, None, None, [0]))
    if f == 0.0:  # deducir de la extensión
        xs, ys = [], []
        for e, *_ in crudos[:5000]:
            for g in _geometria(e, 1.0):
                b = g.bounds
                xs += [b[0], b[2]]
                ys += [b[1], b[3]]
        if xs:
            xs.sort(); ys.sort()
            n = len(xs)
            lado = max(xs[int(n * 0.95)] - xs[int(n * 0.05)], ys[int(n * 0.95)] - ys[int(n * 0.05)])
            f, nombre_u = (0.001, "mm") if lado > 2000 else (0.01, "cm") if lado > 200 else (1.0, "m")
        else:
            f, nombre_u = 1.0, "m"
        avisos.append(f"Unidades deducidas: {nombre_u}.")

    capas_doc = {}
    for c in doc.layers:
        capas_doc[c.dxf.name] = {"color": c.color, "apagada": c.is_off(), "congelada": c.is_frozen()}

    elementos: list[Elemento] = []
    for e, capa, bloque, inst, interno in crudos:
        t = e.dxftype()
        if t in ("MTEXT", "TEXT", "ATTRIB"):
            try:
                txt = e.plain_text() if t == "MTEXT" else e.dxf.text
                ins = e.dxf.insert
                if t == "TEXT" and e.dxf.halign or (t == "TEXT" and e.dxf.valign):
                    ins = e.dxf.get("align_point", ins)
                h = e.dxf.char_height if t == "MTEXT" else e.dxf.height
            except Exception:
                continue
            txt = " ".join(str(txt).split())
            if not txt:
                continue
            elementos.append(Elemento(t, capa, [Point(ins.x * f, ins.y * f)], bloque, inst, interno,
                                      texto=txt, altura_texto=h * f))
            continue
        if t == "DIMENSION":
            elementos.append(Elemento(t, capa, [], bloque, inst, interno))
            continue
        geom = _geometria(e, f)
        if not geom:
            continue
        el = Elemento(t, capa, geom, bloque, inst, interno)
        if t == "HATCH":
            el.relleno_solido = bool(e.dxf.solid_fill)
            el.patron = e.dxf.pattern_name or ""
        elif t == "ARC":
            c = e.ocs().to_wcs(e.dxf.center)  # bloques espejados: el arco queda con extrusión -Z
            el.centro = (c.x * f, c.y * f)
            el.radio = e.dxf.radius * f
            # en un bloque espejado el arco virtual conserva sentido antihorario con extrusión
            # posiblemente negativa; usamos los extremos reales de la geometría
            ls = geom[0]
            el.extremos = (tuple(ls.coords[0]), tuple(ls.coords[-1]))
            a0 = math.degrees(math.atan2(el.extremos[0][1] - el.centro[1], el.extremos[0][0] - el.centro[0]))
            a1 = math.degrees(math.atan2(el.extremos[1][1] - el.centro[1], el.extremos[1][0] - el.centro[0]))
            el.angulos = (a0, a1)
        elementos.append(el)

    plano = PlanoLeido(str(ruta), f, nombre_u, [], capas_doc=capas_doc,
                       n_bloques=len([b for b in doc.blocks if not b.name.startswith("*")]),
                       n_entidades_modelo=len(msp), avisos=avisos)
    plano.elementos, plano.descartados = _zona_principal(elementos)
    if plano.descartados:
        plano.avisos.append(f"{len(plano.descartados)} entidades lejos del plano se descartaron "
                            "(basura, referencias o vistas fuera de la planta).")
    return plano


def _zona_principal(elementos: list[Elemento]) -> tuple[list[Elemento], list[Elemento]]:
    """Separa las entidades que están lejos de la zona donde se concentra el dibujo."""
    centros = []
    for el in elementos:
        if el.geom:
            b = el.geom[0].bounds
            centros.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
    if len(centros) < 10:
        return elementos, []
    xs = sorted(c[0] for c in centros)
    ys = sorted(c[1] for c in centros)
    n = len(xs)
    x0, x1 = xs[int(n * 0.02)], xs[int(n * 0.98) - 1]
    y0, y1 = ys[int(n * 0.02)], ys[int(n * 0.98) - 1]
    m = max(x1 - x0, y1 - y0, 1.0) * 0.5
    x0, x1, y0, y1 = x0 - m, x1 + m, y0 - m, y1 + m
    dentro, fuera = [], []
    for el in elementos:
        if not el.geom:
            dentro.append(el)
            continue
        b = el.geom[0].bounds
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        (dentro if x0 <= cx <= x1 and y0 <= cy <= y1 else fuera).append(el)
    return dentro, fuera
