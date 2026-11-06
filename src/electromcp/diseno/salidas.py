"""Ubicación automática de salidas: tomacorrientes (NTC 2050 210.52), iluminación (RETILAP),
interruptores (210.70) y salidas especiales.

Cada salida propuesta lleva una categoría (para armar circuitos) y la regla que la justifica,
que luego aparece en el reporte de verificación.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from shapely.geometry import LineString, Point, Polygon

from ..model import Aparato, Recinto, Salida, UsoRecinto, Vano
from ..symbols import SIMBOLOS
from .geometria import (Contexto, Tramo, adentro, dist, punto_en_pared, rect_orientado, rotacion_frente,
                        tramos_de_pared)
from .normas import ART, ParametrosDiseno, coef_utilizacion

# Categorías de salida -> tipo de circuito
ILUM, TOMAS, PA, BANO, LAV, ESTUFA, CALENTADOR, COM, CONTROL = (
    "ilum", "tomas", "pa", "bano", "lav", "estufa", "calentador", "com", "control")

USOS_SIN_TOMAS = {UsoRecinto.ESCALERA, UsoRecinto.DUCTO, UsoRecinto.PATIO, UsoRecinto.VESTIER}
USOS_GENERALES = {UsoRecinto.SALA, UsoRecinto.COMEDOR, UsoRecinto.SALA_COMEDOR, UsoRecinto.ALCOBA,
                  UsoRecinto.ESTUDIO, UsoRecinto.OTRO, UsoRecinto.TERRAZA, UsoRecinto.BALCON, UsoRecinto.GARAJE}
EXTERIORES = {UsoRecinto.TERRAZA, UsoRecinto.BALCON, UsoRecinto.EXTERIOR, UsoRecinto.PATIO, UsoRecinto.GARAJE}
RETIRO_SIMBOLO = 0.17  # el centro del símbolo queda a esta distancia de la cara del muro


@dataclass
class Propuesta:
    salida: Salida
    categoria: str
    regla: str
    zona: Optional[str] = None


@dataclass
class CalculoLuminico:
    recinto: str
    zona: str
    uso: str
    area_m2: float
    indice_k: float
    cu: float
    potencia_w: int
    flujo_lm: float
    n: int
    e_objetivo_lx: float
    e_calculada_lx: float

    def resumen(self) -> dict:
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


@dataclass
class ResultadoRecinto:
    propuestas: list[Propuesta] = field(default_factory=list)
    calculos: list[CalculoLuminico] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


class Ubicador:
    """Ubica las salidas de un recinto."""

    def __init__(self, ctx: Contexto, prm: ParametrosDiseno, aparatos: list[Aparato], nuevo_id: Callable[[], str]):
        self.ctx = ctx
        self.prm = prm
        self.aparatos = aparatos
        self.nuevo_id = nuevo_id

    # ------------------------------------------------------------ utilidades
    def _salida(self, simbolo: str, q, normal=None, rid: Optional[str] = None, altura: Optional[float] = None,
                potencia: Optional[float] = None, nota: Optional[str] = None) -> Salida:
        sim = SIMBOLOS[simbolo]
        rot = 0.0
        pos = q
        if normal is not None:
            rot = rotacion_frente(*normal)
            pos = (q[0] + normal[0] * RETIRO_SIMBOLO, q[1] + normal[1] * RETIRO_SIMBOLO)
        return Salida(id=self.nuevo_id(), simbolo=simbolo, posicion=(round(pos[0], 3), round(pos[1], 3)),
                      nivel=self.ctx.nivel, rotacion=rot, altura=altura if altura is not None else sim.altura_montaje,
                      potencia_va=potencia if potencia is not None else sim.potencia_va, recinto=rid, nota=nota,
                      auto=True)

    def _aparatos(self, rid: str, *tipos: str) -> list[Aparato]:
        return [a for a in self.aparatos if a.recinto == rid and a.tipo in tipos]

    @staticmethod
    def _zona_en(rec: Recinto, q) -> tuple[UsoRecinto, Optional[str]]:
        if not rec.zonas:
            return rec.uso, None
        pt = Point(q)
        mejor = min(rec.zonas, key=lambda z: Polygon(z.contorno).distance(pt))
        return mejor.uso, mejor.nombre

    # ------------------------------------------------------------ tomacorrientes
    def tomas(self, rec: Recinto) -> ResultadoRecinto:
        res = ResultadoRecinto()
        if rec.vacio or rec.uso in USOS_SIN_TOMAS:
            return res
        rid = rec.id
        prm = self.prm
        usos = {z.uso for z in rec.zonas} | {rec.uso}
        anillo = None
        excluir = []

        # --- mesón de cocina (210.52(C)) y equipos de cocina
        if UsoRecinto.COCINA in usos:
            res_meson, geo_meson = self._meson(rec)
            res.propuestas += res_meson.propuestas
            res.avisos += res_meson.avisos
            excluir += geo_meson
        # --- zona de ropas (210.52(F)): toma de la lavadora
        if UsoRecinto.ROPAS in usos:
            res.propuestas += self._lavadora(rec, excluir)
            for z in rec.zonas:
                if z.uso == UsoRecinto.ROPAS:
                    excluir.append(Polygon(z.contorno).buffer(0.05))
        for z in rec.zonas:
            if z.uso in (UsoRecinto.VESTIER,):
                excluir.append(Polygon(z.contorno).buffer(-0.01))
        # --- baños (210.52(D))
        if rec.uso == UsoRecinto.BANO:
            res.propuestas += self._bano(rec)
            return res
        if rec.uso == UsoRecinto.ROPAS:
            return res
        # --- pasillos (210.52(H))
        if rec.uso == UsoRecinto.CIRCULACION:
            _, _, _, lu, _ = rect_orientado(self.ctx.poligonos[rid])
            if lu >= prm.pasillo_min_m:
                ts = tramos_de_pared(self.ctx, rid)
                if ts:
                    t = max(ts, key=lambda t: t.longitud)
                    s = (t.s0 + t.s1) / 2
                    res.propuestas.append(Propuesta(
                        self._salida("TOMA_DOBLE", t.punto(s), t.normal(s), rid, prm.altura_toma_m,
                                     prm.va_por_toma, nota="pasillo"),
                        TOMAS, f"{ART['pasillo']}: pasillo de {lu:.1f} m"))
            return res
        # --- espacio de pared general (210.52(A))
        tramos = tramos_de_pared(self.ctx, rid, excluir=excluir or None)
        for t in tramos:
            if t.longitud < prm.espacio_pared_min_m:
                continue
            for s in self._posiciones(t, prm.dist_max_toma_m):
                q = t.punto(s)
                uso_z, nombre_z = self._zona_en(rec, q)
                if uso_z in (UsoRecinto.VESTIER, UsoRecinto.ROPAS):
                    continue
                cat = PA if uso_z in (UsoRecinto.COCINA, UsoRecinto.COMEDOR) else TOMAS
                exterior = uso_z in EXTERIORES
                simb = "TOMA_GFCI" if exterior else "TOMA_DOBLE"
                regla = ART["espaciamiento"] + f": tramo de pared de {t.longitud:.2f} m"
                if cat == PA:
                    regla += f"; {ART['pequenos_artefactos']} (zona {nombre_z or uso_z.value})"
                res.propuestas.append(Propuesta(
                    self._salida(simb, q, t.normal(s), rid, prm.altura_toma_m, prm.va_por_toma), cat, regla,
                    nombre_z))
        if prm.comunicaciones:
            res.propuestas += self._com(rec, [p for p in res.propuestas if p.categoria in (TOMAS, PA)])
        return res

    def _posiciones(self, t: Tramo, dmax: float) -> list[float]:
        """Posiciones (abscisa s) sobre el tramo tales que ningún punto quede a más de dmax de una toma.

        Se arranca con n = ⌈L / 2·dmax⌉ y se alejan las tomas de las esquinas; si al correrlas se pierde
        la cobertura, se agrega una toma más (verificación explícita de 210.52(A)(1)).
        """
        L = t.longitud
        n = max(1, math.ceil(L / (2 * dmax) - 1e-9))
        for _ in range(6):
            pos = []
            for i in range(n):
                s = t.s0 + (i + 0.5) * L / n
                if t.dist_esquina(s) < self.prm.dist_esquina_m:
                    for d in (0.05 * k for k in range(1, 9)):
                        for sg in (1, -1):
                            s2 = s + sg * d
                            if t.s0 + 0.1 <= s2 <= t.s1 - 0.1 and t.dist_esquina(s2) >= self.prm.dist_esquina_m:
                                s = s2
                                break
                        else:
                            continue
                        break
                pos.append(s)
            pos.sort()
            huecos = [pos[0] - t.s0, t.s1 - pos[-1]] + [(b - a) / 2 for a, b in zip(pos, pos[1:])]
            if max(huecos) <= dmax + 1e-6:
                return pos
            n += 1
        return pos

    def _meson(self, rec: Recinto) -> tuple[ResultadoRecinto, list]:
        res = ResultadoRecinto()
        prm = self.prm
        rid = rec.id
        pg = self.ctx.poligonos[rid]
        equipos = self._aparatos(rid, "lavaplatos", "estufa")
        tramos = tramos_de_pared(self.ctx, rid)
        anillo = tramos[0].anillo if tramos else None
        if anillo is None:
            return res, []
        Lr = anillo.length
        # intervalo del mesón sobre el perímetro: cada equipo ±0,45 m, y se unen si quedan a < 1,2 m
        ints = []
        for a in equipos:
            s = anillo.project(Point(a.posicion))
            w = max(a.tamano or (0.6, 0.6)) / 2 + 0.25
            ints.append([s - w, s + w, a])
        if not ints:
            # sin lavaplatos ni estufa dibujados: mesón supuesto en la pared más larga de la zona de cocina
            zonas = [Polygon(z.contorno) for z in rec.zonas if z.uso == UsoRecinto.COCINA]
            zona = zonas[0].buffer(0.3) if zonas else self.ctx.poligonos[rid].buffer(0.3)
            mejor = None
            for t in tramos:
                s, ini = t.s0, None
                while s <= t.s1:
                    dentro = zona.contains(Point(t.punto(s)))
                    if dentro and ini is None:
                        ini = s
                    if (not dentro or s + 0.05 > t.s1) and ini is not None:
                        if mejor is None or s - ini > mejor[1] - mejor[0]:
                            mejor = (ini, s)
                        ini = None
                    s += 0.05
            if mejor is None or mejor[1] - mejor[0] < 0.6:
                res.avisos.append(f"{rec.nombre}: no se pudo ubicar el mesón; ubique a mano sus tomas GFCI.")
                return res, []
            c = (mejor[0] + mejor[1]) / 2
            w = min(mejor[1] - mejor[0], 2.4) / 2
            ints.append([c - w + 0.1, c + w - 0.1, None])
            res.avisos.append(f"{rec.nombre}: lavaplatos y estufa no dibujados; se supuso el mesón en la pared más "
                              "larga de la cocina. Verifique.")
        ints.sort(key=lambda x: x[0])
        grupos = [ints[0][:2]]
        for s0, s1, _ in ints[1:]:
            if s0 - grupos[-1][1] < 1.2:
                grupos[-1][1] = max(grupos[-1][1], s1)
            else:
                grupos.append([s0, s1])
        estufas = [anillo.project(Point(a.posicion)) for a in equipos if a.tipo == "estufa"]  # noqa: E501
        lavaplatos = [anillo.project(Point(a.posicion)) for a in equipos if a.tipo == "lavaplatos"]
        geo = []
        t = Tramo(anillo, 0, Lr)
        for s0, s1 in grupos:
            Lm = s1 - s0
            n = max(1, math.ceil(Lm / (2 * prm.dist_max_meson_m) - 1e-9))
            if Lm >= 1.0:
                n = max(n, 2)  # el mesón queda servido por los dos circuitos de pequeños artefactos
            for i in range(n):
                s = s0 + (i + 0.5) * Lm / n
                # no detrás de la estufa ni del grifo: se corre hasta 0,35 m dentro del mesón
                for c, r in [(e, 0.40) for e in estufas] + [(l, 0.30) for l in lavaplatos]:
                    if abs(s - c) < r:
                        s2 = c + math.copysign(r, s - c if s != c else 1)
                        s = min(max(s2, s0 + 0.1), s1 - 0.1)
                q = t.punto(s)
                res.propuestas.append(Propuesta(
                    self._salida("TOMA_GFCI", q, t.normal(s), rid, prm.altura_toma_meson_m, prm.va_por_toma,
                                 nota="mesón"),
                    PA, f"{ART['meson']}: mesón de {Lm:.2f} m, ningún punto a más de {prm.dist_max_meson_m} m; "
                        f"GFCI {ART['gfci']}(6)", "Cocina"))
            pts = [t.punto(s0 + k * (s1 - s0) / 10) for k in range(11)]
            geo.append(LineString(pts).buffer(0.25))
        # nevera: salida especial (puede ir en un circuito de pequeños artefactos, 210.52(B)(1) Exc. 2)
        neveras = self._aparatos(rid, "nevera")
        if neveras:
            objetivo = neveras[0].posicion
        else:
            s_fin = grupos[-1][1] + 0.45
            objetivo = t.punto(s_fin)
            res.avisos.append(f"{rec.nombre}: no se encontró la nevera en el plano; su salida se ubicó al final del "
                              "mesón. Verifique la posición.")
        hit = punto_en_pared(self.ctx, rid, objetivo, tramos=tramos)
        if hit:
            q, nrm, _ = hit
            res.propuestas.append(Propuesta(
                self._salida("SALIDA_ESPECIAL", q, nrm, rid, 1.20, prm.va_nevera, nota="nevera"),
                PA, f"Nevera en circuito de pequeños artefactos ({ART['pequenos_artefactos']})", "Cocina"))
        if prm.estufa == "electrica":
            est = self._aparatos(rid, "estufa")
            obj = est[0].posicion if est else t.punto((grupos[0][0] + grupos[0][1]) / 2)
            hit = punto_en_pared(self.ctx, rid, obj, tramos=tramos)
            if hit:
                q, nrm, _ = hit
                res.propuestas.append(Propuesta(
                    self._salida("TOMA_220", q, nrm, rid, 0.60, prm.potencia_estufa_va, nota="estufa eléctrica"),
                    ESTUFA, "Estufa eléctrica en circuito individual 240 V (210.19(A)(3), 220.55)", "Cocina"))
        return res, geo

    def _lavadora(self, rec: Recinto, excluir: list) -> list[Propuesta]:
        rid = rec.id
        prm = self.prm
        lav = self._aparatos(rid, "lavadora") or self._aparatos(rid, "lavadero")
        if lav:
            obj = lav[0].posicion
        else:
            zs = [z for z in rec.zonas if z.uso == UsoRecinto.ROPAS]
            obj = Polygon(zs[0].contorno).centroid.coords[0] if zs else self.ctx.poligonos[rid].centroid.coords[0]
        hit = punto_en_pared(self.ctx, rid, obj)
        out = []
        if hit:
            q, nrm, _ = hit
            out.append(Propuesta(self._salida("TOMA_GFCI", q, nrm, rid, 1.10, prm.va_lavadora, nota="lavadora"),
                                 LAV, f"{ART['lavanderia']}; GFCI {ART['gfci']}(10)", "Ropas"))
            if prm.calentador == "electrico":
                out.append(Propuesta(
                    self._salida("TOMA_220", (q[0] - nrm[1] * 0.6, q[1] + nrm[0] * 0.6), nrm, rid, 1.50,
                                 prm.potencia_calentador_va, nota="calentador"),
                    CALENTADOR, "Calentador eléctrico en circuito individual (422.13: carga continua al 125 %)", "Ropas"))
        return out

    def _bano(self, rec: Recinto) -> list[Propuesta]:
        rid = rec.id
        prm = self.prm
        duchas = [a for a in self._aparatos(rid, "ducha") if max(a.tamano or (1, 1)) > 0.5]
        evitar = [(a.posicion, max(a.tamano or (0.9, 0.9)) / 2 + prm.retiro_ducha_m) for a in duchas]
        lavamanos = self._aparatos(rid, "lavamanos")
        inodoros = self._aparatos(rid, "inodoro")
        pg = self.ctx.poligonos[rid]
        if lavamanos:
            objetivo = lavamanos[0].posicion
            regla = f"{ART['bano']}: a menos de {prm.dist_toma_lavamanos_m} m del lavamanos"
        elif inodoros and duchas:
            (ix, iy), (dx, dy) = inodoros[0].posicion, duchas[0].posicion
            d = math.hypot(ix - dx, iy - dy) or 1.0
            objetivo = (ix + (ix - dx) / d * 0.7, iy + (iy - dy) / d * 0.7)
            regla = f"{ART['bano']}: lavamanos no dibujado; toma al lado opuesto a la ducha"
        else:
            objetivo = pg.centroid.coords[0]
            regla = f"{ART['bano']}: lavamanos no dibujado"
        hit = punto_en_pared(self.ctx, rid, objetivo, evitar=evitar)
        out = []
        if hit:
            q, nrm, _ = hit
            out.append(Propuesta(self._salida("TOMA_GFCI", q, nrm, rid, prm.altura_toma_bano_m, prm.va_por_toma,
                                              nota="baño"), BANO, regla + f"; GFCI {ART['gfci']}(1)"))
        return out

    def _com(self, rec: Recinto, tomas: list[Propuesta]) -> list[Propuesta]:
        """Salida de comunicaciones junto a una toma: sala/estudio (TV-datos) y alcobas."""
        quiere = []
        if rec.zonas:
            quiere = [z.nombre for z in rec.zonas if z.uso in (UsoRecinto.SALA, UsoRecinto.ESTUDIO, UsoRecinto.ALCOBA)]
        elif rec.uso in (UsoRecinto.SALA, UsoRecinto.ESTUDIO, UsoRecinto.ALCOBA, UsoRecinto.SALA_COMEDOR):
            quiere = [None]
        out = []
        puertas = self.ctx.puertas_de(rec.id)
        for zona in quiere:
            cand = [p for p in tomas if p.zona == zona] if zona else tomas
            if not cand:
                continue
            # la toma más lejana de la puerta (pared de la cama o del televisor)
            ref = (puertas[0].p1 if puertas else self.ctx.poligonos[rec.id].centroid.coords[0])
            t = max(cand, key=lambda p: dist(p.salida.posicion, ref))
            x, y = t.salida.posicion
            a = math.radians(t.salida.rotacion)
            ux, uy = math.cos(a), math.sin(a)  # dirección del muro
            q = (x + ux * 0.40, y + uy * 0.40)
            s = self._salida("COM", q, None, rec.id, 0.30, None, nota="TV/datos")
            s.rotacion = t.salida.rotacion
            out.append(Propuesta(s, COM, "Salida de telecomunicaciones (RITEL)", zona))
        return out

    # ------------------------------------------------------------ iluminación
    def iluminacion(self, rec: Recinto) -> ResultadoRecinto:
        res = ResultadoRecinto()
        if rec.vacio or rec.uso in (UsoRecinto.DUCTO,):
            return res
        prm = self.prm
        pg_r = self.ctx.poligonos[rec.id]
        partes = [(z.nombre, z.uso, Polygon(z.contorno).intersection(pg_r)) for z in rec.zonas] or \
                 [(rec.nombre, rec.uso, pg_r)]
        h = max(rec.altura_cielo - prm.plano_trabajo_m, 0.8)
        for nombre, uso, pg in partes:
            if pg.is_empty or pg.area < 0.3:
                continue
            if pg.geom_type != "Polygon":
                pg = max(pg.geoms, key=lambda g: g.area)
            A = pg.area
            _, _, _, lu, lv = rect_orientado(pg)
            k = lu * lv / (h * (lu + lv))
            cu = coef_utilizacion(k)
            e = prm.lux(uso)
            # Se prueban las potencias disponibles: N por iluminancia (se acepta 10 % por debajo del valor medio)
            # y N mínimo por uniformidad (separación ≤ espaciamiento máximo); gana el menor costo
            # energético + de instalación (W totales + 15 W equivalentes por salida).
            s_max = prm.espaciamiento_max_m
            n_unif = max(1, math.ceil(A / (s_max * s_max) - 0.15))
            elegido = None
            for w in prm.potencias_bala_w:
                flujo = w * prm.lumenes_por_w
                n_lux = max(1, math.ceil(0.9 * e * A / (flujo * cu * prm.factor_mantenimiento) - 1e-6))
                n = max(n_lux, n_unif)
                costo = n * (w + 15)
                if elegido is None or costo < elegido[3] - 1e-9:
                    elegido = (w, flujo, n, costo)
            w, flujo, n, _ = elegido
            pts = self._rejilla(pg, n)
            sim = f"BALA_LED_{w}W" if f"BALA_LED_{w}W" in SIMBOLOS else "BALA_LED_12W"
            for q in pts:
                res.propuestas.append(Propuesta(
                    self._salida(sim, q, None, rec.id, rec.altura_cielo, float(w)), ILUM,
                    f"{ART['iluminancia']}: {e:.0f} lx; {ART['metodo_lumenes']}", nombre))
            e_calc = len(pts) * flujo * cu * prm.factor_mantenimiento / A
            res.calculos.append(CalculoLuminico(rec.id, nombre, uso.value, A, k, cu, w, flujo, len(pts), e, e_calc))
        if "ventilacion_mecanica" in rec.notas or (rec.uso == UsoRecinto.BANO and not self._tiene_ventana(rec.id)):
            duchas = [a for a in self._aparatos(rec.id, "ducha") if max(a.tamano or (1, 1)) > 0.5]
            c = pg_r.centroid.coords[0]
            obj = duchas[0].posicion if duchas else c
            q = adentro(pg_r, ((obj[0] + c[0]) / 2, (obj[1] + c[1]) / 2), 0.3)
            motivo = "nota 'Ven. Mecánica' del plano" if "ventilacion_mecanica" in rec.notas else "baño sin ventana"
            res.propuestas.append(Propuesta(
                self._salida("EXTRACTOR", q, None, rec.id, rec.altura_cielo, prm.va_extractor, nota="extractor"),
                ILUM, f"Extractor por ventilación mecánica ({motivo})", rec.nombre))
        return res

    def _tiene_ventana(self, rid: str) -> bool:
        return any(rid in v.recintos for v in self.ctx.ventanas)

    def _rejilla(self, pg: Polygon, n: int) -> list:
        o, u, v, lu, lv = rect_orientado(pg)
        nu = max(1, round(math.sqrt(n * lu / max(lv, 0.1))))
        nv = max(1, math.ceil(n / nu))
        while nu * nv - n >= nu and nv > 1:
            nv -= 1
        pts = []
        for i in range(nu):
            for j in range(nv):
                a = (i + 0.5) * lu / nu
                b = (j + 0.5) * lv / nv
                q = (o[0] + u[0] * a + v[0] * b, o[1] + u[1] * a + v[1] * b)
                q = adentro(pg, q, 0.30)
                if all(dist(q, r) > 0.5 for r in pts):
                    pts.append(q)
        return pts[:max(n, 1)] if len(pts) > n + nu else pts

    # ------------------------------------------------------------ control
    def interruptor(self, rec: Recinto, puerta: Optional[Vano], letras: list[str],
                    otros: list) -> Optional[Propuesta]:
        """Interruptor en el lado de la chapa de la puerta de acceso al recinto, h = 1,20 m (210.70(A))."""
        if not letras:
            return None
        rid = rec.id
        pg = self.ctx.poligonos[rid]
        evitar = [(s, 0.30) for s in otros]
        if puerta is not None:
            (x1, y1), (x2, y2) = puerta.p1, puerta.p2
            L = math.hypot(x2 - x1, y2 - y1) or 1.0
            ux, uy = (x2 - x1) / L, (y2 - y1) / L
            objetivo = (x2 + ux * 0.25, y2 + uy * 0.25)
            mid = ((x1 + x2) / 2, (y1 + y2) / 2)
            evitar.append((mid, L / 2 + 0.06))
        else:
            objetivo = pg.centroid.coords[0]
        hit = punto_en_pared(self.ctx, rid, objetivo, evitar=evitar)
        if hit is None:
            return None
        q, nrm, _ = hit
        simb = {1: "INT_SENCILLO", 2: "INT_DOBLE"}.get(len(letras), "INT_TRIPLE")
        s = self._salida(simb, q, nrm, rid, self.prm.altura_interruptor_m, 0.0, nota="interruptor")
        s.control = "".join(letras[:3])
        return Propuesta(s, CONTROL, f"{ART['alumbrado']}: salida de alumbrado controlada por interruptor de pared")
