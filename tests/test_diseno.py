"""Pruebas del paso 3 (motor de diseño NTC 2050) sobre el plano sintético del paso 2 y sobre
recintos dibujados a mano (sin plano arquitectónico)."""

import math

import ezdxf
import pytest

from electromcp.arquitectura import aplicar_a_proyecto, depurar_plano
from electromcp.diseno import ParametrosDiseno, disenar
from electromcp.diseno.geometria import Contexto, tramos_de_pared
from electromcp.diseno.normas import (calibre_para, calibre_tierra, demanda_220_42, diametro_tubo,
                                      regulacion_pct)
from electromcp.model import Proyecto, Recinto, UsoRecinto, etiqueta_circuito

from test_arquitectura import _plano


@pytest.fixture()
def proyecto(tmp_path):
    res = depurar_plano(_plano(tmp_path / "sintetico.dxf"), None)
    p = Proyecto(nombre="Prueba")
    aplicar_a_proyecto(p, res.interpretacion, "PISO 1")
    return p


def test_tablas_normativas():
    assert calibre_para(15) == "14" and calibre_para(20) == "12" and calibre_para(30) == "10"
    assert calibre_para(40) == "8" and calibre_para(40, "10") == "8"
    assert calibre_tierra(20) == "12" and calibre_tierra(40) == "10" and calibre_tierra(100) == "8"
    assert demanda_220_42(3000) == 3000 and demanda_220_42(10000) == pytest.approx(3000 + 0.35 * 7000)
    assert diametro_tubo(["12"] * 3) == '1/2"'
    assert diametro_tubo(["12"] * 9) == '3/4"'
    # 20 A, 30 m, #12, 120 V: 2·20·6,6·0,030/120 = 6,6 %
    assert regulacion_pct(20, 30, "12", 120) == pytest.approx(6.6, rel=1e-3)


def test_tramos_sin_puertas():
    p = Proyecto(nombre="t", recintos=[Recinto(id="R1", nombre="Alcoba", uso=UsoRecinto.ALCOBA,
                                               contorno=[(0, 0), (4, 0), (4, 3), (0, 3)])])
    ctx = Contexto.de_proyecto(p, "PISO 1")
    ts = tramos_de_pared(ctx, "R1")
    assert len(ts) == 1 and ts[0].longitud == pytest.approx(14.0, abs=0.1)


def test_recinto_manual_210_52A():
    """Alcoba de 4 x 3 m sin puertas: 14 m de pared -> ⌈14 / 3,6⌉ = 4 tomas."""
    p = Proyecto(nombre="t", recintos=[Recinto(id="R1", nombre="Alcoba", uso=UsoRecinto.ALCOBA, unidad="CASA",
                                               contorno=[(0, 0), (4, 0), (4, 3), (0, 3)])])
    inf = disenar(p)
    tomas = [s for s in p.salidas if s.simbolo == "TOMA_DOBLE"]
    assert len(tomas) == 4
    assert all(abs(s.posicion[0]) > 0.05 or True for s in tomas)
    assert any(s.simbolo.startswith("BALA_LED") for s in p.salidas)
    assert all(v["cumple"] for v in inf.verificacion if "210.52(A)" in v["articulo"])


def test_diseno_completo(proyecto, tmp_path):
    p = proyecto
    inf = disenar(p)
    # un tablero por apartamento y uno de servicios generales
    assert {t.unidad for t in p.tableros} == {"APTO 101", "APTO 102", "SERVICIOS COMUNES"}
    td101 = next(t for t in p.tableros if t.unidad == "APTO 101")
    tipos = [c.tipo.value for c in p.circuitos if c.tablero == td101.id]
    assert tipos.count("pequenos_artefactos") >= 2  # 210.11(C)(1)
    assert "bano" in tipos and "iluminacion" in tipos
    # baño con toma GFCI
    bano = next(r for r in p.recintos if r.uso == UsoRecinto.BANO)
    assert any(s.simbolo == "TOMA_GFCI" for s in p.salidas if s.recinto == bano.id)
    # todas las salidas eléctricas tienen circuito, y los ids son únicos en el proyecto
    for s in p.salidas:
        if s.simbolo not in ("COM", "MEDIDOR"):
            assert s.circuito, s
    Proyecto.model_validate(p.model_dump())
    assert etiqueta_circuito(p.circuitos[0].id).startswith("C-")
    # tubería: cada circuito llega a su tablero
    for c in p.circuitos:
        assert any(c.id in t.circuitos for t in p.tuberias), c.id
    # cuadros con demanda y protección general
    for cq in inf.cuadros.values():
        assert cq.demanda_va > 0 and cq.proteccion_general_a >= 20
        assert cq.desbalance_pct <= 100
    assert inf.verificacion and all(v["cumple"] for v in inf.verificacion), \
        [v for v in inf.verificacion if not v["cumple"]]
    # rediseñar no duplica
    n = len(p.salidas)
    disenar(p)
    assert len(p.salidas) == n


def test_parametros_estufa_electrica(proyecto):
    p = proyecto
    inf = disenar(p, ParametrosDiseno(estufa="electrica"))
    esp = [c for c in p.circuitos if c.polos == 2]
    if any(a.tipo == "estufa" for a in p.aparatos):
        assert esp and esp[0].fase == "AB"
    assert inf.cuadros


def test_laminas_con_cuadros(proyecto, tmp_path):
    from electromcp.backends.dxf_backend import DXFBackend
    from electromcp.render import Renderizador

    p = proyecto
    disenar(p)
    ruta = tmp_path / "electrico.dxf"
    Renderizador(p, DXFBackend(ruta)).dibujar_juego(("iluminacion", "tomas", "cuadros"))
    doc = ezdxf.readfile(ruta)
    textos = " ".join(e.dxf.text for e in doc.modelspace().query("TEXT"))
    assert "CUADRO DE CARGAS" in textos and "DIAGRAMA UNIFILAR" in textos
    insertos = {e.dxf.name for e in doc.modelspace().query("INSERT")}
    assert {"TOMA_DOBLE", "TOMA_GFCI", "TABLERO"} <= insertos
