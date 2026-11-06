"""Salidas del paso 2: DXF arquitectónico depurado, plano de verificación PNG, reporte y proyecto."""

from __future__ import annotations

import json
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from ..layers import CAPAS, TIPOS_LINEA
from ..model import Proyecto, Recinto, TrazoArq
from .analisis import Interpretacion, _poligonos

ESTILO = "ELECTRO"
_CAPAS_ARQ = [n for n in CAPAS if n.startswith("ARQ-")]


def _coords(g: BaseGeometry, tol: float = 0.003) -> list[list[tuple[float, float]]]:
    """Lista de polilíneas (x, y) para cualquier geometría."""
    if g.is_empty:
        return []
    g = g.simplify(tol) if tol else g
    t = g.geom_type
    if t == "Polygon":
        return [list(g.exterior.coords)] + [list(r.coords) for r in g.interiors]
    if t in ("LineString", "LinearRing"):
        return [list(g.coords)]
    if hasattr(g, "geoms"):
        out = []
        for h in g.geoms:
            out += _coords(h, 0)
        return out
    return []


def _hoja_y_arco(p) -> list[list[tuple[float, float]]]:
    trazos = []
    if p.abierta:
        trazos.append([p.bisagra, tuple(p.abierta)])
    if p.arco:
        trazos.append([tuple(q) for q in p.arco])
    return trazos


