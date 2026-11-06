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
        "Unidades en metros; alturas sobre NPT. Si hay plano arquitectónico: analizar_plano -> depurar_plano "
        "(detecta muros, vanos, recintos y apartamentos y los carga al proyecto) -> corregir_recinto si hace falta "
        "-> disenar_instalacion (paso 3: tomas NTC 2050, iluminación RETILAP, interruptores, circuitos, tableros, "
        "tubería y cuadros de carga) -> verificar_diseno / cuadro_de_cargas -> generar_dxf(laminas='todo') o "
        "dibujar_en_autocad(laminas='todo'). "
        "Flujo manual: crear_proyecto -> agregar_recinto -> "
        "agregar_tablero -> agregar_circuito -> agregar_salidas -> trazar_tuberia -> generar_dxf o "
        "dibujar_en_autocad. Use listar_simbolos para conocer las claves de símbolo. "
        "El diseño final debe ser revisado y firmado por un ingeniero electricista con matrícula."
    ),
)

CARPETA = Path(os.environ.get("ELECTROMCP_DIR", Path.home() / "ElectroMCP"))
_estado: dict = {"proyecto": None, "informe": None}


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
                      "unidad": r.unidad, "area_m2": round(r.area, 2)} for r in p.recintos],
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
            "iluminacion": ("iluminacion",), "tomas": ("tomas",), "cuadros": ("cuadros",),
            "todo": ("iluminacion", "tomas", "cuadros")}
TipoLaminas = Literal["iluminacion_y_tomas", "completo", "iluminacion", "tomas", "cuadros", "todo"]


@mcp.tool()
def generar_dxf(nombre_archivo: Optional[str] = None,
                laminas: TipoLaminas = "todo", vista_previa: bool = False) -> dict:
    """Genera un DXF con las láminas del proyecto (un pliego por nivel y tipo). 'todo' agrega los cuadros de
    carga y diagramas unifilares."""
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
def dibujar_en_autocad(laminas: TipoLaminas = "todo", nuevo_dibujo: bool = True) -> dict:
    """Dibuja el proyecto directamente en el AutoCAD abierto (solo Windows, AutoCAD completo)."""
    from .backends.autocad_com import AutoCADBackend

    res = Renderizador(_p(), AutoCADBackend(nuevo_dibujo=nuevo_dibujo)).dibujar_juego(_LAMINAS[laminas])
    return {"resultado": res}


# ------------------------------------------------------------------ plano arquitectónico (paso 2)
def _ruta_plano(ruta: str) -> Path:
    r = Path(ruta).expanduser()
    if not r.is_absolute():
        r = CARPETA / "planos" / r
    if not r.exists():
        raise FileNotFoundError(f"No existe {r}")
    if r.suffix.lower() == ".dwg":
        from .arquitectura.dwg import convertir_dwg_a_dxf

        r = convertir_dwg_a_dxf(r, CARPETA / "planos" / (r.stem + ".dxf"))
    return r


@mcp.tool()
def analizar_plano(ruta: str, mapa_capas: Optional[dict[str, str]] = None, unidades: Optional[str] = None) -> dict:
    """Lee un plano arquitectónico (DXF, o DWG si hay AutoCAD/ODA) y clasifica sus capas.

    Devuelve cada capa con su categoría (muros, puertas, ventanas, aparatos, mobiliario, cotas, textos, ejes,
    achurados, proyecciones, columnas, escaleras, muros_bajos, otros, ignorar) y el criterio usado.
    mapa_capas corrige la clasificación: {"_F5": "muros", "BLANCO": "ignorar"}.
    unidades fuerza la unidad del dibujo ("mm", "cm" o "m") si el archivo no la declara bien.
    """
    from .arquitectura import analizar_capas

    return analizar_capas(_ruta_plano(ruta), mapa_capas, unidades)


@mcp.tool()
def depurar_plano(ruta: str, nivel: str = "PISO 1", mapa_capas: Optional[dict[str, str]] = None,
                  unidades: Optional[str] = None, cargar_en_proyecto: bool = True,
                  incluir_aparatos: bool = True, vista_previa: bool = True) -> dict:
    """Depura e interpreta el plano: muros, columnas, puertas, ventanas, recintos (nombre, uso, área) y
    unidades (apartamentos). Escribe un DXF limpio con capas ARQ-*, un PNG de verificación y un reporte JSON.
    Si hay un proyecto abierto y cargar_en_proyecto=True, carga la arquitectura y los recintos en el nivel dado
    (reemplaza lo que hubiera en ese nivel).
    """
    from .arquitectura import aplicar_a_proyecto
    from .arquitectura import depurar_plano as _depurar

    r = _ruta_plano(ruta)
    res = _depurar(r, CARPETA / "arquitectura", mapa_capas, unidades, incluir_aparatos=incluir_aparatos,
                   vista_previa=vista_previa)
    out = {"resumen": res.reporte["resumen"], "unidades": res.reporte["unidades"],
           "recintos": [{k: v for k, v in x.items() if k in ("id", "nombre", "uso", "unidad", "area_m2", "avisos")}
                        for x in res.reporte["recintos"]],
           "avisos": res.reporte["avisos"] + res.plano.avisos, "archivos": res.archivos}
    p = _estado["proyecto"]
    if cargar_en_proyecto and p is not None:
        out["proyecto"] = aplicar_a_proyecto(p, res.interpretacion, nivel, incluir_aparatos=incluir_aparatos)
        _guardar()
    elif cargar_en_proyecto:
        out["proyecto"] = "No hay proyecto abierto: cree o abra uno y vuelva a ejecutar para cargar los recintos."
    return out


