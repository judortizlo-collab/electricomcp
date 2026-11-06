"""Motor de diseño: de recintos a instalación completa.

    informe = disenar(proyecto)            # ubica salidas, arma circuitos, tableros y tubería
    informe.cuadros["TD-01"]               # cuadro de cargas con demanda, protecciones y regulación
    informe.verificacion                   # cada requisito NTC 2050 revisado, con su artículo

El motor escribe en el proyecto (salidas, circuitos, tableros y tuberías marcados `auto=True`).
Lo que el ingeniero haya agregado a mano (auto=False) se conserva al volver a diseñar.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from ..model import (Circuito, Proyecto, Recinto, Salida, Tablero, TipoCircuito, TipoTuberia, Tuberia,
                     UsoRecinto, Vano)
from .cuadro import CuadroCargas, calcular_cuadro
from .geometria import Contexto, dist, punto_en_pared, rect_orientado, rotacion_frente, tramos_de_pared
from .normas import (ART, ParametrosDiseno, calibre_para, calibre_tierra, diametro_tubo, regulacion_pct)
from .salidas import (BANO, CALENTADOR, COM, CONTROL, ESTUFA, ILUM, LAV, PA, TOMAS, CalculoLuminico, Propuesta,
                      Ubicador)

COMUNES = "SERVICIOS COMUNES"
LETRAS = "abcdefghijklmnopqrstuvwxyz"
TIPO_CIRCUITO = {ILUM: TipoCircuito.ILUMINACION, TOMAS: TipoCircuito.TOMAS, PA: TipoCircuito.PEQUENOS_ARTEFACTOS,
                 BANO: TipoCircuito.BANO, LAV: TipoCircuito.LAVANDERIA, ESTUFA: TipoCircuito.ESPECIAL,
                 CALENTADOR: TipoCircuito.ESPECIAL}
CATS_PISO = {TOMAS, PA, BANO, LAV, ESTUFA, CALENTADOR}


@dataclass
class InformeDiseno:
    nivel: str
    parametros: ParametrosDiseno
    unidades: dict[str, dict] = field(default_factory=dict)
    calculos_luminicos: list[CalculoLuminico] = field(default_factory=list)
    cuadros: dict[str, CuadroCargas] = field(default_factory=dict)
    verificacion: list[dict] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def resumen(self) -> dict:
        cumple = sum(1 for v in self.verificacion if v["cumple"])
        return {
            "nivel": self.nivel,
            "unidades": self.unidades,
            "tableros": {k: c.resumen_corto() for k, c in self.cuadros.items()},
            "verificacion": {"requisitos": len(self.verificacion), "cumplen": cumple,
                             "no_cumplen": [v for v in self.verificacion if not v["cumple"]]},
            "avisos": self.avisos,
        }

    def reporte(self) -> dict:
        return {
            "nivel": self.nivel,
            "parametros": self.parametros.model_dump(),
            "unidades": self.unidades,
            "calculos_luminicos": [c.resumen() for c in self.calculos_luminicos],
            "cuadros_de_carga": {k: c.como_dict() for k, c in self.cuadros.items()},
            "verificacion": self.verificacion,
            "avisos": self.avisos,
        }


# ======================================================================= API
def disenar(p: Proyecto, prm: Optional[ParametrosDiseno] = None, nivel: Optional[str] = None,
            unidades: Optional[list[str]] = None) -> InformeDiseno:
    prm = prm or ParametrosDiseno()
    nivel = nivel or p.niveles[0]
    return _Motor(p, prm, nivel, unidades).ejecutar()


# ======================================================================= motor
class _Motor:
    def __init__(self, p: Proyecto, prm: ParametrosDiseno, nivel: str, solo: Optional[list[str]]):
        self.p, self.prm, self.nivel, self.solo = p, prm, nivel, solo
        self.inf = InformeDiseno(nivel, prm)
        self._ids: dict[str, int] = defaultdict(int)
        self._longitudes: dict[str, float] = {}  # "C-01@TD-01" -> recorrido al punto más lejano (m)
        self._alim_m: dict[str, float] = {}  # tablero -> longitud del alimentador (m)

    # ------------------------------------------------------------ ids
    def _id(self, prefijo: str, coleccion: str) -> str:
        existentes = {e.id for e in getattr(self.p, coleccion)}
        while True:
            self._ids[prefijo] += 1
            i = f"{prefijo}{self._ids[prefijo]:03d}"
            if i not in existentes:
                return i

    # ------------------------------------------------------------ flujo
    def ejecutar(self) -> InformeDiseno:
        p, nivel = self.p, self.nivel
        grupos: dict[str, list[Recinto]] = defaultdict(list)
        for r in p.recintos:
            if r.nivel != nivel or r.vacio:
                continue
            u = r.unidad if (r.unidad and not r.comun) else COMUNES
            grupos[u].append(r)
        if self.solo:
            grupos = {u: rs for u, rs in grupos.items() if u in self.solo}
        self._limpiar(set(grupos))
        self.ctx = Contexto.de_proyecto(p, nivel)
        self.ub = Ubicador(self.ctx, self.prm, [a for a in p.aparatos if a.nivel == nivel],
                           lambda: self._id("S", "salidas"))
        nombres = sorted(u for u in grupos if u != COMUNES)
        # centro de medición en la zona común (si existe)
        comunes = grupos.get(COMUNES, [])
        self.medidores: dict[str, tuple] = {}
        if comunes and nombres:
            self._centro_medicion(comunes, nombres + [COMUNES])
        for u in nombres:
            self._unidad(u, grupos[u])
        if comunes:
            self._comunes(comunes)
        for c in p.circuitos:
            if c.auto:
                L = self._longitudes.get(f"{c.id}@{c.tablero}")
                if L is not None:
                    c.longitud_m = round(L, 2)
        for t in p.tableros:
            if t.id in self._alim_m:
                t.longitud_alimentador_m = round(self._alim_m[t.id], 2)
            cq = self.inf.cuadros.get(t.id)
            if cq is not None:
                t.proteccion_general_a = cq.proteccion_general_a
                t.alimentador = cq.alimentador
        p.parametros_diseno = self.prm.model_dump()
        self._verificar(grupos)
        return self.inf

    def _limpiar(self, unidades: set[str]) -> None:
        p = self.p
        en_nivel = {r.id for r in p.recintos if r.nivel == self.nivel}
        recs = {r.id: r for r in p.recintos}

        def de_unidad(rid):
            r = recs.get(rid)
            if r is None:
                return None
            return r.unidad if (r.unidad and not r.comun) else COMUNES

        p.salidas = [s for s in p.salidas if not (s.auto and s.nivel == self.nivel and
                                                  (s.recinto not in en_nivel or de_unidad(s.recinto) in unidades))]
        borrar_tab = {t.id for t in p.tableros if t.auto and t.nivel == self.nivel and (t.unidad in unidades or
                                                                                         t.unidad is None)}
        p.tableros = [t for t in p.tableros if t.id not in borrar_tab]
        p.circuitos = [c for c in p.circuitos if not (c.auto and c.tablero in borrar_tab)]
        p.tuberias = [t for t in p.tuberias if not (t.auto and t.nivel == self.nivel and
                                                    (t.unidad in unidades or t.unidad is None))]

    # ------------------------------------------------------------ unidad privada
    def _unidad(self, u: str, recs: list[Recinto]) -> None:
        ctx, prm = self.ctx, self.prm
        ids = {r.id for r in recs}
        entrada = self._puerta_entrada(ids)
        prof, padre_puerta = self._profundidades(recs, entrada)
        props: list[Propuesta] = []
        for r in sorted(recs, key=lambda r: prof.get(r.id, 99)):
            rt = self.ub.tomas(r)
            ri = self.ub.iluminacion(r)
            props += rt.propuestas + ri.propuestas
            self.inf.calculos_luminicos += ri.calculos
            self.inf.avisos += rt.avisos + ri.avisos
        # control de alumbrado
        props += self._interruptores(recs, props, padre_puerta, entrada)
        # tablero junto a la entrada, lado de la chapa, después del interruptor
        tab = self._tablero_unidad(u, recs, entrada, [x.salida.posicion for x in props if x.categoria == CONTROL])
        for x in props:
            self.p.salidas.append(x.salida)
        self._circuitos(u, tab, props, prof)
        self._tuberia(u, tab, props, recs, entrada)
        if u in self.medidores:
            self._alimentador(u, tab, entrada)
        self.inf.cuadros[tab.id] = calcular_cuadro(self.p, tab, prm, recs, self._longitudes, self._alim_m.get(tab.id))
        cq = self.inf.cuadros[tab.id]
        self.inf.unidades[u] = {"tablero": tab.id, "recintos": sorted(ids),
                                "salidas": dict(_conteo(x.salida.simbolo for x in props)),
                                "circuitos": len([c for c in self.p.circuitos if c.tablero == tab.id]),
                                "demanda_va": round(cq.demanda_va), "proteccion_general_a": cq.proteccion_general_a,
                                "alimentador": cq.alimentador}

    def _puerta_entrada(self, ids: set[str]) -> Optional[Vano]:
        cands = []
        recs = self.ctx.recintos
        for v in self.ctx.puertas:
            a, b = (v.recintos + ["EXT", "EXT"])[:2]
            if (a in ids) != (b in ids):
                otro = b if a in ids else a
                comun = otro in recs and recs[otro].comun
                cands.append((0 if comun else 1, -v.ancho, v))
        if not cands:
            return None
        return sorted(cands, key=lambda c: (c[0], c[1]))[0][2]

    def _profundidades(self, recs: list[Recinto], entrada: Optional[Vano]):
        ids = {r.id for r in recs}
        raiz = next((x for x in (entrada.recintos if entrada else []) if x in ids), None)
        if raiz is None:
            raiz = max(recs, key=lambda r: self.ctx.poligonos[r.id].area).id
        ady = defaultdict(list)
        for v in self.ctx.puertas:
            a, b = (v.recintos + ["EXT", "EXT"])[:2]
            if a in ids and b in ids:
                ady[a].append((b, v))
                ady[b].append((a, v))
        prof = {raiz: 0}
        padre_puerta: dict[str, Optional[Vano]] = {raiz: entrada}
        cola = deque([raiz])
        while cola:
            x = cola.popleft()
            for y, v in ady[x]:
                if y not in prof:
                    prof[y] = prof[x] + 1
                    padre_puerta[y] = v
                    cola.append(y)
        for r in recs:  # recintos unidos sin puerta (vanos libres): por vecindad
            if r.id not in prof:
                pg = self.ctx.poligonos[r.id]
                vec = [o for o in prof if self.ctx.poligonos[o].distance(pg) < 0.35]
                prof[r.id] = (min(prof[o] for o in vec) + 1) if vec else 9
                padre_puerta[r.id] = None
        return prof, padre_puerta

    def _interruptores(self, recs, props, padre_puerta, entrada) -> list[Propuesta]:
        out: list[Propuesta] = []
        letra = iter(LETRAS)
        ocupados = []
        for r in recs:
            luces = [x for x in props if x.categoria == ILUM and x.salida.recinto == r.id]
            if not luces:
                continue
            grupos: dict[str, list[Propuesta]] = defaultdict(list)
            for x in luces:
                clave = "extractor" if x.salida.nota == "extractor" else (x.zona or r.nombre)
                grupos[clave].append(x)
            letras = []
            for clave, xs in grupos.items():
                l = next(letra, "z")
                for x in xs:
                    x.salida.control = l
                letras.append(l)
            puerta = padre_puerta.get(r.id)
            if puerta is None and entrada is not None and r.id in entrada.recintos:
                puerta = entrada
            puertas_r = self.ctx.puertas_de(r.id)
            if puerta is None and puertas_r:
                puerta = puertas_r[0]
            _, _, _, lu, _ = rect_orientado(self.ctx.poligonos[r.id])
            if r.uso == UsoRecinto.CIRCULACION and len(puertas_r) >= 2 and lu >= self.prm.pasillo_min_m:
                a, b = max(((x, y) for i, x in enumerate(puertas_r) for y in puertas_r[i + 1:]),
                           key=lambda xy: dist(xy[0].p1, xy[1].p1))
                for pu in (a, b):
                    pr = self.ub.interruptor(r, pu, letras[:1], ocupados)
                    if pr:
                        pr.salida.simbolo = "INT_CONMUTABLE"
                        pr.regla += "; conmutable de 3 vías en los extremos del pasillo"
                        out.append(pr)
                        ocupados.append(pr.salida.posicion)
                continue
            for k in range(0, len(letras), 3):
                pr = self.ub.interruptor(r, puerta, letras[k:k + 3], ocupados)
                if pr:
                    out.append(pr)
                    ocupados.append(pr.salida.posicion)
                else:
                    self.inf.avisos.append(f"{r.nombre} ({r.id}): no se encontró pared para el interruptor.")
        return out

    def _tablero_unidad(self, u: str, recs, entrada: Optional[Vano], interruptores: list) -> Tablero:
        ctx = self.ctx
        tid = _nombre_tablero(u, {t.id for t in self.p.tableros})
        rid = None
        pos, rot = None, 0.0
        if entrada is not None:
            rid = next((x for x in entrada.recintos if x in {r.id for r in recs}), None)
        if rid is None:
            rid = max(recs, key=lambda r: ctx.poligonos[r.id].area).id
        if entrada is not None:
            (x1, y1), (x2, y2) = entrada.p1, entrada.p2
            L = math.hypot(x2 - x1, y2 - y1) or 1.0
            ux, uy = (x2 - x1) / L, (y2 - y1) / L
            objetivo = (x2 + ux * 0.9, y2 + uy * 0.9)
            mid = ((x1 + x2) / 2, (y1 + y2) / 2)
            evitar = [(mid, L / 2 + 0.45)] + [(s, 0.55) for s in interruptores]
        else:
            objetivo = ctx.poligonos[rid].centroid.coords[0]
            evitar = [(s, 0.55) for s in interruptores]
        hit = punto_en_pared(ctx, rid, objetivo, evitar=evitar)
        if hit:
            q, n, _ = hit
            pos = (round(q[0] + n[0] * 0.12, 3), round(q[1] + n[1] * 0.12, 3))
            rot = rotacion_frente(*n)
        else:
            c = ctx.poligonos[rid].representative_point()
            pos = (c.x, c.y)
        tab = Tablero(id=tid, nombre=f"Tablero de distribución {u}", posicion=pos, nivel=self.nivel, rotacion=rot,
                      unidad=u, auto=True, sistema="Monofásico trifilar 120/240 V")
        self.p.tableros.append(tab)
        return tab

    # ------------------------------------------------------------ circuitos
    def _circuitos(self, u: str, tab: Tablero, props: list[Propuesta], prof: dict) -> None:
        prm = self.prm
        orden = lambda x: (prof.get(x.salida.recinto, 9), x.salida.recinto or "", x.salida.posicion)
        por_cat: dict[str, list[Propuesta]] = defaultdict(list)
        for x in props:
            por_cat[x.categoria].append(x)
        planes: list[tuple[str, list[Propuesta], str]] = []  # (categoria, salidas, descripcion)

        def nombres(xs):
            vistos = []
            for x in xs:
                r = self.ctx.recintos.get(x.salida.recinto)
                n = x.zona or (r.nombre if r else "")
                n = re.sub(r"\s*-\s*.*", "", n) if " - " in n and not x.zona else n
                if n and n not in vistos:
                    vistos.append(n)
            return ", ".join(vistos)

        # iluminación: por recintos, hasta max_salidas y 80 % de la capacidad
        cap_ilum = prm.factor_carga_continua * prm.proteccion_iluminacion_a * prm.tension_fn_v
        for bloque in _partir(sorted(por_cat[ILUM], key=orden), prm.max_salidas_iluminacion, cap_ilum,
                              lambda x: (x.salida.potencia_va or 0) / 0.9):
            planes.append((ILUM, bloque, "Iluminación " + nombres(bloque)))
        cap_tomas = prm.factor_carga_continua * prm.proteccion_tomas_a * prm.tension_fn_v
        for bloque in _partir(sorted(por_cat[TOMAS], key=orden), prm.max_tomas_por_circuito, cap_tomas,
                              lambda x: prm.va_por_toma, agrupar=lambda x: x.salida.recinto):
            planes.append((TOMAS, bloque, "Tomas " + nombres(bloque)))
        # pequeños artefactos: mínimo dos circuitos de 20 A (210.11(C)(1)); el mesón queda repartido en ambos
        pa = sorted(por_cat[PA], key=orden)
        if pa:
            meson = [x for x in pa if x.salida.nota == "mesón"]
            resto = [x for x in pa if x.salida.nota != "mesón"]
            c1, c2 = [], []
            for i, x in enumerate(meson):
                (c1 if i % 2 == 0 else c2).append(x)
            for x in resto:
                (c1 if x.salida.nota == "nevera" else c2).append(x)
            if not c2:
                c2, c1 = c1[1::2], c1[0::2]
            planes.append((PA, c1, "Pequeños artefactos 1 (mesón, nevera)"))
            if c2:
                planes.append((PA, c2, "Pequeños artefactos 2 (mesón, comedor)"))
        if por_cat[BANO]:
            planes.append((BANO, por_cat[BANO], "Tomas baños (GFCI, 20 A)"))
        if por_cat[LAV]:
            planes.append((LAV, por_cat[LAV], "Lavandería (GFCI, 20 A)"))
        for cat, desc in ((ESTUFA, "Estufa eléctrica"), (CALENTADOR, "Calentador eléctrico")):
            for x in por_cat[cat]:
                planes.append((cat, [x], desc))

        n = 0
        for cat, xs, desc in planes:
            if not xs:
                continue
            n += 1
            cid = f"{tab.id}.C-{n:02d}"  # id único en el proyecto; en planos se lee "C-01"
            if cat in (ESTUFA, CALENTADOR):
                va = sum(x.salida.potencia_va or 0 for x in xs)
                i = va / prm.tension_ff_v * (1.25 if cat == CALENTADOR else 1.0)
                prot = max(20.0, _std(i))
                tension, polos = prm.tension_ff_v, 2
            elif cat == ILUM:
                prot, tension, polos = prm.proteccion_iluminacion_a, prm.tension_fn_v, 1
            else:
                prot, tension, polos = prm.proteccion_tomas_a, prm.tension_fn_v, 1
            cal = calibre_para(prot)
            cal_t = calibre_tierra(prot)
            hilos = f"2#{cal} + 1#{cal_t}T" if polos == 2 else f"1F+1N #{cal} + 1#{cal_t}T"
            c = Circuito(id=cid, tablero=tab.id, tipo=TIPO_CIRCUITO[cat], descripcion=desc[:60], tension_v=tension,
                         polos=polos, proteccion_a=prot, conductor=f"{hilos} Cu THHN/THWN-2", calibre_awg=cal,
                         unidad=u, auto=True)
            self.p.circuitos.append(c)
            for x in xs:
                x.salida.circuito = cid
        # interruptores: circuito de las luces que controlan; COM sin circuito
        por_letra = {}
        for x in por_cat[ILUM]:
            if x.salida.control:
                por_letra.setdefault(x.salida.control, x.salida.circuito)
        for x in por_cat[CONTROL]:
            x.salida.circuito = por_letra.get((x.salida.control or "?")[0])
        _balancear(self.p, tab, prm)
        tab.n_circuitos = _tamano_tablero(n + prm.reserva_circuitos)

    # ------------------------------------------------------------ zonas comunes
    def _centro_medicion(self, comunes: list[Recinto], unidades: list[str]) -> None:
        circ = [r for r in comunes if r.uso == UsoRecinto.CIRCULACION] or comunes
        r = max(circ, key=lambda r: self.ctx.poligonos[r.id].area)
        tramos = tramos_de_pared(self.ctx, r.id)
        if not tramos:
            return
        t = max(tramos, key=lambda t: t.longitud)
        paso = 0.55
        largo = paso * len(unidades)
        s0 = t.s0 + max((t.longitud - largo) / 2, 0.2) + paso / 2
        for k, u in enumerate(unidades):
            s = min(s0 + k * paso, t.s1 - 0.2)
            q, n = t.punto(s), t.normal(s)
            pos = (round(q[0] + n[0] * 0.30, 3), round(q[1] + n[1] * 0.30, 3))
            self.medidores[u] = (pos, rotacion_frente(*n), r.id)
            self.p.salidas.append(Salida(id=self._id("S", "salidas"), simbolo="MEDIDOR", posicion=pos,
                                         nivel=self.nivel, rotacion=rotacion_frente(*n), altura=1.60, recinto=r.id,
                                         nota=f"Medidor {u}", auto=True))
        self.inf.avisos.append(
            f"Centro de medición propuesto en {r.nombre} ({len(unidades)} medidores). Ubicación definitiva según "
            "el operador de red (celda de medidores / armario).")

    def _comunes(self, recs: list[Recinto]) -> None:
        prm = self.prm
        props: list[Propuesta] = []
        for r in recs:
            ri = self.ub.iluminacion(r)
            self.inf.calculos_luminicos += ri.calculos
            props += ri.propuestas
            if r.uso == UsoRecinto.CIRCULACION:
                props += self.ub.tomas(r).propuestas
        # control: sensores de movimiento (uso racional de energía) o interruptor
        letra = iter(LETRAS)
        for r in recs:
            luces = [x for x in props if x.categoria == ILUM and x.salida.recinto == r.id]
            if not luces:
                continue
            l = next(letra, "z")
            for x in luces:
                x.salida.control = l
            if prm.sensores_zonas_comunes:
                pg = self.ctx.poligonos[r.id]
                _, _, _, lu, _ = rect_orientado(pg)
                n_s = max(1, math.ceil(lu / 8.0))
                for k in range(n_s):
                    ref = luces[min(len(luces) - 1, k * len(luces) // n_s)].salida.posicion
                    q = (ref[0] + 0.35, ref[1])
                    if not pg.buffer(-0.2).contains(Point(q)):
                        q = (ref[0] - 0.35, ref[1])
                    s = self.ub._salida("SENSOR_MOV", q, None, r.id, r.altura_cielo, 0.0, nota="sensor")
                    s.control = l
                    props.append(Propuesta(s, CONTROL, f"{ART['alumbrado']}; control por sensor de movimiento "
                                                       "(uso racional de energía, RETILAP)"))
            else:
                pr = self.ub.interruptor(r, (self.ctx.puertas_de(r.id) or [None])[0], [l], [])
                if pr:
                    props.append(pr)
        pos_med = self.medidores.get(COMUNES)
        tid = _nombre_tablero(COMUNES, {t.id for t in self.p.tableros})
        if pos_med:
            (x, y), rot, rid = pos_med
            a = math.radians(rot)
            pos = (round(x + math.cos(a) * 0.9, 3), round(y + math.sin(a) * 0.9, 3))
        else:
            r0 = max(recs, key=lambda r: self.ctx.poligonos[r.id].area)
            hit = punto_en_pared(self.ctx, r0.id, self.ctx.poligonos[r0.id].centroid.coords[0])
            pos, rot = (hit[0], rotacion_frente(*hit[1])) if hit else ((0.0, 0.0), 0.0)
        tab = Tablero(id=tid, nombre="Tablero de servicios generales", posicion=pos, nivel=self.nivel, rotacion=rot,
                      unidad=COMUNES, auto=True, sistema="Monofásico trifilar 120/240 V")
        self.p.tableros.append(tab)
        prof = {r.id: i for i, r in enumerate(recs)}
        for x in props:
            self.p.salidas.append(x.salida)
        self._circuitos(COMUNES, tab, props, prof)
        for c in self.p.circuitos:
            if c.tablero == tid and c.tipo == TipoCircuito.ILUMINACION:
                c.descripcion = ("Iluminación zonas comunes " + c.descripcion.replace("Iluminación ", ""))[:60]
        self._tuberia(COMUNES, tab, props, recs, None)
        if COMUNES in self.medidores:
            self._alimentador(COMUNES, tab, None)
        self.inf.cuadros[tab.id] = calcular_cuadro(self.p, tab, prm, recs, self._longitudes, self._alim_m.get(tab.id),
                                                   comunes=True)
        cq = self.inf.cuadros[tab.id]
        self.inf.unidades[COMUNES] = {"tablero": tab.id, "recintos": sorted(r.id for r in recs),
                                      "salidas": dict(_conteo(x.salida.simbolo for x in props)),
                                      "circuitos": len([c for c in self.p.circuitos if c.tablero == tab.id]),
                                      "demanda_va": round(cq.demanda_va),
                                      "proteccion_general_a": cq.proteccion_general_a, "alimentador": cq.alimentador}

    # ------------------------------------------------------------ tubería
    def _tuberia(self, u: str, tab: Tablero, props: list[Propuesta], recs: list[Recinto],
                 entrada: Optional[Vano]) -> None:
        """Árbol de tubería de longitud mínima desde el tablero (Prim), por placa de techo para alumbrado y
        por placa de piso para tomas. Cada tramo lleva los circuitos de todo lo que alimenta aguas abajo; con
        eso se cuentan conductores y se dimensiona el tubo por llenado (Cap. 9)."""
        pols = [self.ctx.poligonos[r.id] for r in recs]
        permitido = unary_union([pg.buffer(0.35, join_style="mitre") for pg in pols])
        if entrada is not None:
            permitido = permitido.union(LineString([entrada.p1, entrada.p2]).buffer(0.5))
        circ = {c.id: c for c in self.p.circuitos if c.tablero == tab.id}
        h_cielo = max((r.altura_cielo for r in recs), default=2.4)
        for sistema, cats, tipo in (("techo", {ILUM}, TipoTuberia.TECHO), ("piso", CATS_PISO, TipoTuberia.PISO)):
            nodos = [x.salida for x in props if x.categoria in cats and x.salida.circuito]
            ctrl = [x.salida for x in props if x.categoria == CONTROL and x.salida.circuito] if sistema == "techo" else []
            if not nodos:
                continue
            raiz = tab.posicion
            padre, d_raiz = _prim(raiz, [s.posicion for s in nodos], permitido)
            # interruptores y sensores: a la luminaria más cercana que controlan
            todos = list(nodos)
            for s in ctrl:
                letras = set(s.control or "")
                cands = [i for i, n in enumerate(nodos) if (n.control or "") in letras] or list(range(len(nodos)))
                j = min(cands, key=lambda i: dist(nodos[i].posicion, s.posicion))
                todos.append(s)
                padre.append(j + 1)
                d_raiz.append(d_raiz[j + 1] + dist(nodos[j].posicion, s.posicion))
            pts = [raiz] + [s.posicion for s in todos]
            n = len(pts)
            hijos = defaultdict(list)
            for i in range(1, n):
                hijos[padre[i]].append(i)
            # circuitos aguas abajo de cada nodo
            abajo: list[set] = [set() for _ in range(n)]
            retornos: list[int] = [0] * n

            def acumular(i):
                if i > 0 and todos[i - 1].circuito:
                    abajo[i].add(todos[i - 1].circuito)
                for h in hijos[i]:
                    acumular(h)
                    abajo[i] |= abajo[h]

            import sys
            sys.setrecursionlimit(max(1000, 4 * n))
            acumular(0)
            for i in range(1, n):
                s = todos[i - 1]
                if s.simbolo.startswith("INT_"):
                    retornos[i] = len(s.control or "a")
            # longitud por circuito (para la regulación): recorrido + bajantes
            bajante = 1.0 if sistema == "techo" else 1.9
            for i in range(1, n):
                c = todos[i - 1].circuito
                if c:
                    self._longitudes[c + "@" + tab.id] = max(self._longitudes.get(c + "@" + tab.id, 0.0),
                                                            d_raiz[i] + bajante + 0.5)
            # tramos -> polilíneas (se unen nodos de paso con los mismos circuitos)
            for i in hijos[0]:
                self._cadena(u, tab, 0, i, pts, hijos, abajo, retornos, circ, tipo, h_cielo if sistema == "techo"
                             else 0.0, sistema)

    def _cadena(self, u, tab, a, b, pts, hijos, abajo, retornos, circ, tipo, elev, sistema):
        ruta = [pts[a], pts[b]]
        cur = b
        while len(hijos[cur]) == 1 and abajo[hijos[cur][0]] == abajo[b] and retornos[hijos[cur][0]] == 0 \
                and retornos[b] == 0:
            cur = hijos[cur][0]
            ruta.append(pts[cur])
        cs = sorted(abajo[b])
        if retornos[b]:
            cal = circ[cs[0]].calibre_awg if cs and cs[0] in circ else "14"
            cond = [cal] * (1 + retornos[b])
            prot = circ[cs[0]].proteccion_a if cs and cs[0] in circ else 15
            texto = f"1F+{retornos[b]}R #{cal} + 1#{calibre_tierra(prot)}T"
        else:
            cond = []
            for c in cs:
                cc = circ.get(c)
                cal = cc.calibre_awg if cc else "12"
                cond += [cal, cal]
            prot = max((circ[c].proteccion_a for c in cs if c in circ), default=20)
            n_c = len(cond)
            cal_max = max(cond, key=lambda x: -int(x) if x.isdigit() else 99) if cond else "12"
            texto = f"{n_c}#{cal_max} + 1#{calibre_tierra(prot)}T"
        cond.append(calibre_tierra(prot))
        diam = diametro_tubo(cond, self.prm.tubo_min, self.prm.llenado_max)
        self.p.tuberias.append(Tuberia(id=self._id("T", "tuberias"), ruta=[(round(x, 3), round(y, 3)) for x, y in ruta],
                                       nivel=self.nivel, tipo=tipo, circuitos=cs, diametro=diam, elevacion=elev,
                                       conductores=texto, unidad=u, auto=True))
        for h in hijos[cur]:
            self._cadena(u, tab, cur, h, pts, hijos, abajo, retornos, circ, tipo, elev, sistema)

    def _alimentador(self, u: str, tab: Tablero, entrada: Optional[Vano]) -> None:
        (mx, my), _, _ = self.medidores[u]
        ruta = [(mx, my)]
        comun = unary_union([pg.buffer(0.3) for rid, pg in self.ctx.poligonos.items()
                             if self.ctx.recintos[rid].comun])
        destino = tab.posicion
        if entrada is not None:
            destino = ((entrada.p1[0] + entrada.p2[0]) / 2, (entrada.p1[1] + entrada.p2[1]) / 2)
        # recorrido ortogonal (en L) por la zona común: se elige el codo que queda más adentro de ella
        codos = [(destino[0], my), (mx, destino[1])]

        def adentro_de_comun(c):
            ln = LineString([(mx, my), c, destino])
            return ln.intersection(comun).length if not comun.is_empty else 0.0

        codo = max(codos, key=adentro_de_comun)
        if dist(codo, (mx, my)) > 0.05 and dist(codo, destino) > 0.05:
            ruta.append(codo)
        if entrada is not None:
            ruta.append(destino)
        ruta.append(tab.posicion)
        L = sum(dist(a, b) for a, b in zip(ruta, ruta[1:])) + 3.0  # + bajantes y reservas
        self._alim_m[tab.id] = L
        tab.alimentado_desde = f"Medidor {u}"
        self.p.tuberias.append(Tuberia(id=self._id("T", "tuberias"), ruta=[(round(x, 3), round(y, 3)) for x, y in ruta],
                                       nivel=self.nivel, tipo=TipoTuberia.ACOMETIDA, circuitos=[f"ALIM {tab.id}"],
                                       diametro=self.prm.tubo_min, elevacion=0.0, unidad=u, auto=True))

    # ------------------------------------------------------------ verificación
    def _verificar(self, grupos: dict[str, list[Recinto]]) -> None:
        V = self.inf.verificacion
        p, prm, ctx = self.p, self.prm, self.ctx
        sal = [s for s in p.salidas if s.nivel == self.nivel]

        def add(u, rec, art, req, res, ok):
            V.append({"unidad": u, "recinto": rec, "articulo": art, "requisito": req, "resultado": res, "cumple": ok})

        tomas_sim = {"TOMA_DOBLE", "TOMA_GFCI"}
        for u, recs in grupos.items():
            for r in recs:
                rs = [s for s in sal if s.recinto == r.id]
                etiqueta = f"{r.nombre} ({r.id})"
                # 210.52(A): ningún punto de pared a más de 1,8 m de una toma
                usos = {z.uso for z in r.zonas} | {r.uso}
                if u != COMUNES and r.uso in (UsoRecinto.SALA, UsoRecinto.COMEDOR, UsoRecinto.ALCOBA,
                                              UsoRecinto.ESTUDIO, UsoRecinto.SALA_COMEDOR) and not r.zonas:
                    peor = _cobertura(ctx, r.id, [s for s in rs if s.simbolo in tomas_sim and s.nota is None])
                    add(u, etiqueta, ART["espaciamiento"], f"Distancia máxima a una toma ≤ {prm.dist_max_toma_m} m",
                        f"{peor:.2f} m", peor <= prm.dist_max_toma_m + 0.05)
                if r.uso == UsoRecinto.BANO:
                    g = [s for s in rs if s.simbolo == "TOMA_GFCI"]
                    lav = [a for a in p.aparatos if a.recinto == r.id and a.tipo == "lavamanos"]
                    if lav:
                        d = min((dist(s.posicion, lav[0].posicion) for s in g), default=99)
                        add(u, etiqueta, ART["bano"], f"Toma GFCI a ≤ {prm.dist_toma_lavamanos_m} m del lavamanos",
                            f"{d:.2f} m", d <= prm.dist_toma_lavamanos_m + 0.25)
                    else:
                        add(u, etiqueta, ART["bano"], "Al menos una toma GFCI junto al lavamanos",
                            f"{len(g)} GFCI (lavamanos no dibujado: verifique su posición)", len(g) >= 1)
                if UsoRecinto.COCINA in usos and u != COMUNES:
                    m = [s for s in rs if s.nota == "mesón"]
                    add(u, etiqueta, ART["meson"], "Tomas en el mesón cada ≤ 1,2 m, GFCI",
                        f"{len(m)} tomas GFCI en el mesón", len(m) >= 1 and all(s.simbolo == "TOMA_GFCI" for s in m))
                if UsoRecinto.ROPAS in usos and u != COMUNES:
                    l = [s for s in rs if s.nota == "lavadora"]
                    add(u, etiqueta, ART["lavanderia"], "Toma para lavadora en circuito de 20 A",
                        f"{len(l)} toma(s)", len(l) >= 1)
                if r.uso == UsoRecinto.CIRCULACION and u != COMUNES:
                    _, _, _, lu, _ = rect_orientado(ctx.poligonos[r.id])
                    if lu >= prm.pasillo_min_m:
                        n = len([s for s in rs if s.simbolo in tomas_sim])
                        add(u, etiqueta, ART["pasillo"], "Pasillo ≥ 3 m con al menos una toma", f"{n} toma(s)", n >= 1)
                # 210.70(A): alumbrado controlado por interruptor
                luces = [s for s in rs if s.simbolo.startswith(("BALA_", "LUM_"))]
                ctrl = [s for s in rs if s.simbolo.startswith("INT_") or s.simbolo == "SENSOR_MOV"]
                add(u, etiqueta, ART["alumbrado"], "Salida de alumbrado controlada por interruptor o sensor",
                    f"{len(luces)} luminarias, {len(ctrl)} controles", bool(luces) and bool(ctrl))
                # 210.8(A): GFCI en baños, mesón y lavandería
                req_gfci = [s for s in rs if s.nota in ("baño", "mesón", "lavadora")]
                if req_gfci:
                    add(u, etiqueta, ART["gfci"], "Tomas de baño, mesón y lavandería con protección GFCI",
                        f"{sum(s.simbolo == 'TOMA_GFCI' for s in req_gfci)}/{len(req_gfci)} GFCI",
                        all(s.simbolo == "TOMA_GFCI" for s in req_gfci))
        # circuitos
        for tid, cq in self.inf.cuadros.items():
            u = cq.unidad
            tipos = [c.tipo for c in p.circuitos if c.tablero == tid]
            if u != COMUNES:
                hay_cocina = any(UsoRecinto.COCINA in ({z.uso for z in r.zonas} | {r.uso}) for r in grupos.get(u, []))
                if hay_cocina:
                    n = tipos.count(TipoCircuito.PEQUENOS_ARTEFACTOS)
                    add(u, tid, ART["pequenos_artefactos"], "Mínimo dos circuitos de 20 A para pequeños artefactos",
                        f"{n} circuitos", n >= 2)
                if any(r.uso == UsoRecinto.BANO for r in grupos.get(u, [])):
                    add(u, tid, ART["bano"], "Circuito de 20 A para las tomas de baños",
                        "sí" if TipoCircuito.BANO in tipos else "no", TipoCircuito.BANO in tipos)
            for fila in cq.filas:
                add(u, f"{tid} {fila['circuito']}", ART["regulacion"],
                    f"Regulación del ramal ≤ {prm.regulacion_max_ramal_pct} %", f"{fila['regulacion_pct']:.2f} %",
                    fila["regulacion_pct"] <= prm.regulacion_max_ramal_pct)
                cap = fila["proteccion_a"] * fila["tension_v"] * (prm.factor_carga_continua
                                                                  if fila["tipo"] == "iluminacion" else 1.0)
                add(u, f"{tid} {fila['circuito']}", "NTC 2050 210.19(A) y 210.20(A)",
                    "Carga del circuito dentro de la capacidad de la protección", f"{fila['va']:.0f} VA de {cap:.0f} VA",
                    fila["va"] <= cap + 1)
            if cq.regulacion_alimentador_pct is not None:
                add(u, tid, ART["regulacion"], f"Regulación del alimentador ≤ {prm.regulacion_max_alimentador_pct} %",
                    f"{cq.regulacion_alimentador_pct:.2f} %",
                    cq.regulacion_alimentador_pct <= prm.regulacion_max_alimentador_pct)
            if cq.total_va >= 1500:
                # con pocos circuitos el mejor reparto posible lo limita el circuito más grande
                mayor = max((f["va"] for f in cq.filas if f["polos"] == 1), default=0.0)
                dif = abs(cq.fase_a_va - cq.fase_b_va)
                add(u, tid, "NTC 2050 210.11(B)",
                    "Cargas repartidas entre fases (desbalance ≤ 20 % o el mínimo posible con los circuitos dados)",
                    f"{cq.desbalance_pct:.1f} %", cq.desbalance_pct <= 20 or dif <= mayor + 1)


# ======================================================================= utilidades
def _conteo(it):
    c = defaultdict(int)
    for x in it:
        c[x] += 1
    return sorted(c.items())


def _std(i: float) -> float:
    from .normas import proteccion_estandar

    return proteccion_estandar(i)


def _nombre_tablero(u: str, usados: set[str]) -> str:
    if u == COMUNES:
        base = "TSG"
    else:
        m = re.search(r"(\d+)\s*$", u)
        base = f"TD-{m.group(1)}" if m else "TD-" + re.sub(r"\W+", "", u)[:6].upper()
    t, k = base, 1
    while t in usados:
        k += 1
        t = f"{base}-{k}"
    return t


def _tamano_tablero(n: int) -> int:
    for t in (4, 6, 8, 12, 18, 24, 30, 36, 42):
        if n <= t:
            return t
    return 42


def _partir(xs: list, max_n: int, max_va: float, va, agrupar=None) -> list[list]:
    """Reparte salidas en circuitos sin superar max_n salidas ni max_va; intenta no partir un recinto."""
    if not xs:
        return []
    bloques: list[list] = []
    if agrupar is None:
        grupos = [[x] for x in xs]
    else:
        grupos, vistos = [], {}
        for x in xs:
            k = agrupar(x)
            if k not in vistos:
                vistos[k] = []
                grupos.append(vistos[k])
            vistos[k].append(x)
    actual: list = []
    for g in grupos:
        if actual and (len(actual) + len(g) > max_n or sum(va(x) for x in actual + g) > max_va):
            if len(g) <= max_n:
                bloques.append(actual)
                actual = []
        for x in g:
            if actual and (len(actual) + 1 > max_n or sum(va(y) for y in actual) + va(x) > max_va):
                bloques.append(actual)
                actual = []
            actual.append(x)
    if actual:
        bloques.append(actual)
    return bloques


def _balancear(p: Proyecto, tab: Tablero, prm: ParametrosDiseno) -> None:
    """Asigna fases A/B: los circuitos de 240 V toman ambas; los de 120 V van a la fase menos cargada."""
    carga = {"A": 0.0, "B": 0.0}
    cs = [c for c in p.circuitos if c.tablero == tab.id]
    va = {c.id: _va_circuito(p, c, tab) for c in cs}
    for c in cs:
        if c.polos == 2:
            c.fase = "AB"
            carga["A"] += va[c.id] / 2
            carga["B"] += va[c.id] / 2
    for c in sorted((c for c in cs if c.polos == 1), key=lambda c: -va[c.id]):
        f = min(carga, key=carga.get)
        c.fase = f
        carga[f] += va[c.id]


def _va_circuito(p: Proyecto, c: Circuito, tab: Tablero) -> float:
    total = 0.0
    for s in p.salidas:
        if s.circuito == c.id and s.recinto is not None and _de_tablero(p, s, tab):
            v = s.potencia_va or 0.0
            total += v / 0.9 if c.tipo == TipoCircuito.ILUMINACION else v
    return total


def _de_tablero(p: Proyecto, s: Salida, tab: Tablero) -> bool:
    if tab.unidad is None:
        return True
    r = next((r for r in p.recintos if r.id == s.recinto), None)
    if r is None:
        return False
    u = r.unidad if (r.unidad and not r.comun) else COMUNES
    return u == tab.unidad


def _prim(raiz, pts: list, permitido) -> tuple[list[int], list[float]]:
    """Árbol de expansión mínima (Prim) desde la raíz. Penaliza tramos que salen de la unidad."""
    todos = [raiz] + list(pts)
    n = len(todos)
    INF = float("inf")
    en = [False] * n
    costo = [INF] * n
    padre = [0] * n
    d_raiz = [0.0] * n
    costo[0] = 0.0
    cache = {}

    def c(i, j):
        k = (min(i, j), max(i, j))
        if k not in cache:
            d = dist(todos[i], todos[j])
            seg = LineString([todos[i], todos[j]]) if d > 1e-6 else None
            fuera = seg is not None and not permitido.contains(seg)
            cache[k] = d * (4.0 if fuera else 1.0)
        return cache[k]

    for _ in range(n):
        i = min((k for k in range(n) if not en[k]), key=lambda k: costo[k])
        en[i] = True
        if i:
            d_raiz[i] = d_raiz[padre[i]] + dist(todos[i], todos[padre[i]])
        for j in range(n):
            if not en[j]:
                cj = c(i, j)
                if cj < costo[j]:
                    costo[j] = cj
                    padre[j] = i
    return padre, d_raiz


def _cobertura(ctx: Contexto, rid: str, tomas: list[Salida]) -> float:
    """Mayor distancia, medida sobre la pared, de un punto de pared útil a la toma más cercana."""
    from .salidas import RETIRO_SIMBOLO

    tramos = tramos_de_pared(ctx, rid)
    peor = 0.0
    for t in tramos:
        if t.longitud < 0.6:
            continue
        ss = []
        for s in tomas:
            a = math.radians(s.rotacion + 90)
            q = (s.posicion[0] - math.cos(a) * RETIRO_SIMBOLO, s.posicion[1] - math.sin(a) * RETIRO_SIMBOLO)
            sp = t.anillo.project(Point(q))
            # abscisa equivalente dentro del tramo (el tramo puede dar la vuelta)
            for cand in (sp, sp + t.anillo.length):
                if t.s0 - 0.05 <= cand <= t.s1 + 0.05 and Point(q).distance(t.anillo) < 0.1:
                    ss.append(cand)
        if not ss:
            peor = max(peor, t.longitud)
            continue
        ss.sort()
        huecos = [ss[0] - t.s0, t.s1 - ss[-1]] + [(b - a) / 2 for a, b in zip(ss, ss[1:])]
        peor = max(peor, max(huecos))
    return peor