# ---------------------------------------------------------------- DXF depurado
def escribir_dxf(interp: Interpretacion, ruta: str | Path, incluir_aparatos: bool = True,
                 incluir_ejes: bool = True, titulo: str = "") -> Path:
    """Escribe un DXF nuevo, limpio: solo capas ARQ-*, sin bloques ni basura, en metros."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2018", setup=True, units=ezdxf.units.M)
    doc.header["$INSUNITS"] = 6
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LTSCALE"] = 0.05
    for nombre, (desc, patron) in TIPOS_LINEA.items():
        if nombre in doc.linetypes:
            doc.linetypes.remove(nombre)
        doc.linetypes.add(nombre, pattern=patron, description=desc)
    for n in _CAPAS_ARQ:
        c = CAPAS[n]
        capa = doc.layers.add(n)
        capa.color = c.color
        capa.dxf.linetype = c.tipo_linea
        capa.dxf.lineweight = c.grosor
        capa.dxf.plot = 1 if c.imprimible else 0
        capa.description = c.descripcion
    if ESTILO not in doc.styles:
        doc.styles.add(ESTILO, font="arial.ttf")
    msp = doc.modelspace()

    def pl(pts, capa, cerrada=False):
        if len(pts) >= 2:
            msp.add_lwpolyline(pts, close=cerrada, dxfattribs={"layer": capa})

    def txt(s, pos, h, capa):
        t = msp.add_text(s, height=h, dxfattribs={"layer": capa, "style": ESTILO})
        t.set_placement(pos, align=TextEntityAlignment.MIDDLE_CENTER)

    # muros: contorno + achurado sólido gris (con huecos)
    for pg in _poligonos(interp.muros):
        anillos = _coords(pg, 0.002)
        for a in anillos:
            pl(a[:-1], "ARQ-MUROS", True)
        h = msp.add_hatch(color=253, dxfattribs={"layer": "ARQ-MUROS-RELLENO"})
        h.paths.add_polyline_path(anillos[0][:-1], is_closed=True, flags=1)  # exterior
        for a in anillos[1:]:
            h.paths.add_polyline_path(a[:-1], is_closed=True, flags=0)
    for pg in _poligonos(interp.muros_bajos):
        for a in _coords(pg):
            pl(a[:-1], "ARQ-MUROS", True)
    for pg in interp.columnas:
        a = _coords(pg)[0][:-1]
        pl(a, "ARQ-ESTRUCTURA", True)
        h = msp.add_hatch(color=8, dxfattribs={"layer": "ARQ-ESTRUCTURA"})
        h.paths.add_polyline_path(a, is_closed=True)
    # vanos
    for p in interp.puertas:
        for tr in _hoja_y_arco(p):
            pl(tr, "ARQ-VANOS")
    for g in interp.lineas_vanos:
        for a in _coords(g):
            pl(a, "ARQ-VANOS", False)
    for v in interp.vacios:
        a = _coords(v)[0]
        pl(a[:-1], "ARQ-REFERENCIA", True)
        x0, y0, x1, y1 = v.bounds
        pl([(x0, y0), (x1, y1)], "ARQ-REFERENCIA")
        pl([(x0, y1), (x1, y0)], "ARQ-REFERENCIA")
    for g in interp.escaleras:
        for a in _coords(g):
            pl(a[:-1] if g.geom_type == "Polygon" else a, "ARQ-ESCALERAS", g.geom_type == "Polygon")
    if incluir_aparatos:
        for g in interp.aparatos_geom:
            for a in _coords(g):
                pl(a[:-1] if g.geom_type == "Polygon" else a, "ARQ-APARATOS", g.geom_type == "Polygon")
    if incluir_ejes:
        for g in interp.ejes:
            for a in _coords(g, 0):
                pl(a[:-1] if g.geom_type == "Polygon" else a, "ARQ-EJES", g.geom_type == "Polygon")
        for p, t, h in interp.textos_ejes:
            txt(t, (p.x, p.y), max(h, 0.15), "ARQ-EJES")
    # recintos: contorno (no imprime) + nombre + área
    for r in interp.recintos:
        pl(_coords(r.poligono)[0][:-1], "ARQ-RECINTOS-CONTORNO", True)
        c = r.poligono.representative_point()
        txt(r.nombre.upper(), (c.x, c.y + 0.10), 0.12, "ARQ-RECINTOS")
        txt(f"{r.area:.2f} m²".replace(".", ","), (c.x, c.y - 0.08), 0.09, "ARQ-RECINTOS")
    for nombre, ids in interp.unidades.items():
        from shapely.ops import unary_union

        geo = unary_union([interp.recinto(i).poligono for i in ids])
        area = sum(interp.recinto(i).area for i in ids)
        c = max(_poligonos(geo), key=lambda q: q.area).representative_point()
        txt(nombre, (c.x, c.y - 0.55), 0.18, "ARQ-RECINTOS")
        txt(f"Área libre {area:.2f} m²".replace(".", ","), (c.x, c.y - 0.78), 0.10, "ARQ-RECINTOS")
    if titulo:
        doc.header["$PROJECTNAME"] = titulo[:200]
    doc.saveas(ruta)
    return ruta


# ---------------------------------------------------------------- plano de verificación
_PALETA = ["#4C78A8", "#F58518", "#54A24B", "#B279A2", "#E45756", "#72B7B2", "#EECA3B", "#9D755D", "#FF9DA6",
           "#BAB0AC"]


def plano_verificacion(interp: Interpretacion, ruta: str | Path, titulo: str = "", dpi: int = 110) -> Path:
    """PNG para revisar la interpretación: recintos coloreados por unidad, puertas, ventanas, avisos."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPolygon

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    geoms = [r.poligono for r in interp.recintos] + _poligonos(interp.muros)
    if not geoms:
        raise ValueError("No hay nada que dibujar")
    x0 = min(g.bounds[0] for g in geoms) - 0.6
    y0 = min(g.bounds[1] for g in geoms) - 0.6
    x1 = max(g.bounds[2] for g in geoms) + 0.6
    y1 = max(g.bounds[3] for g in geoms) + 0.6
    alto = 16.0
    ancho = max(alto * (x1 - x0) / (y1 - y0), 6) + 5.5
    fig = plt.figure(figsize=(ancho, alto))
    ax = fig.add_axes([0.02, 0.03, (ancho - 5.5) / ancho - 0.02, 0.92])
    ax.set_aspect("equal")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.axis("off")

    colores = {u: _PALETA[i % len(_PALETA)] for i, u in enumerate(interp.unidades)}

    def poly(pg: Polygon, **kw):
        ax.add_patch(MplPolygon(list(pg.exterior.coords), closed=True, **kw))
        for r in pg.interiors:
            ax.add_patch(MplPolygon(list(r.coords), closed=True, facecolor="white", edgecolor="none"))

    for r in interp.recintos:
        col = colores.get(r.unidad, "#D9D9D9" if r.comun else "#EFEFEF")
        poly(r.poligono, facecolor=col, alpha=0.35 if r.unidad else 0.6, edgecolor="none")
        if r.zonas:
            for z in r.zonas:
                b = z["poligono"].boundary.difference(r.poligono.exterior.buffer(0.02))
                for tr in _coords(b, 0):
                    ax.plot(*zip(*tr), color="#555", lw=0.6, ls=(0, (4, 3)))
    for pg in _poligonos(interp.muros):
        poly(pg, facecolor="#3A3A3A", edgecolor="#000", lw=0.4)
    for pg in interp.columnas:
        poly(pg, facecolor="#8B3A3A", edgecolor="#000", lw=0.4)
    for g in interp.lineas_vanos:
        for tr in _coords(g):
            ax.plot(*zip(*tr), color="#1F9BD1", lw=1.0)
    for p in interp.puertas:
        ax.plot(*zip(p.bisagra, p.extremo), color="#D62728", lw=2.2, solid_capstyle="butt")
        for tr in _hoja_y_arco(p):
            ax.plot(*zip(*tr), color="#D62728", lw=0.6)
    for g in interp.aparatos_geom + interp.escaleras:
        for tr in _coords(g, 0.01):
            ax.plot(*zip(*tr), color="#8C8C8C", lw=0.3)
    for v in interp.vacios:
        x_0, y_0, x_1, y_1 = v.bounds
        ax.plot([x_0, x_1], [y_0, y_1], color="#999", lw=0.6, ls="--")
        ax.plot([x_0, x_1], [y_1, y_0], color="#999", lw=0.6, ls="--")

    for r in interp.recintos:
        c = r.poligono.representative_point()
        aviso = " *" if any("sin nombre" in a.lower() for a in r.avisos) else ""
        fs = 7 if r.area > 4 else 5.5
        ax.text(c.x, c.y, f"{r.id}\n{r.nombre}{aviso}\n{r.area:.2f} m²".replace(".", ","), ha="center",
                va="center", fontsize=fs, color="#111", linespacing=1.15,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75))

    fig.text(0.02, 0.975, titulo or "Interpretación del plano arquitectónico", fontsize=16, weight="bold")
    fig.text(0.02, 0.955, f"{len(interp.recintos)} recintos · {len(interp.unidades)} unidades · "
             f"{len(interp.puertas)} puertas · {len(interp.ventanas)} ventanas · {len(interp.columnas)} columnas",
             fontsize=10, color="#444")
    # panel derecho
    xt = (ancho - 5.3) / ancho
    y = 0.93
    fig.text(xt, y, "Unidades", fontsize=12, weight="bold")
    y -= 0.022
    for u, ids in interp.unidades.items():
        area = sum(interp.recinto(i).area for i in ids)
        fig.patches.append(matplotlib.patches.Rectangle((xt, y - 0.004), 0.012, 0.012, transform=fig.transFigure,
                                                        color=colores[u], alpha=0.6))
        fig.text(xt + 0.018, y, f"{u}: {len(ids)} recintos, {area:.1f} m²".replace(".", ","), fontsize=9)
        y -= 0.018
    y -= 0.012
    fig.text(xt, y, "Convenciones", fontsize=12, weight="bold")
    y -= 0.022
    for color, etq in (("#3A3A3A", "Muro detectado"), ("#8B3A3A", "Columna"), ("#D62728", "Puerta (vano cerrado)"),
                       ("#1F9BD1", "Ventana / vidrio / baranda"), ("#D9D9D9", "Zona común")):
        fig.patches.append(matplotlib.patches.Rectangle((xt, y - 0.004), 0.012, 0.012, transform=fig.transFigure,
                                                        color=color))
        fig.text(xt + 0.018, y, etq, fontsize=9)
        y -= 0.018
    avisos = list(interp.avisos)
    for r in interp.recintos:
        for a in r.avisos:
            if "extractor" in a:
                continue
            avisos.append(f"{r.id} {r.nombre}: {a}")
    if avisos:
        y -= 0.012
        fig.text(xt, y, "Para revisar", fontsize=12, weight="bold")
        y -= 0.02
        import textwrap

        for a in avisos[:22]:
            for i, ln in enumerate(textwrap.wrap(a, 62)):
                fig.text(xt + (0 if i == 0 else 0.008), y, ("• " if i == 0 else "") + ln, fontsize=7.5, color="#333")
                y -= 0.0135
            if y < 0.03:
                break
    fig.savefig(ruta, dpi=dpi, facecolor="white")
    plt.close(fig)
    return ruta


