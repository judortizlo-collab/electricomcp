"""Servidor MCP de ElectroMCP.

Expone herramientas para que Claude construya el proyecto eléctrico paso a paso
y lo dibuje, ya sea generando un DXF o directamente en el AutoCAD abierto.

Los proyectos se guardan como JSON en la carpeta de trabajo
(variable de entorno ELECTROMCP_DIR, por defecto ~/ElectroMCP).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

try:  # SDK de MCP 2.x
    from mcp.server.mcpserver import MCPServer as _Servidor
except ImportError:  # SDK de MCP 1.x
    from mcp.server.fastmcp import FastMCP as _Servidor

from .backends.dxf_backend import DXFBackend
from .model import (Circuito, Proyecto, Recinto, Rotulo, Salida, Tablero, TipoCircuito,
                    TipoTuberia, Tuberia, UsoRecinto)
from .render import Renderizador
from .symbols import SIMBOLOS

mcp = _Servidor(
    "electromcp",
    instructions=(
        "Herramientas de diseño eléctrico residencial/comercial para Colombia (NTC 2050, RETIE). "
        "Unidades en metros; alturas sobre NPT. Flujo típico: crear_proyecto -> agregar_recinto -> "
        "agregar_tablero -> agregar_circuito -> agregar_salidas -> trazar_tuberia -> generar_dxf o "
        "dibujar_en_autocad. Use listar_simbolos para conocer las claves de símbolo. "
        "El diseño final debe ser revisado y firmado por un ingeniero electricista con matrícula."
    ),
)

CARPETA = Path(os.environ.get("ELECTROMCP_DIR", Path.home() / "ElectroMCP"))
_estado: dict[str, Optional[Proyecto]] = {"proyecto": None}


def _ruta_json(nombre: str) -> Path:
    seguro = "".join(c if c.isalnum() or c in "-_ " else "_" for c in nombre).strip().replace(" ", "_")
    return CARPETA / "proyectos" / f"{seguro}.json"


def _p() -> Proyecto:
    p = _estado["proyecto"]
    if p is None:
        raise ValueError("No hay proyecto abierto. Use crear_proyecto o abrir_proyecto.")
    return p


def _guardar() -> str:
    p = _p()
    # Validación completa (IDs únicos, referencias) antes de guardar
    Proyecto.model_validate(p.model_dump())
    return str(p.guardar(_ruta_json(p.nombre)))


def _resumen(p: Proyecto) -> dict:
    return {
        "nombre": p.nombre,
        "niveles": p.niveles,
        "recintos": [{"id": r.id, "nombre": r.nombre, "uso": r.uso.value, "nivel": r.nivel,
                      "area_m2": round(r.area, 2)} for r in p.recintos],
        "tableros": [t.id for t in p.tableros],
        "circuitos": [{"id": c.id, "tipo": c.tipo.value, "descripcion": c.descripcion} for c in p.circuitos],
        "salidas_por_simbolo": p.conteo_simbolos(),
        "n_tuberias": len(p.tuberias),
        "archivo": str(_ruta_json(p.nombre)),
    }


# ------------------------------------------------------------------ proyecto
@mcp.tool()
def crear_proyecto(nombre: str, niveles: list[str] = ["PISO 1"], empresa: str = "", contacto: str = "",
                   direccion: str = "", municipio: str = "", tipo_proyecto: str = "RESIDENCIAL",
                   constructor: str = "", disenador: str = "", matricula: str = "", dibujante: str = "",
                   fecha: str = "", escala: str = "1/50") -> dict:
    """Crea un proyecto nuevo y lo deja abierto. Los datos llenan el rótulo de los planos."""
    p = Proyecto(nombre=nombre, niveles=niveles, rotulo=Rotulo(
        empresa=empresa, contacto=contacto, proyecto=nombre, direccion=direccion, municipio=municipio,
        tipo_proyecto=tipo_proyecto, constructor=constructor, disenador=disenador, matricula=matricula,
        dibujante=dibujante, fecha=fecha, escala=escala))
    _estado["proyecto"] = p
    _guardar()
    return _resumen(p)


@mcp.tool()
def abrir_proyecto(nombre: str) -> dict:
    """Abre un proyecto guardado por su nombre."""
    _estado["proyecto"] = Proyecto.cargar(_ruta_json(nombre))
    return _resumen(_p())


@mcp.tool()
def listar_proyectos() -> list[str]:
    """Lista los proyectos guardados en la carpeta de trabajo."""
    d = CARPETA / "proyectos"
    return sorted(f.stem for f in d.glob("*.json")) if d.exists() else []


@mcp.tool()
def estado_proyecto() -> dict:
    """Resumen del proyecto abierto: recintos, circuitos, conteo de salidas."""
    return _resumen(_p())


# ------------------------------------------------------------------ elementos
@mcp.tool()
def agregar_recinto(nombre: str, contorno: list[tuple[float, float]], uso: UsoRecinto = UsoRecinto.OTRO,
                    nivel: str = "PISO 1", altura_cielo: float = 2.40, id: Optional[str] = None) -> dict:
    """Agrega un recinto (espacio) dado su contorno en metros, en orden de recorrido."""
    p = _p()
    r = Recinto(id=id or p.siguiente_id("R", "recintos"), nombre=nombre, uso=uso, nivel=nivel,
                contorno=contorno, altura_cielo=altura_cielo)
    p.recintos.append(r)
    _guardar()
    return {"id": r.id, "area_m2": round(r.area, 2), "perimetro_m": round(r.perimetro, 2)}


@mcp.tool()
def agregar_tablero(id: str, posicion: tuple[float, float], nivel: str = "PISO 1", rotacion: float = 0.0,
                    sistema: str = "Bifásico trifilar 120/240 V", n_circuitos: int = 12) -> dict:
    """Agrega un tablero de distribución (borde superior a 1,60 m)."""
    p = _p()
    p.tableros.append(Tablero(id=id, posicion=posicion, nivel=nivel, rotacion=rotacion,
                              sistema=sistema, n_circuitos=n_circuitos))
    _guardar()
    return {"ok": True, "tablero": id}


@mcp.tool()
def agregar_circuito(id: str, tablero: str, tipo: TipoCircuito, descripcion: str = "",
                     tension_v: float = 120.0, polos: int = 1, proteccion_a: float = 20.0,
                     conductor: str = "3x12 AWG Cu THHN/THWN-2", tuberia: str = "PVC 1/2\"") -> dict:
    """Agrega un circuito ramal al tablero indicado (p. ej. id='C-03')."""
    p = _p()
    if tablero not in {t.id for t in p.tableros}:
        raise ValueError(f"No existe el tablero {tablero!r}")
    p.circuitos.append(Circuito(id=id, tablero=tablero, tipo=tipo, descripcion=descripcion,
                                tension_v=tension_v, polos=polos, proteccion_a=proteccion_a,
                                conductor=conductor, tuberia=tuberia))
    _guardar()
    return {"ok": True, "circuito": id}


@mcp.tool()
def agregar_salidas(salidas: list[dict]) -> dict:
    """Agrega varias salidas de una vez.

    Cada salida: {"simbolo": "TOMA_DOBLE", "posicion": [x, y], "nivel": "PISO 1",
    "circuito": "C-03", "rotacion": 0, "altura": 0.30, "recinto": "R001"}.
    La rotación orienta el frente del símbolo (0° = mirando a +Y).
    """
    p = _p()
    ids = []
    for d in salidas:
        if d.get("simbolo") not in SIMBOLOS:
            raise ValueError(f"Símbolo desconocido {d.get('simbolo')!r}; use listar_simbolos")
        d = dict(d)
        d.setdefault("id", p.siguiente_id("S", "salidas"))
        sim = SIMBOLOS[d["simbolo"]]
        d.setdefault("altura", sim.altura_montaje)
        d.setdefault("potencia_va", sim.potencia_va)
        s = Salida.model_validate(d)
        p.salidas.append(s)
        ids.append(s.id)
    _guardar()
    return {"agregadas": len(ids), "ids": ids}


@mcp.tool()
def trazar_tuberia(ruta: list[tuple[float, float]], tipo: TipoTuberia = TipoTuberia.MURO,
                   circuitos: list[str] = [], diametro: str = "1/2\"", nivel: str = "PISO 1",
                   elevacion: Optional[float] = None) -> dict:
    """Traza una tubería como polilínea (metros). tipo: muro, piso, techo, comunicaciones, acometida."""
    p = _p()
    t = Tuberia(id=p.siguiente_id("T", "tuberias"), ruta=ruta, tipo=tipo, circuitos=circuitos,
                diametro=diametro, nivel=nivel, elevacion=elevacion)
    p.tuberias.append(t)
    _guardar()
    longitud = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(ruta, ruta[1:]))
    return {"id": t.id, "longitud_m": round(longitud, 2)}


@mcp.tool()
def eliminar_elemento(coleccion: Literal["recintos", "salidas", "circuitos", "tableros", "tuberias"],
                      id: str) -> dict:
    """Elimina un elemento del proyecto por su id."""
    p = _p()
    lista = getattr(p, coleccion)
    antes = len(lista)
    lista[:] = [e for e in lista if e.id != id]
    _guardar()
    return {"eliminados": antes - len(lista)}


@mcp.tool()
def listar_simbolos() -> list[dict]:
    """Biblioteca de símbolos disponibles (clave, descripción, altura de montaje, capa)."""
    return [{"clave": s.clave, "descripcion": s.descripcion, "altura_m": s.altura_montaje,
             "capa": s.capa, "grupo": s.grupo} for s in SIMBOLOS.values()]


# ------------------------------------------------------------------ salida
_LAMINAS = {"iluminacion_y_tomas": ("iluminacion", "tomas"), "completo": ("completo",),
            "iluminacion": ("iluminacion",), "tomas": ("tomas",)}


@mcp.tool()
def generar_dxf(nombre_archivo: Optional[str] = None,
                laminas: Literal["iluminacion_y_tomas", "completo", "iluminacion", "tomas"] = "iluminacion_y_tomas",
                vista_previa: bool = False) -> dict:
    """Genera un DXF con las láminas del proyecto (un pliego por nivel y tipo)."""
    p = _p()
    nombre = nombre_archivo or f"{_ruta_json(p.nombre).stem}.dxf"
    ruta = CARPETA / "salidas" / nombre
    res = Renderizador(p, DXFBackend(ruta)).dibujar_juego(_LAMINAS[laminas])
    out = {"dxf": res}
    if vista_previa:
        from .preview import dxf_a_png

        out["png"] = str(dxf_a_png(ruta))
    return out


@mcp.tool()
def dibujar_en_autocad(laminas: Literal["iluminacion_y_tomas", "completo", "iluminacion", "tomas"] = "iluminacion_y_tomas",
                       nuevo_dibujo: bool = True) -> dict:
    """Dibuja el proyecto directamente en el AutoCAD abierto (solo Windows, AutoCAD completo)."""
    from .backends.autocad_com import AutoCADBackend

    res = Renderizador(_p(), AutoCADBackend(nuevo_dibujo=nuevo_dibujo)).dibujar_juego(_LAMINAS[laminas])
    return {"resultado": res}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
