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
from typing import Optional

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


class Recinto(BaseModel):
    id: str
    nombre: str
    uso: UsoRecinto = UsoRecinto.OTRO
    nivel: str = "PISO 1"
    contorno: list[Punto] = Field(min_length=3)
    altura_cielo: float = 2.40

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


class Tablero(BaseModel):
    id: str  # "TD-1"
    nombre: str = "Tablero de distribución"
    posicion: Punto
    nivel: str = "PISO 1"
    rotacion: float = 0.0
    sistema: str = "Bifásico trifilar 120/240 V"
    n_circuitos: int = 12
    altura: float = 1.60


class Tuberia(BaseModel):
    id: str
    ruta: list[Punto] = Field(min_length=2)
    nivel: str = "PISO 1"
    tipo: TipoTuberia = TipoTuberia.MURO
    circuitos: list[str] = Field(default_factory=list)
    diametro: str = "1/2\""
    elevacion: Optional[float] = None  # m, para la vista 3D


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

    @model_validator(mode="after")
    def _ids_unicos(self) -> "Proyecto":
        for nombre in ("recintos", "salidas", "circuitos", "tableros", "tuberias"):
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