# ---------------------------------------------------------------- reporte y proyecto
def reporte(interp: Interpretacion, plano=None) -> dict:
    from collections import Counter

    rep = {
        "resumen": {
            "recintos": len(interp.recintos), "unidades": len(interp.unidades), "puertas": len(interp.puertas),
            "ventanas": len(interp.ventanas), "columnas": len(interp.columnas),
            "aparatos": dict(Counter(a.tipo for a in interp.aparatos)),
            "area_muros_m2": round(interp.muros.area, 2),
            "area_libre_total_m2": round(sum(r.area for r in interp.recintos), 2),
        },
        "unidades": {u: {"recintos": ids, "area_m2": round(sum(interp.recinto(i).area for i in ids), 2)}
                     for u, ids in interp.unidades.items()},
        "recintos": [r.resumen() for r in interp.recintos],
        "puertas": [{"ancho_m": p.ancho, "tipo": p.tipo, "entre": p.recintos,
                     "bisagra": [round(v, 3) for v in p.bisagra]} for p in interp.puertas],
        "ventanas": [{"ancho_m": v.ancho, "recintos": v.recintos,
                      "centro": [round(v.poligono.centroid.x, 3), round(v.poligono.centroid.y, 3)]}
                     for v in interp.ventanas],
        "aparatos": [{"tipo": a.tipo, "bloque": a.bloque, "recinto": a.recinto, "centro": list(a.centro)}
                     for a in interp.aparatos],
        "capas": [i.resumen() for i in sorted(interp.capas.values(), key=lambda i: (i.categoria.value, i.nombre))],
        "avisos": interp.avisos,
    }
    if plano is not None:
        rep["archivo"] = {"ruta": plano.ruta, "unidades_origen": plano.unidad_origen, "factor_a_m": plano.factor_m,
                          "entidades_modelo": plano.n_entidades_modelo, "bloques": plano.n_bloques,
                          "entidades_explotadas": len(plano.elementos), "descartadas": len(plano.descartados),
                          "avisos": plano.avisos}
    return rep


