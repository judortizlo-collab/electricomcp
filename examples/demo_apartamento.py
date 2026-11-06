"""Demostración del paso 1: un apartamento de un nivel dibujado a partir del modelo.

Las salidas aquí se ubican a mano para probar símbolos, capas, láminas,
convenciones y rótulo. La ubicación automática según NTC 2050 llega en el paso 3.

Uso:
    python examples/demo_apartamento.py              # genera DXF + PNG
    python examples/demo_apartamento.py --autocad    # dibuja en el AutoCAD abierto (Windows)
"""

import sys
from pathlib import Path

from electromcp.backends.dxf_backend import DXFBackend
from electromcp.model import (Circuito, Proyecto, Recinto, Rotulo, Salida, Tablero, TipoCircuito,
                              TipoTuberia, Tuberia, UsoRecinto)
from electromcp.render import Renderizador


def rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def construir() -> Proyecto:
    p = Proyecto(
        nombre="APARTAMENTO DEMO",
        rotulo=Rotulo(empresa="EMPRESA DE DISEÑO S.A.S", contacto="Cel: 300 000 0000",
                      proyecto="APARTAMENTO DEMO", municipio="ARMENIA - QUINDÍO",
                      disenador="INGENIERO ELECTRICISTA", matricula="XX 000-000000",
                      dibujante="ELECTROMCP", fecha="NOVIEMBRE DE 2026"),
    )
    R = [
        Recinto(id="R1", nombre="Sala - comedor", uso=UsoRecinto.SALA_COMEDOR, contorno=rect(0, 0, 6.0, 5.0)),
        Recinto(id="R2", nombre="Cocina", uso=UsoRecinto.COCINA, contorno=rect(6.0, 2.5, 3.0, 2.5)),
        Recinto(id="R3", nombre="Ropas", uso=UsoRecinto.ROPAS, contorno=rect(6.0, 0, 3.0, 2.5)),
        Recinto(id="R4", nombre="Circulación", uso=UsoRecinto.CIRCULACION, contorno=rect(0, 5.0, 9.0, 1.2)),
        Recinto(id="R5", nombre="Habitación principal", uso=UsoRecinto.ALCOBA, contorno=rect(0, 6.2, 4.0, 3.8)),
        Recinto(id="R6", nombre="Baño", uso=UsoRecinto.BANO, contorno=rect(4.0, 6.2, 2.0, 3.8)),
        Recinto(id="R7", nombre="Habitación 2", uso=UsoRecinto.ALCOBA, contorno=rect(6.0, 6.2, 3.0, 3.8)),
    ]
    p.recintos = R
    p.tableros = [Tablero(id="TD-1", posicion=(8.4, 5.6), rotacion=0)]
    p.circuitos = [
        Circuito(id="C-01", tablero="TD-1", tipo=TipoCircuito.ILUMINACION, descripcion="Iluminación general",
                 proteccion_a=15, conductor="3x14 AWG Cu THHN"),
        Circuito(id="C-02", tablero="TD-1", tipo=TipoCircuito.TOMAS, descripcion="Tomas sala y alcobas"),
        Circuito(id="C-03", tablero="TD-1", tipo=TipoCircuito.PEQUENOS_ARTEFACTOS, descripcion="Cocina (pequeños artefactos)"),
        Circuito(id="C-04", tablero="TD-1", tipo=TipoCircuito.BANO, descripcion="Baño (GFCI)"),
        Circuito(id="C-05", tablero="TD-1", tipo=TipoCircuito.LAVANDERIA, descripcion="Lavadora"),
        Circuito(id="C-06", tablero="TD-1", tipo=TipoCircuito.ESPECIAL, descripcion="Nevera"),
    ]
    S = []

    def s(sim, x, y, c=None, rot=0):
        S.append(Salida(id=f"S{len(S) + 1:03d}", simbolo=sim, posicion=(x, y), circuito=c, rotacion=rot))

    # Iluminación
    for x, y in [(1.5, 1.25), (4.5, 1.25), (1.5, 3.75), (4.5, 3.75)]:
        s("BALA_LED_12W", x, y, "C-01")
    s("LUM_COLGANTE", 3.0, 2.5, "C-01")
    s("BALA_LED_18W", 7.5, 3.75, "C-01")
    s("BALA_LED_9W", 7.5, 1.25, "C-01")
    for x in (1.5, 4.5, 7.5):
        s("BALA_LED_5W", x, 5.6, "C-01")
    s("BALA_LED_18W", 2.0, 8.1, "C-01")
    s("BALA_LED_9W", 5.0, 8.1, "C-01")
    s("BALA_LED_12W", 7.5, 8.1, "C-01")
    s("INT_DOBLE", 5.75, 4.6, rot=270)
    s("INT_SENCILLO", 6.25, 4.6, rot=90)
    s("INT_SENCILLO", 6.25, 2.1, rot=90)
    s("INT_CONMUTABLE", 0.3, 5.6, rot=270)
    s("INT_CONMUTABLE", 8.0, 5.25)
    s("INT_SENCILLO", 3.7, 6.5, rot=270)
    s("INT_SENCILLO", 4.3, 6.5, rot=90)
    s("INT_SENCILLO", 6.3, 6.5, rot=90)
    # Tomas (frente hacia el interior del recinto)
    for x, y, r in [(0.0, 1.2, 270), (0.0, 3.8, 270), (3.0, 0.0, 0), (6.0, 1.2, 90), (2.0, 5.0, 180), (4.8, 5.0, 180)]:
        s("TOMA_DOBLE", x, y, "C-02", r)
    for x, y, r in [(0.0, 7.3, 270), (0.0, 9.0, 270), (2.0, 10.0, 180), (4.0, 8.0, 90),
                    (9.0, 7.3, 90), (7.5, 10.0, 180), (6.0, 9.0, 270)]:
        s("TOMA_DOBLE", x, y, "C-02", r)
    for x, y in [(6.7, 5.0), (7.8, 5.0)]:
        s("TOMA_GFCI", x, y, "C-03", 180)
    s("TOMA_GFCI", 9.0, 3.2, "C-03", 90)
    s("SALIDA_ESPECIAL", 9.0, 4.4, "C-06", 90)
    s("TOMA_GFCI", 5.0, 10.0, "C-04", 180)
    s("SALIDA_ESPECIAL", 7.5, 0.0, "C-05", 0)
    s("TOMA_220", 6.0, 0.6, "C-05", 270)
    s("TOMA_AA", 2.0, 9.95, "C-07", 180)
    s("COM", 3.0, 4.95, rot=180)
    s("COM", 0.05, 8.1, rot=270)
    s("GABINETE_COM", 7.4, 5.6)
    p.circuitos.append(Circuito(id="C-07", tablero="TD-1", tipo=TipoCircuito.AIRE, descripcion="Aire acondicionado",
                                tension_v=240, polos=2))
    p.salidas = S
    p.tuberias = [
        Tuberia(id="T001", ruta=[(8.4, 5.6), (7.5, 5.6), (4.5, 5.6), (1.5, 5.6)], tipo=TipoTuberia.TECHO, circuitos=["C-01"]),
        Tuberia(id="T002", ruta=[(4.5, 5.6), (4.5, 3.75), (4.5, 1.25)], tipo=TipoTuberia.TECHO, circuitos=["C-01"]),
        Tuberia(id="T003", ruta=[(4.5, 3.75), (1.5, 3.75), (1.5, 1.25)], tipo=TipoTuberia.TECHO, circuitos=["C-01"]),
        Tuberia(id="T004", ruta=[(1.5, 5.6), (2.0, 8.1), (5.0, 8.1), (7.5, 8.1)], tipo=TipoTuberia.TECHO, circuitos=["C-01"]),
        Tuberia(id="T005", ruta=[(8.4, 5.4), (8.4, 4.9), (6.7, 4.9), (6.7, 5.0)], tipo=TipoTuberia.MURO, circuitos=["C-03"]),
        Tuberia(id="T006", ruta=[(8.4, 5.4), (8.4, 4.4), (9.0, 4.4)], tipo=TipoTuberia.MURO, circuitos=["C-06"]),
        Tuberia(id="T007", ruta=[(8.2, 5.4), (6.2, 4.9), (4.8, 4.9), (2.0, 4.9), (0.1, 3.8), (0.1, 1.2), (3.0, 0.1), (5.9, 1.2)],
                tipo=TipoTuberia.PISO, circuitos=["C-02"]),
        Tuberia(id="T008", ruta=[(8.6, 5.4), (8.9, 3.2), (8.9, 0.6), (7.5, 0.1), (6.1, 0.6)], tipo=TipoTuberia.PISO,
                circuitos=["C-03", "C-05"]),
        Tuberia(id="T009", ruta=[(8.2, 5.8), (6.1, 6.3), (5.0, 9.9)], tipo=TipoTuberia.MURO, circuitos=["C-04"]),
        Tuberia(id="T010", ruta=[(8.0, 5.8), (8.9, 7.3), (7.5, 9.9), (6.1, 9.0), (4.1, 8.0), (2.0, 9.9), (0.1, 9.0), (0.1, 7.3)],
                tipo=TipoTuberia.PISO, circuitos=["C-02"]),
        Tuberia(id="T011", ruta=[(7.4, 5.6), (3.0, 5.1), (0.1, 8.1)], tipo=TipoTuberia.COMUNICACIONES),
        Tuberia(id="T012", ruta=[(9.6, 5.6), (11.0, 5.6)], tipo=TipoTuberia.ACOMETIDA),
    ]
    return p


if __name__ == "__main__":
    proyecto = construir()
    salida = Path(__file__).resolve().parent.parent / "salidas"
    proyecto.guardar(salida / "apartamento_demo.json")
    if "--autocad" in sys.argv:
        from electromcp.backends.autocad_com import AutoCADBackend

        print(Renderizador(proyecto, AutoCADBackend(nuevo_dibujo=True)).dibujar_juego())
    else:
        ruta = Renderizador(proyecto, DXFBackend(salida / "apartamento_demo.dxf")).dibujar_juego()
        print("DXF:", ruta)
        from electromcp.preview import dxf_a_png

        print("PNG:", dxf_a_png(ruta))