@mcp.tool()
def corregir_recinto(id: str, nombre: Optional[str] = None, uso: Optional[UsoRecinto] = None,
                     unidad: Optional[str] = None, altura_cielo: Optional[float] = None) -> dict:
    """Corrige el nombre, uso, unidad (apartamento) o altura de cielo de un recinto del proyecto."""
    p = _p()
    r = p.recinto(id)
    if nombre is not None:
        r.nombre = nombre
    if uso is not None:
        r.uso = uso
    if unidad is not None:
        r.unidad = unidad or None
    if altura_cielo is not None:
        r.altura_cielo = altura_cielo
    _guardar()
    return {"id": r.id, "nombre": r.nombre, "uso": r.uso.value, "unidad": r.unidad, "area_m2": round(r.area, 2)}


@mcp.tool()
def convertir_dwg_a_dxf(ruta_dwg: str) -> dict:
    """Convierte un DWG a DXF (ODA File Converter o AutoCAD 2026 por COM). El DWG original no se modifica."""
    from .arquitectura.dwg import convertir_dwg_a_dxf as _conv

    dwg = Path(ruta_dwg).expanduser()
    return {"dxf": str(_conv(dwg, CARPETA / "planos" / (dwg.stem + ".dxf")))}


@mcp.tool()
def exportar_dibujo_activo() -> dict:
    """Exporta a DXF el dibujo abierto en AutoCAD (debe estar guardado), para luego depurarlo."""
    from .arquitectura.dwg import dibujo_activo_a_dxf

    from datetime import datetime

    destino = CARPETA / "planos" / f"dibujo_activo_{datetime.now():%Y%m%d_%H%M%S}.dxf"
    return {"dxf": str(dibujo_activo_a_dxf(destino))}


# ------------------------------------------------------------------ diseño automático (paso 3)
@mcp.tool()
def disenar_instalacion(nivel: Optional[str] = None, unidades: Optional[list[str]] = None,
                        estufa: Literal["gas", "electrica"] = "gas",
                        calentador: Literal["gas", "electrico", "ninguno"] = "gas",
                        comunicaciones: bool = True, sensores_zonas_comunes: bool = True,
                        max_tomas_por_circuito: int = 8, max_salidas_iluminacion: int = 12,
                        parametros: Optional[dict] = None) -> dict:
    """Diseña la instalación del nivel a partir de los recintos (paso 3):
    tomas según NTC 2050 210.52 (pared, mesón, baños, lavandería, pasillos) con GFCI donde lo exige 210.8;
    iluminación por método de lúmenes con los niveles de RETILAP; interruptores en el lado de la chapa;
    extractores en baños con ventilación mecánica; circuitos (pequeños artefactos, baños, lavandería, generales,
    alumbrado) con balance de fases; un tablero por unidad, tablero de servicios generales y medidores;
    tubería de recorrido mínimo con conductores y diámetro por llenado; cuadros de carga con demanda (220),
    protección general, alimentador y regulación. Reemplaza lo generado antes por el motor y conserva lo manual.
    parametros: cualquier campo de ParametrosDiseno (p. ej. {"lumenes_por_w": 90, "proteccion_iluminacion_a": 20}).
    """
    from .diseno import ParametrosDiseno, disenar

    datos = dict(parametros or {})
    datos.update(estufa=estufa, calentador=calentador, comunicaciones=comunicaciones,
                 sensores_zonas_comunes=sensores_zonas_comunes, max_tomas_por_circuito=max_tomas_por_circuito,
                 max_salidas_iluminacion=max_salidas_iluminacion)
    inf = disenar(_p(), ParametrosDiseno(**datos), nivel, unidades)
    _estado["informe"] = inf
    ruta = _guardar()
    import json

    rep = CARPETA / "salidas" / f"{_ruta_json(_p().nombre).stem}_diseno.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(inf.reporte(), ensure_ascii=False, indent=2), encoding="utf-8")
    out = inf.resumen()
    out["archivos"] = {"proyecto": ruta, "reporte": str(rep)}
    return out


@mcp.tool()
def cuadro_de_cargas(tablero: Optional[str] = None) -> dict:
    """Cuadro de cargas de un tablero (o de todos): circuitos, VA por fase, corriente, protección, conductor,
    tubo, longitud, regulación, cálculo de demanda (NTC 2050 Sección 220), protección general y alimentador."""
    from .diseno.cuadro import cuadros_del_proyecto

    cs = cuadros_del_proyecto(_p())
    if tablero:
        if tablero not in cs:
            raise ValueError(f"No hay cuadro para {tablero!r}. Tableros: {sorted(cs)}")
        return cs[tablero].como_dict()
    return {k: v.resumen_corto() for k, v in cs.items()}


@mcp.tool()
def verificar_diseno(solo_incumplimientos: bool = False) -> dict:
    """Lista de requisitos NTC 2050 revisados en el último diseño, con artículo, resultado y si cumple."""
    inf = _estado.get("informe")
    if inf is None:
        raise ValueError("Ejecute disenar_instalacion primero.")
    v = [x for x in inf.verificacion if not (solo_incumplimientos and x["cumple"])]
    return {"requisitos": len(inf.verificacion), "cumplen": sum(x["cumple"] for x in inf.verificacion),
            "detalle": v, "calculos_luminicos": [c.resumen() for c in inf.calculos_luminicos],
            "avisos": inf.avisos}


@mcp.tool()
def parametros_diseno() -> dict:
    """Criterios por defecto del motor de diseño, con los artículos de la norma que aplica cada uno."""
    from .diseno import ART, ParametrosDiseno

    return {"parametros": ParametrosDiseno().model_dump(), "articulos": ART}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
