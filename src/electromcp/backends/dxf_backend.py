"""Backend DXF con ezdxf: genera un archivo .dxf sin necesidad de AutoCAD."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

import ezdxf
from ezdxf.enums import TextEntityAlignment

from ..layers import Capa
from ..symbols import Circulo, Linea, Polilinea, Simbolo, Texto, etiquetas
from .base import P2, P3, Backend

ESTILO_TEXTO = "ELECTRO"


class DXFBackend(Backend):
    nombre = "dxf"

    def __init__(self, ruta_salida: str | Path, version: str = "R2018"):
        self.ruta = Path(ruta_salida)
        self.doc = ezdxf.new(version, setup=True, units=ezdxf.units.M)
        self.doc.header["$INSUNITS"] = 6  # metros
        self.doc.header["$MEASUREMENT"] = 1  # métrico
        self.doc.header["$LTSCALE"] = 1.0
        self.msp = self.doc.modelspace()
        self._bloques: set[str] = set()

    # ------------------------------------------------------------ preparación
    def preparar(self, capas: Iterable[Capa], tipos_linea: dict) -> None:
        for nombre, (desc, patron) in tipos_linea.items():
            if nombre in self.doc.linetypes:
                self.doc.linetypes.remove(nombre)
            self.doc.linetypes.add(nombre, pattern=patron, description=desc)
        for c in capas:
            if c.nombre in self.doc.layers:
                capa = self.doc.layers.get(c.nombre)
            else:
                capa = self.doc.layers.add(c.nombre)
            capa.color = c.color
            capa.dxf.linetype = c.tipo_linea
            capa.dxf.lineweight = c.grosor
            capa.dxf.plot = 1 if c.imprimible else 0
            capa.description = c.descripcion
        if ESTILO_TEXTO not in self.doc.styles:
            self.doc.styles.add(ESTILO_TEXTO, font="arial.ttf")

    def definir_bloque(self, s: Simbolo) -> None:
        if s.clave in self._bloques or s.clave in self.doc.blocks:
            self._bloques.add(s.clave)
            return
        blk = self.doc.blocks.new(name=s.clave, dxfattribs={"description": s.descripcion})
        attr = {"layer": "0", "color": s.color}
        for p in s.primitivas:
            if isinstance(p, Circulo):
                if p.relleno:
                    h = blk.add_hatch(color=s.color, dxfattribs={"layer": "0"})
                    h.paths.add_edge_path().add_arc(p.centro, p.radio, 0, 360)
                else:
                    blk.add_circle(p.centro, p.radio, dxfattribs=attr)
            elif isinstance(p, Linea):
                blk.add_line(p.p1, p.p2, dxfattribs=attr)
            elif isinstance(p, Polilinea):
                blk.add_lwpolyline(p.puntos, close=p.cerrada, dxfattribs=attr)
                if p.relleno:
                    h = blk.add_hatch(color=s.color, dxfattribs={"layer": "0"})
                    h.paths.add_polyline_path(p.puntos, is_closed=True)
        for tag, p in etiquetas(s):
            a = blk.add_attdef(tag, text=p.texto, dxfattribs={
                "height": p.altura, "layer": "0", "color": s.color, "style": ESTILO_TEXTO, "flags": 0})
            a.set_placement(p.posicion, align=TextEntityAlignment.MIDDLE_CENTER
                            if p.alineacion == "centro" else TextEntityAlignment.MIDDLE_LEFT)
        for i, tag in enumerate(s.atributos):
            blk.add_attdef(tag, insert=(0.30, 0.18 - 0.14 * i), text="",
                           dxfattribs={"height": 0.09, "layer": "0", "color": 7, "style": ESTILO_TEXTO})
        self._bloques.add(s.clave)

    # ------------------------------------------------------------ entidades
    def insertar_bloque(self, clave, pos, rot_grados, capa, atributos=None, escala=1.0):
        ref = self.msp.add_blockref(clave, pos, dxfattribs={
            "layer": capa, "rotation": rot_grados, "xscale": escala, "yscale": escala})
        valores = {d.dxf.tag: d.dxf.text for d in self.doc.blocks[clave].attdefs()}
        valores.update(atributos or {})
        ref.add_auto_attribs(valores)
        for a in ref.attribs:  # textos siempre legibles (horizontales)
            a.dxf.rotation = 0
            if not a.dxf.tag.startswith("ETQ"):
                a.dxf.layer = "E-CIRCUITOS"

    def polilinea(self, puntos, capa, cerrada=False, color=None, ancho=0.0):
        attr = {"layer": capa}
        if color is not None:
            attr["color"] = color
        if ancho:
            attr["const_width"] = ancho
        self.msp.add_lwpolyline(puntos, close=cerrada, dxfattribs=attr)

    def relleno_solido(self, puntos, capa, color=None):
        h = self.msp.add_hatch(color=color if color is not None else 256, dxfattribs={"layer": capa})
        h.paths.add_polyline_path(puntos, is_closed=True)

    def circulo(self, centro, radio, capa, color=None):
        attr = {"layer": capa}
        if color is not None:
            attr["color"] = color
        self.msp.add_circle(centro, radio, dxfattribs=attr)

    def texto(self, txt, pos, altura, capa, centrado=False, rot_grados=0.0, color=None):
        attr = {"layer": capa, "style": ESTILO_TEXTO, "rotation": rot_grados}
        if color is not None:
            attr["color"] = color
        t = self.msp.add_text(txt, height=altura, dxfattribs=attr)
        t.set_placement(pos, align=TextEntityAlignment.MIDDLE_CENTER if centrado
                        else TextEntityAlignment.MIDDLE_LEFT)

    def polilinea_3d(self, puntos: list[P3], capa, color=None):
        attr = {"layer": capa}
        if color is not None:
            attr["color"] = color
        self.msp.add_polyline3d(puntos, dxfattribs=attr)

    def finalizar(self) -> str:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.doc.set_modelspace_vport(height=40, center=(20, 10))
        self.doc.saveas(self.ruta)
        return str(self.ruta)
