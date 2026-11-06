import sys
from pathlib import Path

import ezdxf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
from demo_apartamento import construir  # noqa: E402

from electromcp.backends.dxf_backend import DXFBackend
from electromcp.model import Proyecto, Recinto
from electromcp.render import Renderizador
from electromcp.symbols import SIMBOLOS


def test_area_y_centroide():
    r = Recinto(id="R", nombre="x", contorno=[(0, 0), (4, 0), (4, 3), (0, 3)])
    assert r.area == pytest.approx(12.0)
    assert r.perimetro == pytest.approx(14.0)
    assert r.centroide == pytest.approx((2.0, 1.5))


def test_ids_duplicados():
    with pytest.raises(ValueError):
        Proyecto(nombre="x", recintos=[
            Recinto(id="R", nombre="a", contorno=[(0, 0), (1, 0), (1, 1)]),
            Recinto(id="R", nombre="b", contorno=[(0, 0), (1, 0), (1, 1)])])


def test_guardar_y_cargar(tmp_path):
    p = construir()
    ruta = p.guardar(tmp_path / "p.json")
    q = Proyecto.cargar(ruta)
    assert q.model_dump() == p.model_dump()


def test_dxf_generado(tmp_path):
    p = construir()
    ruta = Renderizador(p, DXFBackend(tmp_path / "demo.dxf")).dibujar_juego()
    doc = ezdxf.readfile(ruta)
    # Todos los símbolos existen como bloques
    for k in SIMBOLOS:
        assert k in doc.blocks
    # Capas normalizadas
    assert "E-TOMAS" in doc.layers and "ARQ-MUROS" in doc.layers
    msp = doc.modelspace()
    tomas = [e for e in msp.query("INSERT") if e.dxf.name == "TOMA_DOBLE" and e.dxf.layer == "E-TOMAS"]
    assert len(tomas) == sum(1 for s in p.salidas if s.simbolo == "TOMA_DOBLE")
    # Los atributos de circuito quedan horizontales y con el valor correcto
    t = tomas[0]
    att = t.get_attrib("CIRCUITO")
    assert att is not None and att.dxf.text.startswith("C-") and att.dxf.rotation == 0
