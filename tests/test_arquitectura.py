"""Pruebas del paso 2 con un plano sintético: dos apartamentos y un corredor, dibujado en milímetros,
con muros en líneas sueltas, puertas en bloques (una espejada), ventanas y nombres de recinto."""

import math

import ezdxf
import pytest

from electromcp.arquitectura import Categoria, analizar_capas, aplicar_a_proyecto, depurar_plano
from electromcp.arquitectura.capas import por_nombre
from electromcp.model import Proyecto, UsoRecinto

E = 150  # espesor de muro, mm


def _muro(msp, x0, y0, x1, y1, capa="A-MUROS"):
    """Muro rectangular (x0,y0)-(x1,y1) dibujado con 4 líneas sueltas."""
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        msp.add_line(a, b, dxfattribs={"layer": capa})


def _plano(ruta):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    # bloque de puerta de 900 mm: hoja abierta sobre +Y, barrido de 0° a 90°, bisagra en el origen
    blk = doc.blocks.new("PUERTA_90")
    blk.add_line((0, 0), (0, 900), dxfattribs={"layer": "0"})
    blk.add_arc((0, 0), 900, 0, 90, dxfattribs={"layer": "0"})
    # Caja exterior 10 x 8 m. Corredor horizontal de 1,5 m al sur; dos aptos arriba (x<5 y x>5).
    _muro(msp, 0, 0, 10000, E)              # sur
    _muro(msp, 0, 8000 - E, 10000, 8000)    # norte
    _muro(msp, 0, E, E, 8000 - E)           # oeste
    _muro(msp, 10000 - E, E, 10000, 8000 - E)  # este
    # muro corredor/aptos en y=1500, con vanos de puerta en x=1000..1900 y x=6000..6900
    _muro(msp, E, 1500, 1000, 1500 + E)
    _muro(msp, 1900, 1500, 6000, 1500 + E)
    _muro(msp, 6900, 1500, 10000 - E, 1500 + E)
    # muro divisorio entre aptos en x=5000
    _muro(msp, 5000, 1500 + E, 5000 + E, 8000 - E)
    # baño del apto 1: muro y=5000 de x=E..2500 con vano 1500..2300, y muro x=2500
    _muro(msp, E, 5000, 1500, 5000 + E)
    _muro(msp, 2300, 5000, 2500, 5000 + E)
    _muro(msp, 2500, 5000, 2500 + E, 8000 - E)
    # puertas: entradas (bisagra en la jamba izquierda, hoja cerrada a lo largo del muro)
    msp.add_blockref("PUERTA_90", (1000, 1500 + E / 2), dxfattribs={"layer": "A-PUERTAS"})
    msp.add_blockref("PUERTA_90", (6900, 1500 + E / 2),  # espejada: bisagra a la derecha
                     dxfattribs={"layer": "A-PUERTAS", "xscale": -1})
    msp.add_blockref("PUERTA_90", (1500, 5000 + E / 2), dxfattribs={"layer": "A-PUERTAS", "xscale": 0.8889, "yscale": 0.8889})
    # ventanas en el muro norte: vano 3000..4000 del apto 1 (se corta el muro con dos tramos)
    for y in (8000 - E, 8000 - E / 2, 8000):
        msp.add_line((3000, y), (4000, y), dxfattribs={"layer": "A-VENTANAS"})
    # textos
    for txt, x, y in (("Sala - Comedor", 3500, 3000), ("Cocina", 1200, 3000), ("Baño", 1300, 6500),
                      ("Alcoba", 7500, 5000), ("Hall", 5000, 750), ("APTO 101", 3500, 2500),
                      ("APTO 102", 7500, 2500), ("125.40", 7500, 4500)):
        msp.add_text(txt, height=120, dxfattribs={"layer": "A-TEXTO-ESPACIOS", "insert": (x, y)})
    msp.add_aligned_dim((0, -500), (10000, -500), distance=300, dxfattribs={"layer": "COTAS"}).render()
    # un sofá suelto (mobiliario que debe desaparecer)
    msp.add_lwpolyline([(6000, 6000), (8000, 6000), (8000, 6800), (6000, 6800)], close=True,
                       dxfattribs={"layer": "A-MUEBLES"})
    doc.saveas(ruta)
    return ruta


