"""Clasificación de las capas del plano arquitectónico.

Cada capa recibe una categoría por dos vías:

1. **Por nombre**, con palabras clave en español e inglés (MUROS, A-WALL, PUERTAS, COTAS...).
2. **Por geometría**, cuando el nombre no dice nada (capas tipo ``_F5``, ``252``, ``0``):
   se mide qué tan "delgadas y alargadas" son sus figuras cerradas (muros), si son
   cuadradas y pequeñas (columnas), si son rellenos sólidos (achurado de muro), etc.

El usuario siempre puede corregir el resultado con un mapa ``{capa: categoría}``.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from .lectura import Elemento


class Categoria(str, Enum):
    MUROS = "muros"
    MUROS_BAJOS = "muros_bajos"  # antepechos, barandas, muros a media altura
    COLUMNAS = "columnas"
    PUERTAS = "puertas"
    VENTANAS = "ventanas"
    APARATOS = "aparatos"  # sanitarios, mesones, estufas, lavaderos: útiles para el diseño eléctrico
    MOBILIARIO = "mobiliario"  # muebles sueltos: se eliminan
    ESCALERAS = "escaleras"
    COTAS = "cotas"
    TEXTOS = "textos"
    EJES = "ejes"
    ACHURADOS = "achurados"
    PROYECCIONES = "proyecciones"
    OTROS = "otros"
    IGNORAR = "ignorar"


# Orden importante: la primera regla que coincide gana.
_REGLAS: list[tuple[Categoria, tuple[str, ...]]] = [
    (Categoria.IGNORAR, ("defpoints", "viewport", "ventanagrafica")),
    (Categoria.EJES, ("eje", "grid", "axis", "s-grid")),
    (Categoria.COTAS, ("cota", "acot", "dim", "a-anno-dims")),
    (Categoria.ESCALERAS, ("escal", "stair", "rampa", "peldan")),
    (Categoria.MUROS_BAJOS, ("muro bajo", "muros bajos", "muro_bajo", "antepecho", "baranda", "pasamano",
                             "railing", "a-wall-prht")),
    (Categoria.ACHURADOS, ("blanco", "mascara", "wipeout", "hatch", "achur", "textura", "relleno", "pattern", "lineas de piso",
                           "piso", "a-flor-patt", "enchape")),
    (Categoria.MUROS, ("muro", "wall", "mamposter", "ladrillo", "drywall", "tabique", "a-wall", "pared",
                       "fachada")),
    (Categoria.COLUMNAS, ("column", "pilar", "estructura", "s-cols", "a-cols", "concreto")),
    (Categoria.PUERTAS, ("puerta", "door", "a-door")),
    (Categoria.VENTANAS, ("ventan", "window", "vidrio", "glaz", "a-glaz", "cancel", "marco")),
    (Categoria.APARATOS, ("bano", "sanitar", "wc", "lavamanos", "ducha", "plumb", "a-flor-pfix", "cocina",
                          "kitchen", "electrodom", "lavadero", "meson", "aparato", "equipo")),
    (Categoria.MOBILIARIO, ("mueble", "furn", "mobili", "a-furn", "decor", "vegeta", "planta", "arbol",
                            "jardin", "persona", "carro", "vehic")),
    (Categoria.PROYECCIONES, ("proyecc", "hidden", "oculta", "cubierta", "voladizo", "alero", "vacio",
                              "cielo")),
    (Categoria.TEXTOS, ("texto", "text", "anot", "nombre", "rotulo", "title", "area", "espacio", "nota",
                        "simbolo", "a-anno", "label")),
]

# Rangos geométricos de muro (m)
ESPESOR_MURO_MIN = 0.06
ESPESOR_MURO_MAX = 0.40
ESBELTEZ_MIN = 5.0  # longitud / espesor


def normalizar(nombre: str) -> str:
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    return s.replace("_", " ").replace("-", "-").strip()


def por_nombre(nombre: str) -> Optional[Categoria]:
    n = normalizar(nombre)
    for cat, claves in _REGLAS:
        for k in claves:
            if k == "dim" and not (n.startswith("dim") or " dim" in n or "-dim" in n):
                continue  # evita falsos positivos como "dimmer"
            if k == "wc" and not (n == "wc" or " wc" in n or n.startswith("wc")):
                continue
            if k in n:
                return cat
    return None


def espesor_y_largo(g: BaseGeometry) -> tuple[float, float]:
    """Espesor equivalente (2A/P) y largo (P/2) de un polígono: sirve para cualquier forma delgada."""
    if g.length <= 0:
        return 0.0, 0.0
    return 2.0 * g.area / g.length, g.length / 2.0


def es_muro(g: BaseGeometry) -> bool:
    if g.geom_type != "Polygon" or g.area < 0.01:
        return False
    t, largo = espesor_y_largo(g)
    return ESPESOR_MURO_MIN <= t <= ESPESOR_MURO_MAX and largo / max(t, 1e-9) >= ESBELTEZ_MIN


def es_columna(g: BaseGeometry) -> bool:
    if g.geom_type != "Polygon":
        return False
    r = g.minimum_rotated_rectangle
    if r.geom_type != "Polygon":
        return False
    c = list(r.exterior.coords)
    a = LineString(c[0:2]).length
    b = LineString(c[1:3]).length
    lo, hi = sorted((a, b))
    return 0.15 <= lo <= 1.0 and hi <= 1.5 and hi / max(lo, 1e-9) <= 2.2 and g.area >= 0.6 * r.area


@dataclass
class InfoCapa:
    nombre: str
    categoria: Categoria
    origen: str  # "nombre", "geometria", "usuario", "texto"
    n_entidades: int = 0
    tipos: dict[str, int] = field(default_factory=dict)
    detalle: str = ""

    def resumen(self) -> dict:
        return {"capa": self.nombre, "categoria": self.categoria.value, "criterio": self.origen,
                "entidades": self.n_entidades, "tipos": self.tipos, "detalle": self.detalle}


def clasificar_capas(elementos: Iterable[Elemento],
                     mapa_usuario: Optional[dict[str, str]] = None) -> dict[str, InfoCapa]:
    mapa_usuario = {k: Categoria(v) for k, v in (mapa_usuario or {}).items()}
    por_capa: dict[str, list[Elemento]] = defaultdict(list)
    for el in elementos:
        por_capa[el.capa].append(el)

    info: dict[str, InfoCapa] = {}
    for capa, els in por_capa.items():
        tipos: dict[str, int] = defaultdict(int)
        for el in els:
            tipos[el.tipo] += 1
        tipos = dict(sorted(tipos.items(), key=lambda kv: -kv[1]))
        n = len(els)
        if capa in mapa_usuario:
            info[capa] = InfoCapa(capa, mapa_usuario[capa], "usuario", n, tipos)
            continue
        cat = por_nombre(capa)
        if cat is not None:
            info[capa] = InfoCapa(capa, cat, "nombre", n, tipos)
            continue
        info[capa] = _por_geometria(capa, els, tipos)
    return info


def _por_geometria(capa: str, els: list[Elemento], tipos: dict[str, int]) -> InfoCapa:
    n = len(els)
    if tipos.get("DIMENSION", 0) >= 0.5 * n:
        return InfoCapa(capa, Categoria.COTAS, "geometria", n, tipos, "mayoría de cotas")
    if sum(tipos.get(t, 0) for t in ("MTEXT", "TEXT", "ATTRIB")) >= 0.7 * n:
        return InfoCapa(capa, Categoria.TEXTOS, "geometria", n, tipos, "mayoría de textos")

    area = area_muro = largo_muro = 0.0
    cerrados = columnas = 0
    hatch_patron = 0
    for el in els:
        if el.tipo == "HATCH" and not el.relleno_solido:
            hatch_patron += 1
            continue
        for g in el.geom:
            if g.geom_type != "Polygon" or g.area < 1e-3:
                continue
            cerrados += 1
            area += g.area
            if es_muro(g):
                area_muro += g.area
                largo_muro += espesor_y_largo(g)[1]
            elif es_columna(g):
                columnas += 1
    if hatch_patron >= 0.7 * n:
        return InfoCapa(capa, Categoria.ACHURADOS, "geometria", n, tipos, "rellenos con patrón")
    if area > 0 and area_muro / area >= 0.6 and largo_muro >= 8.0:
        return InfoCapa(capa, Categoria.MUROS, "geometria", n, tipos,
                        f"{area_muro / area:.0%} del área en figuras delgadas; {largo_muro:.0f} m de muro")
    if cerrados >= 3 and columnas >= 0.7 * cerrados:
        return InfoCapa(capa, Categoria.COLUMNAS, "geometria", n, tipos,
                        f"{columnas} figuras cuadradas pequeñas")
    return InfoCapa(capa, Categoria.OTROS, "geometria", n, tipos)
