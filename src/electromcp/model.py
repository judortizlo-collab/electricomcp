"""Modelo de datos del proyecto eléctrico.

Todo el diseño vive en este modelo, independiente de AutoCAD. Los "backends"
(DXF o AutoCAD en vivo) solo traducen el modelo a entidades de dibujo, así el
mismo proyecto se puede dibujar, recalcular o exportar cuantas veces se quiera.

Unidades: metros en planta (1 unidad de dibujo = 1 m), alturas en metros
sobre el nivel de piso terminado (NPT).
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Punto = tuple[float, float]


class UsoRecinto(str, Enum):
    """Uso del recinto. Define las reglas NTC 2050 / RETILAP aplicables."""

    SALA = "sala"
    COMEDOR = "comedor"
    SALA_COMEDOR = "sala_comedor"
    COCINA = "cocina"
    BANO = "bano"
    ALCOBA = "alcoba"
    ESTUDIO = "estudio"
    ROPAS = "ropas"
    CIRCULACION = "circulacion"
    VESTIER = "vestier"
    GARAJE = "garaje"
    TERRAZA = "terraza"
    BALCON = "balcon"
    EXTERIOR = "exterior"
    CUARTO_TECNICO = "cuarto_tecnico"
    PATIO = "patio"
    DUCTO = "ducto"
    ESCALERA = "escalera"
    OTRO = "otro"


class TipoTuberia(str, Enum):
    MURO = "muro"
    PISO = "piso"
    TECHO = "techo"
    COMUNICACIONES = "comunicaciones"
    ACOMETIDA = "acometida"


class TipoCircuito(str, Enum):
    ILUMINACION = "iluminacion"
    TOMAS = "tomas"
    PEQUENOS_ARTEFACTOS = "pequenos_artefactos"
    BANO = "bano"
    LAVANDERIA = "lavanderia"
    ESPECIAL = "especial"
    FUERZA = "fuerza"
    AIRE = "aire"


class Zona(BaseModel):
    """Subzona de un espacio abierto (p. ej. la cocina dentro de 'Sala - Comedor - Cocina')."""

    nombre: str
    uso: UsoRecinto
    contorno: list[Punto] = Field(min_length=3)


def etiqueta_circuito(cid: Optional[str]) -> str:
    """'TD-01.C-03' -> 'C-03' (el prefijo del tablero solo hace único el id dentro del proyecto)."""
    return (cid or "").rsplit(".", 1)[-1]


class Recinto(BaseModel):
    id: str
    nombre: str
    uso: UsoRecinto = UsoRecinto.OTRO
    nivel: str = "PISO 1"
    contorno: list[Punto] = Field(min_length=3)
    altura_cielo: float = 2.40
    unidad: Optional[str] = None  # apartamento / local al que pertenece (paso 2)
    comun: bool = False  # zona común (circulación, escalera, punto fijo)
    vacio: bool = False  # patio de luz / vacío: no lleva salidas
    notas: list[str] = Field(default_factory=list)  # ventilacion_mecanica, ruta_evacuacion...
    zonas: list[Zona] = Field(default_factory=list)

    @property
    def area(self) -> float:
        pts = self.contorno
        s = 0.0
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            s += x1 * y2 - x2 * y1
        return abs(s) / 2.0

    @property
    def perimetro(self) -> float:
        pts = self.contorno
        return sum(
            ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])
        )

    @property
    def centroide(self) -> Punto:
        pts = self.contorno
        a = 0.0
        cx = cy = 0.0
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
            f = x1 * y2 - x2 * y1
            a += f
            cx += (x1 + x2) * f
            cy += (y1 + y2) * f
        if abs(a) < 1e-9:
            n = len(pts)
            return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
        a *= 0.5
        return (cx / (6 * a), cy / (6 * a))


class Vano(BaseModel):
    """Puerta o ventana. p1-p2 es el eje del vano sobre el muro.

    En puertas, p1 = bisagra y p2 = extremo de la hoja cerrada (lado de la chapa).
    """

    id: str
    tipo: Literal["puerta", "ventana"] = "puerta"
    p1: Punto
    p2: Punto
    nivel: str = "PISO 1"
    recintos: list[str] = Field(default_factory=list)  # ids a cada lado ("EXT" = exterior)
    abre_hacia: Optional[str] = None  # recinto hacia el que barre la hoja

    @property
    def ancho(self) -> float:
        return ((self.p2[0] - self.p1[0]) ** 2 + (self.p2[1] - self.p1[1]) ** 2) ** 0.5


class Aparato(BaseModel):
    """Aparato o equipo fijo del plano arquitectónico (inodoro, lavaplatos, estufa, nevera...)."""

    id: str
    tipo: str
    posicion: Punto
    nivel: str = "PISO 1"
    recinto: Optional[str] = None
    tamano: Optional[tuple[float, float]] = None  # ancho x fondo aproximados (m)


class Salida(BaseModel):
    """Una salida eléctrica: toma, luminaria, interruptor, salida especial..."""

    id: str
    simbolo: str  # clave de la biblioteca de símbolos (symbols.SIMBOLOS)
    posicion: Punto
    nivel: str = "PISO 1"
    rotacion: float = 0.0  # grados
    altura: Optional[float] = None  # m sobre NPT; None = altura por defecto del símbolo
    circuito: Optional[str] = None  # p. ej. "C-03"
    potencia_va: Optional[float] = None
    recinto: Optional[str] = None
    nota: Optional[str] = None
    control: Optional[str] = None  # letra de encendido (a, b, c) que une interruptor y luminarias
    auto: bool = False  # True = ubicada por el motor de diseño (se reemplaza al rediseñar)


class Circuito(BaseModel):
    id: str  # "C-01"
    tablero: str
    tipo: TipoCircuito
    descripcion: str = ""
    tension_v: float = 120.0
    polos: int = 1
    proteccion_a: float = 20.0
    conductor: str = "3x12 AWG Cu THHN/THWN-2"
    tuberia: str = "PVC 1/2\""
    fase: str = ""  # "A", "B" o "AB"
    calibre_awg: str = "12"
    longitud_m: Optional[float] = None  # recorrido hasta la salida más lejana (regulación)
    unidad: Optional[str] = None
    auto: bool = False


class Tablero(BaseModel):
    id: str  # "TD-1"
    nombre: str = "Tablero de distribución"
    posicion: Punto
    nivel: str = "PISO 1"
    rotacion: float = 0.0
    sistema: str = "Bifásico trifilar 120/240 V"
    n_circuitos: int = 12
    altura: float = 1.60
    unidad: Optional[str] = None  # apartamento / local que alimenta
    alimentado_desde: Optional[str] = None  # medidor o tablero aguas arriba
    proteccion_general_a: Optional[float] = None
    alimentador: str = ""
    longitud_alimentador_m: Optional[float] = None
    auto: bool = False


class Tuberia(BaseModel):
    id: str
    ruta: list[Punto] = Field(min_length=2)
    nivel: str = "PISO 1"
    tipo: TipoTuberia = TipoTuberia.MURO
    circuitos: list[str] = Field(default_factory=list)
    diametro: str = "1/2\""
    elevacion: Optional[float] = None  # m, para la vista 3D
    conductores: str = ""  # p. ej. "4#12 + 1#12T"
    unidad: Optional[str] = None
    auto: bool = False


class TrazoArq(BaseModel):
    """Geometría arquitectónica ya depurada (muros, vanos, referencias)."""

    capa: str = "ARQ-MUROS"
    puntos: list[Punto] = Field(min_length=2)
    cerrado: bool = False
    nivel: str = "PISO 1"


class Rotulo(BaseModel):
    """Datos del rótulo (cajetín) del plano."""

    empresa: str = ""
    contacto: str = ""
    proyecto: str = ""
    direccion: str = ""
    municipio: str = ""
    tipo_proyecto: str = "RESIDENCIAL"
    contiene: str = ""
    constructor: str = ""
    disenador: str = ""
    matricula: str = ""
    dibujante: str = ""
    fecha: str = ""
    escala: str = "1/50"
    plano_n: str = "01 DE 01"


class Proyecto(BaseModel):
    nombre: str
    rotulo: Rotulo = Field(default_factory=Rotulo)
    niveles: list[str] = Field(default_factory=lambda: ["PISO 1"])
    recintos: list[Recinto] = Field(default_factory=list)
    salidas: list[Salida] = Field(default_factory=list)
    circuitos: list[Circuito] = Field(default_factory=list)
    tableros: list[Tablero] = Field(default_factory=list)
    tuberias: list[Tuberia] = Field(default_factory=list)
    arquitectura: list[TrazoArq] = Field(default_factory=list)
    vanos: list[Vano] = Field(default_factory=list)
    aparatos: list[Aparato] = Field(default_factory=list)
    parametros_diseno: dict = Field(default_factory=dict)  # criterios usados por el motor (paso 3)

    @model_validator(mode="after")
    def _ids_unicos(self) -> "Proyecto":
        for nombre in ("recintos", "salidas", "circuitos", "tableros", "tuberias", "vanos", "aparatos"):
            ids = [e.id for e in getattr(self, nombre)]
            dup = {i for i in ids if ids.count(i) > 1}
            if dup:
                raise ValueError(f"IDs duplicados en {nombre}: {sorted(dup)}")
        return self

    # ---------- utilidades ----------
    def siguiente_id(self, prefijo: str, coleccion: str) -> str:
        existentes = {e.id for e in getattr(self, coleccion)}
        n = 1
        while f"{prefijo}{n:03d}" in existentes:
            n += 1
        return f"{prefijo}{n:03d}"

    def recinto(self, rid: str) -> Recinto:
        for r in self.recintos:
            if r.id == rid:
                return r
        raise KeyError(f"No existe el recinto {rid!r}")

    def conteo_simbolos(self, nivel: Optional[str] = None) -> dict[str, int]:
        cuenta: dict[str, int] = {}
        for s in self.salidas:
            if nivel is None or s.nivel == nivel:
                cuenta[s.simbolo] = cuenta.get(s.simbolo, 0) + 1
        for t in self.tableros:
            if nivel is None or t.nivel == nivel:
                cuenta["TABLERO"] = cuenta.get("TABLERO", 0) + 1
        return cuenta

    def guardar(self, ruta: str | Path) -> Path:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return ruta

    @classmethod
    def cargar(cls, ruta: str | Path) -> "Proyecto":
        return cls.model_validate(json.loads(Path(ruta).read_text(encoding="utf-8")))