def aplicar_a_proyecto(proyecto: Proyecto, interp: Interpretacion, nivel: str, reemplazar: bool = True,
                       incluir_aparatos: bool = True) -> dict:
    """Carga muros, vanos y recintos detectados en el proyecto (nivel indicado)."""
    if nivel not in proyecto.niveles:
        proyecto.niveles.append(nivel)
    if reemplazar:
        proyecto.arquitectura = [a for a in proyecto.arquitectura if a.nivel != nivel]
        viejos = {r.id for r in proyecto.recintos if r.nivel == nivel}
        proyecto.recintos = [r for r in proyecto.recintos if r.nivel != nivel]
        for s in proyecto.salidas:
            if s.recinto in viejos:
                s.recinto = None
    trazos: list[TrazoArq] = []

    def add(pts, capa, cerrado=False):
        pts = [(round(x, 4), round(y, 4)) for x, y in pts]
        if cerrado and len(pts) > 3 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) >= 2:
            trazos.append(TrazoArq(capa=capa, puntos=pts, cerrado=cerrado, nivel=nivel))

    for pg in _poligonos(interp.muros) + _poligonos(interp.muros_bajos):
        for a in _coords(pg):
            add(a, "ARQ-MUROS", True)
    for pg in interp.columnas:
        add(_coords(pg)[0], "ARQ-ESTRUCTURA", True)
    for p in interp.puertas:
        for tr in _hoja_y_arco(p):
            add(tr, "ARQ-VANOS")
    for g in interp.lineas_vanos:
        for a in _coords(g):
            add(a, "ARQ-VANOS", g.geom_type == "Polygon")
    for v in interp.vacios:
        add(_coords(v)[0], "ARQ-REFERENCIA", True)
    for g in interp.escaleras:
        for a in _coords(g):
            add(a, "ARQ-ESCALERAS", g.geom_type == "Polygon")
    if incluir_aparatos:
        for g in interp.aparatos_geom:
            for a in _coords(g, 0.01):
                add(a, "ARQ-APARATOS", g.geom_type == "Polygon")
    proyecto.arquitectura += trazos

    existentes = {r.id for r in proyecto.recintos}
    mapa = {}
    for r in interp.recintos:
        rid = r.id if r.id not in existentes else proyecto.siguiente_id("R", "recintos")
        mapa[r.id] = rid
        contorno = [(round(x, 4), round(y, 4)) for x, y in r.poligono.exterior.coords[:-1]]
        proyecto.recintos.append(Recinto(id=rid, nombre=r.nombre, uso=r.uso, nivel=nivel, contorno=contorno,
                                         unidad=r.unidad))
        existentes.add(rid)
    return {"recintos": len(interp.recintos), "trazos_arquitectura": len(trazos), "ids": mapa}


def guardar_reporte(rep: dict, ruta: str | Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta
