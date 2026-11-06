"""Backend en vivo: dibuja directamente en el AutoCAD abierto (Windows, COM/ActiveX).

Requisitos: Windows, AutoCAD 2026 completo (AutoCAD LT no expone automatización),
y el paquete pywin32. Se conecta a la sesión de AutoCAD que esté abierta (o la
inicia) y dibuja en el dibujo activo, o en uno nuevo si se pide.

Notas técnicas:
* Los puntos se pasan como VARIANT de dobles (VT_ARRAY | VT_R8), que es lo que
  espera la API ActiveX de AutoCAD.
* AutoCAD rechaza llamadas mientras está ocupado ("Call was rejected by callee",
  RPC_E_CALL_REJECTED). Todas las llamadas pasan por `_reintentar`.
* Los ángulos de la API van en radianes.
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Iterable, Optional

from ..layers import Capa
from ..symbols import Circulo, Linea, Polilinea, Simbolo, Texto, etiquetas
from .base import P2, P3, Backend

try:  # pragma: no cover - solo en Windows
    import pythoncom
    import win32com.client as win32
except ImportError:  # pragma: no cover
    pythoncom = None
    win32 = None

RPC_E_CALL_REJECTED = -2147418111
RPC_E_SERVERCALL_RETRYLATER = -2147417846
AC_ALIGN_MIDDLE_CENTER = 10
AC_ALIGN_MIDDLE_LEFT = 9
AC_ZOOM_EXTENTS = 1
ESTILO_TEXTO = "ELECTRO"


def _reintentar(fn: Callable[[], Any], intentos: int = 40, espera: float = 0.25) -> Any:
    for i in range(intentos):
        try:
            return fn()
        except Exception as exc:  # pywintypes.com_error
            codigo = getattr(exc, "hresult", None) or (exc.args[0] if exc.args else None)
            if codigo in (RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER) and i < intentos - 1:
                time.sleep(espera)
                continue
            raise


class AutoCADBackend(Backend):
    nombre = "autocad"

    def __init__(self, nuevo_dibujo: bool = False, plantilla: str = "acadiso.dwt",
                 visible: bool = True):
        if win32 is None:
            raise RuntimeError(
                "El modo AutoCAD en vivo requiere Windows con pywin32 instalado "
                "(pip install pywin32). Use el modo DXF en otros sistemas.")
        pythoncom.CoInitialize()
        try:
            self.acad = win32.GetActiveObject("AutoCAD.Application")
        except Exception:
            self.acad = win32.Dispatch("AutoCAD.Application")
        _reintentar(lambda: setattr(self.acad, "Visible", visible))
        if nuevo_dibujo or _reintentar(lambda: self.acad.Documents.Count) == 0:
            self.doc = _reintentar(lambda: self.acad.Documents.Add(plantilla))
        else:
            self.doc = _reintentar(lambda: self.acad.ActiveDocument)
        self.ms = _reintentar(lambda: self.doc.ModelSpace)
        self._bloques: set[str] = set()

    # ------------------------------------------------------------ utilidades COM
    @staticmethod
    def _pt(x: float, y: float, z: float = 0.0):
        return win32.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (float(x), float(y), float(z)))

    @staticmethod
    def _plano(puntos: Iterable[P2]):
        flat: list[float] = []
        for x, y in puntos:
            flat += [float(x), float(y)]
        return win32.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat)

    @staticmethod
    def _plano3d(puntos: Iterable[P3]):
        flat: list[float] = []
        for x, y, z in puntos:
            flat += [float(x), float(y), float(z)]
        return win32.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat)

    def _props(self, ent, capa: str, color: Optional[int]) -> None:
        _reintentar(lambda: setattr(ent, "Layer", capa))
        if color is not None:
            _reintentar(lambda: setattr(ent, "Color", color))

    def _hatch(self, contenedor, contorno_ent, capa: str, color: Optional[int]) -> None:
        h = _reintentar(lambda: contenedor.AddHatch(0, "SOLID", True))
        lazo = win32.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, [contorno_ent])
        _reintentar(lambda: h.AppendOuterLoop(lazo))
        _reintentar(h.Evaluate)
        self._props(h, capa, color)

    # ------------------------------------------------------------ preparación
    def preparar(self, capas: Iterable[Capa], tipos_linea: dict) -> None:
        self.doc.SetVariable("INSUNITS", 6)  # metros
        self.doc.SetVariable("LTSCALE", 0.05)  # patrones acadiso (mm) en dibujo en metros
        self.doc.SetVariable("PSLTSCALE", 0)
        cargados = {lt.Name.upper() for lt in self.doc.Linetypes}
        for nombre in tipos_linea:
            if nombre.upper() not in cargados:
                try:
                    _reintentar(lambda n=nombre: self.doc.Linetypes.Load(n, "acadiso.lin"))
                except Exception:
                    pass  # si no existe se queda en Continuous
        try:
            est = self.doc.TextStyles.Add(ESTILO_TEXTO)
            est.SetFont("Arial", False, False, 0, 34)
        except Exception:
            pass
        for c in capas:
            capa = _reintentar(lambda n=c.nombre: self.doc.Layers.Add(n))
            _reintentar(lambda: setattr(capa, "Color", c.color))
            try:
                _reintentar(lambda: setattr(capa, "Linetype", c.tipo_linea))
            except Exception:
                pass
            _reintentar(lambda: setattr(capa, "Lineweight", c.grosor))
            _reintentar(lambda: setattr(capa, "Plottable", c.imprimible))
            try:
                capa.Description = c.descripcion
            except Exception:
                pass
        self.doc.ActiveTextStyle = self.doc.TextStyles.Item(ESTILO_TEXTO)

    def definir_bloque(self, s: Simbolo) -> None:
        if s.clave in self._bloques:
            return
        try:
            self.doc.Blocks.Item(s.clave)
            self._bloques.add(s.clave)
            return  # ya existe en el dibujo: se respeta (el usuario puede haberlo personalizado)
        except Exception:
            pass
        blk = _reintentar(lambda: self.doc.Blocks.Add(self._pt(0, 0), s.clave))
        for p in s.primitivas:
            if isinstance(p, Circulo):
                e = _reintentar(lambda: blk.AddCircle(self._pt(*p.centro), p.radio))
                self._props(e, "0", s.color)
                if p.relleno:
                    self._hatch(blk, e, "0", s.color)
            elif isinstance(p, Linea):
                e = _reintentar(lambda: blk.AddLine(self._pt(*p.p1), self._pt(*p.p2)))
                self._props(e, "0", s.color)
            elif isinstance(p, Polilinea):
                e = _reintentar(lambda: blk.AddLightWeightPolyline(self._plano(p.puntos)))
                e.Closed = p.cerrada or p.relleno
                self._props(e, "0", s.color)
                if p.relleno:
                    self._hatch(blk, e, "0", s.color)
        for tag, p in etiquetas(s):
            # Atributo con valor por defecto = la etiqueta; se reorienta a 0° al insertar
            e = _reintentar(lambda: blk.AddAttribute(p.altura, 0, tag, self._pt(*p.posicion), tag, p.texto))
            e.StyleName = ESTILO_TEXTO
            e.Alignment = AC_ALIGN_MIDDLE_CENTER if p.alineacion == "centro" else AC_ALIGN_MIDDLE_LEFT
            e.TextAlignmentPoint = self._pt(*p.posicion)
            self._props(e, "0", s.color)
        for i, tag in enumerate(s.atributos):
            a = _reintentar(lambda: blk.AddAttribute(0.09, 0, tag, self._pt(0.30, 0.18 - 0.14 * i), tag, ""))
            a.StyleName = ESTILO_TEXTO
            self._props(a, "0", 7)
        self._bloques.add(s.clave)

    # ------------------------------------------------------------ entidades
    def insertar_bloque(self, clave, pos, rot_grados, capa, atributos=None, escala=1.0):
        ref = _reintentar(lambda: self.ms.InsertBlock(self._pt(*pos), clave, escala, escala, escala,
                                                       math.radians(rot_grados)))
        self._props(ref, capa, None)
        if _reintentar(lambda: ref.HasAttributes):
            for att in _reintentar(ref.GetAttributes):
                att.Rotation = 0.0  # textos siempre horizontales
                if atributos and att.TagString in atributos:
                    att.TextString = str(atributos[att.TagString])
                if not att.TagString.startswith("ETQ"):
                    att.Layer = "E-CIRCUITOS"

    def polilinea(self, puntos, capa, cerrada=False, color=None, ancho=0.0):
        e = _reintentar(lambda: self.ms.AddLightWeightPolyline(self._plano(puntos)))
        e.Closed = cerrada
        if ancho:
            e.ConstantWidth = ancho
        self._props(e, capa, color)

    def relleno_solido(self, puntos, capa, color=None):
        borde = _reintentar(lambda: self.ms.AddLightWeightPolyline(self._plano(puntos)))
        borde.Closed = True
        self._props(borde, capa, color)
        self._hatch(self.ms, borde, capa, color)

    def circulo(self, centro, radio, capa, color=None):
        e = _reintentar(lambda: self.ms.AddCircle(self._pt(*centro), radio))
        self._props(e, capa, color)

    def texto(self, txt, pos, altura, capa, centrado=False, rot_grados=0.0, color=None):
        e = _reintentar(lambda: self.ms.AddText(txt, self._pt(*pos), altura))
        e.StyleName = ESTILO_TEXTO
        e.Alignment = AC_ALIGN_MIDDLE_CENTER if centrado else AC_ALIGN_MIDDLE_LEFT
        e.TextAlignmentPoint = self._pt(*pos)
        if rot_grados:
            e.Rotation = math.radians(rot_grados)
        self._props(e, capa, color)

    def polilinea_3d(self, puntos, capa, color=None):
        e = _reintentar(lambda: self.ms.Add3DPoly(self._plano3d(puntos)))
        self._props(e, capa, color)

    def finalizar(self) -> str:
        _reintentar(lambda: self.acad.ZoomExtents())
        _reintentar(lambda: self.doc.Regen(1))  # acAllViewports
        return f"Dibujado en AutoCAD: {self.doc.Name}"