@pytest.fixture()
def plano(tmp_path):
    return _plano(tmp_path / "sintetico.dxf")


def test_clasificacion_por_nombre():
    assert por_nombre("A-MUROS") == Categoria.MUROS
    assert por_nombre("_Muros Bajos") == Categoria.MUROS_BAJOS
    assert por_nombre("E. EJE ESTRUCTURA") == Categoria.EJES
    assert por_nombre("_Muebles Baños") == Categoria.APARATOS
    assert por_nombre("_Muebles") == Categoria.MOBILIARIO
    assert por_nombre("COTAS") == Categoria.COTAS
    assert por_nombre("_F5") is None


def test_analizar_capas(plano):
    r = analizar_capas(plano)
    assert r["unidades_origen"] == "mm"
    cats = {c["capa"]: c["categoria"] for c in r["capas"]}
    assert cats["A-MUROS"] == "muros"
    assert cats["A-PUERTAS"] == "puertas"


def test_depurar_detecta_recintos_y_unidades(plano, tmp_path):
    res = depurar_plano(plano, tmp_path / "out", vista_previa=False)
    it = res.interpretacion
    assert len(it.puertas) == 3
    # la puerta espejada debe tener la bisagra en x = 6,9 m y la hoja cerrada hacia x = 6,0 m
    p = min(it.puertas, key=lambda q: abs(q.bisagra[0] - 6.9))
    assert p.bisagra[0] == pytest.approx(6.9, abs=0.01) and p.extremo[0] == pytest.approx(6.0, abs=0.01)
    nombres = {r.nombre: r for r in it.recintos}
    assert nombres["Baño"].uso == UsoRecinto.BANO
    assert nombres["Alcoba"].uso == UsoRecinto.ALCOBA
    assert nombres["Hall"].uso == UsoRecinto.CIRCULACION and nombres["Hall"].comun
    cocina = next(r for r in it.recintos if r.uso == UsoRecinto.COCINA)
    assert len(cocina.zonas) == 2  # cocina abierta a la sala-comedor
    assert nombres["Alcoba"].area == pytest.approx((10 - 5.15 - 0.15) * (8 - 1.65 - 0.15), rel=0.02)
    assert set(it.unidades) == {"APTO 101", "APTO 102"}
    assert nombres["Baño"].unidad == "APTO 101" and nombres["Alcoba"].unidad == "APTO 102"
    assert any(v.ancho == pytest.approx(1.0, abs=0.1) for v in it.ventanas)


def test_dxf_depurado_limpio(plano, tmp_path):
    res = depurar_plano(plano, tmp_path / "out", vista_previa=False)
    doc = ezdxf.readfile(res.archivos["dxf"])
    capas = {e.dxf.layer for e in doc.modelspace()}
    assert capas <= {c for c in capas if c.startswith("ARQ-")}
    assert "ARQ-MUROS" in capas and "ARQ-RECINTOS" in capas and "ARQ-VANOS" in capas
    assert doc.header["$INSUNITS"] == 6
    assert "PUERTA_90" not in doc.blocks  # sin bloques heredados del plano original
    textos = [e.dxf.text for e in doc.modelspace().query("TEXT")]
    assert "BAÑO" in textos and "APTO 101" in textos


def test_cargar_en_proyecto(plano, tmp_path):
    res = depurar_plano(plano, None)
    p = Proyecto(nombre="Prueba")
    info = aplicar_a_proyecto(p, res.interpretacion, "PISO 1")
    assert info["recintos"] == len(p.recintos) == 4
    assert any(a.capa == "ARQ-MUROS" for a in p.arquitectura)
    Proyecto.model_validate(p.model_dump())
    # se puede dibujar con el renderizador del paso 1
    from electromcp.backends.dxf_backend import DXFBackend
    from electromcp.render import Renderizador

    Renderizador(p, DXFBackend(tmp_path / "laminas.dxf")).dibujar_juego(("tomas",))
    assert (tmp_path / "laminas.dxf").exists()
