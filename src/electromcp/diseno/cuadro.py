"""Cuadro de cargas de un tablero: carga instalada por circuito, fases, protecciones, conductores,
regulación, y cálculo de la demanda de la unidad (NTC 2050 Sección 220, método estándar) para
dimensionar la protección general y el alimentador."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shapely.ops import unary_union

from ..model import Proyecto, Recinto, Tablero, TipoCircuito, etiqueta_circuito
from .normas import (ART, ParametrosDiseno, calibre_para, calibre_tierra, demanda_220_42, diametro_tubo,
                     proteccion_estandar, regulacion_pct)


@dataclass
class CuadroCargas:
    tablero: str
    unidad: str
    sistema: str
    filas: list[dict] = field(default_factory=list)
    total_va: float = 0.0
    fase_a_va: float = 0.0
    fase_b_va: float = 0.0
    desbalance_pct: float = 0.0
    area_m2: float = 0.0
    demanda: list[dict] = field(default_factory=list)  # pasos del cálculo de demanda
    demanda_va: float = 0.0
    corriente_a: float = 0.0
    proteccion_general_a: float = 0.0
    alimentador: str = ""
    calibre_alimentador: str = ""
    tubo_alimentador: str = ""
    longitud_alimentador_m: Optional[float] = None
    regulacion_alimentador_pct: Optional[float] = None
    n_espacios: int = 0

    def resumen_corto(self) -> dict:
        return {"unidad": self.unidad, "circuitos": len(self.filas), "instalada_va": round(self.total_va),
                "demanda_va": round(self.demanda_va), "corriente_a": round(self.corriente_a, 1),
                "proteccion_general": f"2x{self.proteccion_general_a:.0f} A", "alimentador": self.alimentador,
                "desbalance_pct": round(self.desbalance_pct, 1)}

    def como_dict(self) -> dict:
        d = dict(self.__dict__)
        d["filas"] = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in f.items()} for f in self.filas]
        return d


def calcular_cuadro(p: Proyecto, tab: Tablero, prm: ParametrosDiseno, recs: list[Recinto],
                    longitudes: dict[str, float], long_alim: Optional[float], comunes: bool = False) -> CuadroCargas:
    cq = CuadroCargas(tab.id, tab.unidad or "", tab.sistema, n_espacios=tab.n_circuitos)
    cs = [c for c in p.circuitos if c.tablero == tab.id]
    ids_recs = {r.id for r in recs}
    tuberias = [t for t in p.tuberias if t.unidad == tab.unidad]
    for c in cs:
        ss = [s for s in p.salidas if s.circuito == c.id and s.recinto in ids_recs]
        lum = [s for s in ss if s.simbolo.startswith(("BALA_", "LUM_", "EXTRACTOR"))]
        tomas = [s for s in ss if s.simbolo.startswith("TOMA_") and s.simbolo != "TOMA_220"]
        esp = [s for s in ss if s.simbolo in ("SALIDA_ESPECIAL", "TOMA_220", "TOMA_AA")]
        if c.tipo == TipoCircuito.ILUMINACION:
            va = sum((s.potencia_va or 0) for s in lum) / 0.9  # LED con FP ≥ 0,9
        else:
            va = sum((s.potencia_va or 0) for s in tomas + esp)
        i = va / c.tension_v
        L = longitudes.get(f"{c.id}@{tab.id}") or c.longitud_m or 10.0
        reg = regulacion_pct(i, L, c.calibre_awg, c.tension_v)
        tubos = sorted({t.diametro for t in tuberias if c.id in t.circuitos},
                       key=lambda d: ['1/2"', '3/4"', '1"', '1-1/4"', '1-1/2"', '2"'].index(d)
                       if d in ['1/2"', '3/4"', '1"', '1-1/4"', '1-1/2"', '2"'] else 0)
        fila = {"circuito": etiqueta_circuito(c.id), "descripcion": c.descripcion, "tipo": c.tipo.value, "luminarias": len(lum),
                "tomas": len(tomas), "especiales": len(esp), "va": va,
                "fase_a_va": va if c.fase == "A" else (va / 2 if c.fase == "AB" else 0.0),
                "fase_b_va": va if c.fase == "B" else (va / 2 if c.fase == "AB" else 0.0),
                "tension_v": c.tension_v, "corriente_a": i, "polos": c.polos, "proteccion_a": c.proteccion_a,
                "conductor": c.conductor.replace(" Cu THHN/THWN-2", ""), "calibre_awg": c.calibre_awg,
                "tubo": "PVC " + (tubos[-1] if tubos else prm.tubo_min), "longitud_m": L, "regulacion_pct": reg,
                "fase": c.fase}
        cq.filas.append(fila)
    cq.total_va = sum(f["va"] for f in cq.filas)
    cq.fase_a_va = sum(f["fase_a_va"] for f in cq.filas)
    cq.fase_b_va = sum(f["fase_b_va"] for f in cq.filas)
    mx = max(cq.fase_a_va, cq.fase_b_va, 1e-9)
    cq.desbalance_pct = 100.0 * abs(cq.fase_a_va - cq.fase_b_va) / mx

    # ---------------- demanda (Sección 220, Parte III)
    ctx_area = unary_union([_poligono(r).buffer(0.075, join_style="mitre") for r in recs])
    cq.area_m2 = ctx_area.area
    D = cq.demanda
    if comunes:
        ilum = sum(f["va"] for f in cq.filas if f["tipo"] == "iluminacion")
        otros = cq.total_va - ilum
        D.append({"concepto": "Alumbrado zonas comunes (carga instalada, 100 %)", "va": ilum, "factor": 1.0})
        D.append({"concepto": "Tomas zonas comunes 180 VA c/u (220.44: primeros 10 kVA al 100 %)", "va": otros,
                  "factor": 1.0 if otros <= 10000 else 0.5})
        cq.demanda_va = ilum + (otros if otros <= 10000 else 10000 + 0.5 * (otros - 10000))
    else:
        n_pa = sum(1 for c in cs if c.tipo == TipoCircuito.PEQUENOS_ARTEFACTOS)
        n_lav = sum(1 for c in cs if c.tipo == TipoCircuito.LAVANDERIA)
        alum = prm.va_alumbrado_m2 * cq.area_m2
        pa = prm.va_pequenos_artefactos * n_pa
        lav = prm.va_lavanderia * n_lav
        sub = alum + pa + lav
        D.append({"concepto": f"Alumbrado general y tomas: {prm.va_alumbrado_m2:.0f} VA/m² × {cq.area_m2:.1f} m² "
                              f"({ART['carga_alumbrado']})", "va": alum})
        D.append({"concepto": f"Pequeños artefactos: {n_pa} × {prm.va_pequenos_artefactos:.0f} VA "
                              f"({ART['carga_pa']})", "va": pa})
        D.append({"concepto": f"Lavandería: {n_lav} × {prm.va_lavanderia:.0f} VA ({ART['carga_pa']})", "va": lav})
        dem = demanda_220_42(sub)
        D.append({"concepto": f"Subtotal {sub:.0f} VA con factores de demanda ({ART['factor_demanda']})", "va": dem})
        especiales = [f for f in cq.filas if f["tipo"] == "especial"]
        for f in especiales:
            if "Estufa" in f["descripcion"]:
                v = 0.8 * f["va"] if f["va"] <= 8750 else 8000.0
                D.append({"concepto": "Estufa / cubierta de cocción (220.55, Tabla 220.55 col. B)", "va": v})
                dem += v
            else:
                D.append({"concepto": f"{f['descripcion']} (100 %)", "va": f["va"]})
                dem += f["va"]
        cq.demanda_va = dem
    cq.corriente_a = cq.demanda_va / prm.tension_ff_v
    cq.proteccion_general_a = proteccion_estandar(cq.corriente_a, prm.proteccion_general_min_a if not comunes else 20)
    cal = calibre_para(cq.proteccion_general_a, "10")
    cal_t = calibre_tierra(cq.proteccion_general_a)
    cq.calibre_alimentador = cal
    cq.tubo_alimentador = diametro_tubo([cal, cal, cal, cal_t], '3/4"' if cal not in ("14", "12") else prm.tubo_min)
    cq.alimentador = f"2#{cal} F + 1#{cal} N + 1#{cal_t} T Cu THHN, PVC {cq.tubo_alimentador}"
    if long_alim is not None:
        cq.longitud_alimentador_m = long_alim
        cq.regulacion_alimentador_pct = regulacion_pct(cq.corriente_a, long_alim, cal, prm.tension_ff_v)
    return cq


def _poligono(r: Recinto):
    from shapely.geometry import Polygon

    pg = Polygon(r.contorno)
    return pg if pg.is_valid else pg.buffer(0)


def cuadros_del_proyecto(p: Proyecto, nivel: Optional[str] = None) -> dict[str, CuadroCargas]:
    """Recalcula los cuadros de carga de los tableros a partir del proyecto guardado."""
    from .motor import COMUNES

    prm = ParametrosDiseno.model_validate(p.parametros_diseno or {})
    out = {}
    for t in p.tableros:
        if nivel is not None and t.nivel != nivel:
            continue
        if not any(c.tablero == t.id for c in p.circuitos):
            continue
        if t.unidad == COMUNES:
            recs = [r for r in p.recintos if r.nivel == t.nivel and not r.vacio and (r.comun or not r.unidad)]
        elif t.unidad:
            recs = [r for r in p.recintos if r.unidad == t.unidad and not r.comun]
        else:
            recs = [r for r in p.recintos if r.nivel == t.nivel]
        out[t.id] = calcular_cuadro(p, t, prm, recs, {}, t.longitud_alimentador_m, comunes=t.unidad == COMUNES)
    return out
