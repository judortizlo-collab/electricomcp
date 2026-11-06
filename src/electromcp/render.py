"""Traduce el modelo del proyecto a planos (DXF o AutoCAD en vivo).

Cada plano ("lámina") replica la organización de los planos de referencia:
un nivel por lámina, separado en ILUMINACIÓN y TOMAS, con el cuadro de
convenciones a la derecha (con cantidades contadas automáticamente), el rótulo
abajo a la derecha y el marco del pliego. Escala de impresión 1:50 por defecto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

from .backends.base import Backend
from .layers import CAPAS, TIPOS_LINEA
from .model import Proyecto, TipoCircuito, TipoTuberia, etiqueta_circuito
from .symbols import SIMBOLOS, caja

TipoLamina = Literal["loc_iluminacion", "loc_tomas", "iluminacion", "tomas", "completo", "cuadros"]
# Juego completo, en el orden del formato de referencia (ELE-01 a ELE-05): localización sin tubería,
# cuadros y unifilares, y constructivos con tubería, conductores y retornos.
JUEGO_COMPLETO: tuple = ("loc_iluminacion", "loc_tomas", "cuadros", "iluminacion", "tomas")

CAPA_TUBERIA = {
    TipoTuberia.MURO: "E-TUB-MURO",
    TipoTuberia.PISO: "E-TUB-PISO",
    TipoTuberia.TECHO: "E-TUB-TECHO",
    TipoTuberia.COMUNICACIONES: "COM-TUBERIA",
    TipoTuberia.ACOMETIDA: "E-ACOMETIDA",
}

GRUPOS_LAMINA = {
    "loc_iluminacion": {"iluminacion", "tableros"},
    "loc_tomas": {"tomas", "fuerza", "com", "tableros"},
    "iluminacion": {"iluminacion", "tableros"},
    "tomas": {"tomas", "fuerza", "com", "tableros"},
    "completo": {"iluminacion", "tomas", "fuerza", "com", "tableros"},
}

TITULO_LAMINA = {
    "loc_iluminacion": "LOCALIZACIÓN DE SALIDAS DE ILUMINACIÓN E INTERRUPTORES",
    "loc_tomas": "LOCALIZACIÓN DE TOMACORRIENTES, FUERZA Y COMUNICACIONES",
    "iluminacion": "CONSTRUCTIVO DE ILUMINACIÓN: TUBERÍA, CONDUCTORES Y RETORNOS",
    "tomas": "CONSTRUCTIVO DE TOMAS: TUBERÍA Y CONDUCTORES",
    "completo": "REDES ELÉCTRICAS",
    "cuadros": "CUADROS DE CARGA Y DIAGRAMAS UNIFILARES",
}


def num(x: float, dec: int = 2) -> str:
    """Formato colombiano: coma decimal."""
    return f"{x:.{dec}f}".replace(".", ",")


@dataclass
class Pliego:
    """Pliego en unidades de dibujo (m) para una escala dada."""

    ancho_mm: float = 1000.0  # pliego de 100 x 70,7 cm, como los planos de referencia
    alto_mm: float = 707.0
    escala: float = 50.0

    @property
    def ancho(self) -> float:
        return self.ancho_mm * self.escala / 1000.0

    @property
    def alto(self) -> float:
        return self.alto_mm * self.escala / 1000.0

    def mm(self, v: float) -> float:
        """Convierte mm de papel a metros de dibujo."""
        return v * self.escala / 1000.0


class Renderizador:
    def __init__(self, proyecto: Proyecto, backend: Backend, pliego: Optional[Pliego] = None):
        self.p = proyecto
        self.b = backend
        self.pl = pliego or Pliego()
        self._preparado = False

    # ------------------------------------------------------------------ API
    def preparar(self) -> None:
        if self._preparado:
            return
        self.b.preparar(CAPAS.values(), TIPOS_LINEA)
        for s in SIMBOLOS.values():
            self.b.definir_bloque(s)
        self._preparado = True

    def dibujar_juego(self, laminas: tuple[TipoLamina, ...] = ("iluminacion", "tomas")) -> str:
        """Dibuja todas las láminas (cada nivel x cada tipo) una al lado de otra."""
        self.preparar()
        # orden de las láminas = orden pedido; los cuadros pueden ocupar varios pliegos
        trabajos: list = []
        for tipo in laminas:
            if tipo == "cuadros":
                from .render_cuadros import paginar

                trabajos += [("cuadros", h) for h in paginar(self.p, self.pl)]
            else:
                trabajos += [(tipo, nivel) for nivel in self.p.niveles]
        total = len(trabajos)
        for n, (tipo, dato) in enumerate(trabajos, 1):
            origen = ((n - 1) * (self.pl.ancho + self.pl.mm(100)), 0.0)
            if tipo == "cuadros":
                dato.dibujar(self, origen)
                self._rotulo(self.p.niveles[0], "cuadros", f"{n:02d} DE {total:02d}",
                             (origen[0] + self.pl.ancho - self.pl.mm(15), origen[1] + self.pl.mm(15)))
                self._marco(*origen)
            else:
                self.dibujar_lamina(dato, tipo, origen, f"{n:02d} DE {total:02d}")
        return self.b.finalizar()

    def dibujar_lamina(self, nivel: str, tipo: TipoLamina, origen=(0.0, 0.0),
                       plano_n: Optional[str] = None) -> None:
        self.preparar()
        ox, oy = origen
        pl = self.pl
        # Zona útil de dibujo: a la izquierda de la columna de convenciones
        margen = pl.mm(15)
        col_der = pl.mm(240)
        zona = (ox + margen, oy + margen, ox + pl.ancho - col_der - margen, oy + pl.alto - margen)

        # Encaje del contenido del nivel en la zona útil (traslación, nunca escala)
        bb = self._bbox(nivel)
        if bb:
            cx = (bb[0] + bb[2]) / 2
            cy = (bb[1] + bb[3]) / 2
            dx = (zona[0] + zona[2]) / 2 - cx
            dy = (zona[1] + zona[3]) / 2 - cy
        else:
            dx, dy = zona[0], zona[1]
        self._dx, self._dy = dx, dy

        grupos = GRUPOS_LAMINA[tipo]
        self._tipo_actual = tipo
        localizacion = tipo.startswith("loc_")
        self._arquitectura(nivel)
        if not localizacion:
            self._tuberias(nivel, tipo)
        self._salidas(nivel, grupos)
        self._tableros(nivel)
        conteo = self._conteo(nivel, grupos)
        y_fin = self._convenciones(conteo, (ox + pl.ancho - col_der, oy + pl.alto - margen), constructivo=not localizacion)
        if localizacion:
            self._cuadro_recintos(nivel, tipo, (ox + pl.ancho - col_der, y_fin - pl.mm(12)), oy + margen + pl.mm(160))
        self._rotulo(nivel, tipo, plano_n, (ox + pl.ancho - margen, oy + margen))
        self._marco(ox, oy)

    # ------------------------------------------------------------------ partes
    def _t(self, pt):
        return (pt[0] + self._dx, pt[1] + self._dy)

    def _bbox(self, nivel: str):
        xs: list[float] = []
        ys: list[float] = []
        for r in self.p.recintos:
            if r.nivel == nivel:
                xs += [q[0] for q in r.contorno]
                ys += [q[1] for q in r.contorno]
        for a in self.p.arquitectura:
            if a.nivel == nivel:
                xs += [q[0] for q in a.puntos]
                ys += [q[1] for q in a.puntos]
        for s in self.p.salidas:
            if s.nivel == nivel:
                xs.append(s.posicion[0])
                ys.append(s.posicion[1])
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))

    def _arquitectura(self, nivel: str) -> None:
        for a in self.p.arquitectura:
            if a.nivel == nivel:
                self.b.polilinea([self._t(q) for q in a.puntos], a.capa, a.cerrado)
        for r in self.p.recintos:
            if r.nivel != nivel:
                continue
            if not any(a.nivel == nivel for a in self.p.arquitectura):
                # Sin arquitectura importada: se dibuja el contorno del recinto como muro
                self.b.polilinea([self._t(q) for q in r.contorno], "ARQ-MUROS", True)
            cx, cy = self._t(r.centroide)
            self.b.texto(r.nombre.upper(), (cx, cy + 0.15), 0.20, "ARQ-RECINTOS", centrado=True)
            self.b.texto(f"{num(r.area)} m2", (cx, cy - 0.15), 0.15, "ARQ-RECINTOS", centrado=True)

    def _tipo_tuberia_en_lamina(self, circuitos: list[str], tipo: TipoLamina) -> bool:
        if tipo == "completo":
            return True
        if not circuitos:
            return True
        tipos = {c.tipo for c in self.p.circuitos if c.id in circuitos}
        if not tipos:
            return True
        es_ilum = tipos == {TipoCircuito.ILUMINACION}
        return es_ilum if tipo == "iluminacion" else not es_ilum

    def _tuberias(self, nivel: str, tipo: TipoLamina) -> None:
        for t in self.p.tuberias:
            if t.nivel != nivel or not self._tipo_tuberia_en_lamina(t.circuitos, tipo):
                continue
            if t.tipo in (TipoTuberia.COMUNICACIONES, TipoTuberia.ACOMETIDA) and tipo == "iluminacion":
                continue
            pts = [self._t(q) for q in t.ruta]
            if t.auto and t.tipo in (TipoTuberia.TECHO, TipoTuberia.PISO):
                # estilo de los planos de referencia: cada tramo como arco suave entre cajas,
                # con las marcas de conductores en el tramo más largo
                k_max = max(range(len(pts) - 1), key=lambda k: _d(pts[k], pts[k + 1]))
                tableros = [self._t(tb.posicion) for tb in self.p.tableros if tb.nivel == nivel]
                for k, (a, b) in enumerate(zip(pts, pts[1:])):
                    arco = _arco(a, b, 0.12)
                    self.b.polilinea(arco, CAPA_TUBERIA[t.tipo])
                    if k == 0 and any(_d(a, q) < 0.05 for q in tableros):
                        self._flecha(arco[1], arco[0], CAPA_TUBERIA[t.tipo])
                    if k == k_max and _d(a, b) > 0.6:
                        self._marcas(arco, t.conductores, CAPA_TUBERIA[t.tipo])
            else:
                self.b.polilinea(pts, CAPA_TUBERIA[t.tipo])
            largo = sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(pts, pts[1:]))
            if t.auto and t.circuitos:
                # tubería del motor: se rotulan los tramos largos con más de un circuito y los alimentadores
                if t.tipo != TipoTuberia.ACOMETIDA and (largo < 1.2 or len(t.circuitos) < 2):
                    continue
                i = max(range(len(pts) - 1),
                        key=lambda k: (pts[k + 1][0] - pts[k][0]) ** 2 + (pts[k + 1][1] - pts[k][1]) ** 2)
                (x1, y1), (x2, y2) = pts[i], pts[i + 1]
                ang = math.degrees(math.atan2(y2 - y1, x2 - x1))
                if ang > 90 or ang <= -90:
                    ang -= 180 if ang > 0 else -180
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                if t.tipo in (TipoTuberia.TECHO, TipoTuberia.PISO):
                    mx, my = _arco((x1, y1), (x2, y2), 0.12)[4]  # sobre la cresta del arco
                nx, ny = -math.sin(math.radians(ang)), math.cos(math.radians(ang))
                etq = ", ".join(etiqueta_circuito(c) for c in t.circuitos)
                if t.conductores and t.tipo != TipoTuberia.ACOMETIDA:
                    etq += "  " + t.conductores
                if t.diametro != '1/2"' or t.tipo == TipoTuberia.ACOMETIDA:
                    etq += f"  %%c{t.diametro}"
                self.b.texto(etq, (mx + nx * 0.10, my + ny * 0.10), 0.08, "E-CIRCUITOS", centrado=True,
                             rot_grados=ang)
                continue
            if t.circuitos:
                # Etiqueta en el tramo más largo
                i = max(range(len(pts) - 1),
                        key=lambda k: (pts[k + 1][0] - pts[k][0]) ** 2 + (pts[k + 1][1] - pts[k][1]) ** 2)
                (x1, y1), (x2, y2) = pts[i], pts[i + 1]
                vertical = abs(x2 - x1) < abs(y2 - y1)
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                etiqueta = ", ".join(t.circuitos) + f"  %%c{t.diametro}"
                self.b.texto(etiqueta, (mx + (0.12 if vertical else 0), my + (0 if vertical else 0.12)),
                             0.09, "E-CIRCUITOS", rot_grados=90 if vertical else 0)

    def _flecha(self, desde, hacia, capa: str) -> None:
        """Punta de flecha rellena en `hacia` (llegada del circuito al tablero)."""
        L = _d(desde, hacia) or 1.0
        ux, uy = (hacia[0] - desde[0]) / L, (hacia[1] - desde[1]) / L
        nx, ny = -uy, ux
        base = (hacia[0] - ux * 0.16, hacia[1] - uy * 0.16)
        self.b.relleno_solido([hacia, (base[0] + nx * 0.05, base[1] + ny * 0.05),
                               (base[0] - nx * 0.05, base[1] - ny * 0.05)], capa)

    def _marcas(self, arco: list, conductores: str, capa: str) -> None:
        """Rayitas sobre la tubería: una larga por fase o retorno, una corta por neutro, tierra con punto."""
        import re

        f = n = r = 0
        m = re.match(r"\s*1N\+(\d+)R", conductores or "")
        if m:
            n, r = 1, int(m.group(1))
        else:
            m = re.match(r"\s*1F\+1N", conductores or "")
            m2 = re.match(r"\s*(\d+)#", conductores or "")
            if m:
                f, n = 1, 1
            elif m2:
                k = int(m2.group(1))
                f, n = (k + 1) // 2, k // 2
        marcas = ["L"] * (f + r) + ["C"] * n + ["T"]
        i = len(arco) // 2
        (xa, ya), (xb, yb) = arco[i - 1], arco[i + 1]
        L = _d((xa, ya), (xb, yb)) or 1.0
        ux, uy = (xb - xa) / L, (yb - ya) / L
        nx, ny = -uy, ux
        xc, yc = arco[i]
        paso = 0.06
        x0 = xc - ux * paso * (len(marcas) - 1) / 2
        y0 = yc - uy * paso * (len(marcas) - 1) / 2
        for j, tipo in enumerate(marcas):
            px, py = x0 + ux * paso * j, y0 + uy * paso * j
            lg = 0.09 if tipo != "C" else 0.05
            # rayita inclinada 60° respecto al tubo
            dx, dy = nx * lg + ux * lg * 0.5, ny * lg + uy * lg * 0.5
            self.b.linea((px - dx, py - dy), (px + dx, py + dy), capa)
            if tipo == "T":
                self.b.circulo((px + dx, py + dy), 0.015, capa)

    def _salidas(self, nivel: str, grupos: set[str]) -> None:
        for s in self.p.salidas:
            if s.nivel != nivel:
                continue
            sim = SIMBOLOS[s.simbolo]
            if sim.grupo not in grupos:
                continue
            attrs = {}
            if "CIRCUITO" in sim.atributos:
                if s.simbolo.startswith("INT_") or s.simbolo == "SENSOR_MOV":
                    etq = s.control or ""  # el interruptor muestra las letras que enciende
                else:
                    etq = etiqueta_circuito(s.circuito)
                    if s.control and sim.grupo == "iluminacion":
                        etq = f"{etq} {s.control}".strip()
                if etq:
                    attrs["CIRCUITO"] = etq
            self.b.insertar_bloque(s.simbolo, self._t(s.posicion), s.rotacion, sim.capa, attrs)

    def _tableros(self, nivel: str) -> None:
        for tb in self.p.tableros:
            if tb.nivel != nivel:
                continue
            self.b.insertar_bloque("TABLERO", self._t(tb.posicion), tb.rotacion, "E-TABLEROS",
                                   {"NOMBRE": tb.id})
            if tb.auto:
                # rótulo del tablero como en los planos de referencia
                x, y = self._t(tb.posicion)
                polos = "2F" if "trifilar" in tb.sistema.lower() or "bif" in tb.sistema.lower() else "3F"
                self.b.texto(f"{polos} · {tb.n_circuitos} ctos · borde sup. h = {num(tb.altura)} m",
                             (x + 0.45, y - 0.22), 0.08, "E-CIRCUITOS")
                if tb.alimentador and self._tipo_actual in ("tomas", "loc_tomas"):
                    self.b.texto(f"Alimentador {tb.id}: {tb.alimentador}", (x + 0.45, y - 0.36), 0.08,
                                 "E-ACOMETIDA", color=1)

    def _conteo(self, nivel: str, grupos: set[str]) -> dict[str, int]:
        cuenta = {}
        for k, v in self.p.conteo_simbolos(nivel).items():
            if SIMBOLOS[k].grupo in grupos:
                cuenta[k] = v
        return cuenta

    def _convenciones(self, conteo: dict[str, int], esquina_sup_izq, constructivo: bool = False) -> float:
        """Cuadro SÍMBOLO | DESCRIPCIÓN | CANT., como en las convenciones de Julián."""
        pl = self.pl
        x0, y0 = esquina_sup_izq
        w_sim, w_desc, w_cant = pl.mm(30), pl.mm(170), pl.mm(25)
        fila = pl.mm(12)
        ancho = w_sim + w_desc + w_cant
        capa = "ANOT-CONVENCIONES"
        h_txt = pl.mm(3.0)

        self.b.relleno_solido([(x0, y0), (x0 + pl.mm(3), y0), (x0 + pl.mm(3), y0 - pl.mm(8)),
                               (x0, y0 - pl.mm(8))], capa, color=2)
        self.b.texto("CONVENCIONES", (x0 + pl.mm(6), y0 - pl.mm(4)), pl.mm(5), capa)
        self.b.texto("cantidad = salidas en este plano", (x0 + ancho - pl.mm(62), y0 - pl.mm(5)),
                     pl.mm(2.2), capa, color=8)
        y = y0 - pl.mm(12)
        filas = [k for k in SIMBOLOS if k in conteo] or []
        alto = fila * (len(filas) + 3)
        # Marco y encabezado
        self.b.polilinea([(x0, y), (x0 + ancho, y), (x0 + ancho, y - alto), (x0, y - alto)], capa, True)
        self.b.texto("SÍMBOLO", (x0 + w_sim / 2, y - fila / 2), h_txt * 0.8, capa, centrado=True)
        self.b.texto("DESCRIPCIÓN", (x0 + w_sim + pl.mm(3), y - fila / 2), h_txt * 0.8, capa)
        self.b.texto("CANT.", (x0 + w_sim + w_desc + w_cant / 2, y - fila / 2), h_txt * 0.8, capa, centrado=True)
        for xv in (x0 + w_sim, x0 + w_sim + w_desc):
            self.b.linea((xv, y), (xv, y - alto), capa)
        yy = y - fila
        self.b.linea((x0, yy), (x0 + ancho, yy), capa)
        for k in filas:
            s = SIMBOLOS[k]
            yc = yy - fila / 2
            bx0, by0, bx1, by1 = caja(s)
            esc = min(2.0, 0.8 * fila / max(by1 - by0, 1e-6), 0.8 * w_sim / max(bx1 - bx0, 1e-6))
            pos = (x0 + w_sim / 2 - esc * (bx0 + bx1) / 2, yc - esc * (by0 + by1) / 2)
            self.b.insertar_bloque(k, pos, 0, capa, None, esc)
            self.b.texto(s.descripcion, (x0 + w_sim + pl.mm(3), yc), h_txt, capa)
            self.b.texto(str(conteo[k]), (x0 + w_sim + w_desc + w_cant / 2, yc), h_txt, capa, centrado=True)
            yy -= fila
            self.b.linea((x0, yy), (x0 + ancho, yy), capa)
        # Filas fijas: número de circuito y acometida
        yc = yy - fila / 2
        self.b.texto("C-02", (x0 + w_sim / 2, yc), h_txt * 0.8, capa, centrado=True)
        self.b.texto("Número junto a la salida = circuito del tablero", (x0 + w_sim + pl.mm(3), yc), h_txt, capa)
        yy -= fila
        self.b.linea((x0, yy), (x0 + ancho, yy), capa)
        yc = yy - fila / 2
        self.b.linea((x0 + pl.mm(5), yc), (x0 + w_sim - pl.mm(5), yc), "E-ACOMETIDA")
        self.b.texto("Acometida y alimentador entre tableros", (x0 + w_sim + pl.mm(3), yc), h_txt, capa)
        yy -= fila
        if constructivo:
            extra = [("E-TUB-TECHO", "Tubería por placa de techo (alumbrado); marcas: fase larga, neutro corta, "
                                     "tierra con punto"),
                     ("E-TUB-PISO", "Tubería por placa de piso (tomas)")]
            for capa_t, texto in extra:
                self.b.linea((x0, yy), (x0 + ancho, yy), capa)
                yc = yy - fila / 2
                pts = _arco((x0 + pl.mm(5), yc - pl.mm(1.5)), (x0 + w_sim - pl.mm(5), yc - pl.mm(1.5)), 0.35)
                self.b.polilinea(pts, capa_t)
                self.b.texto(texto, (x0 + w_sim + pl.mm(3), yc), h_txt * 0.9, capa)
                yy -= fila
            self.b.polilinea([(x0, y - alto), (x0, yy), (x0 + ancho, yy), (x0 + ancho, y - alto)], capa)
            for xv in (x0 + w_sim, x0 + w_sim + w_desc):
                self.b.linea((xv, y - alto), (xv, yy), capa)
        return yy

    def _cuadro_recintos(self, nivel: str, tipo: str, esquina_sup_izq, y_min: float) -> None:
        """Cuadro de recintos y salidas: área, unidad y cantidad de salidas de cada recinto."""
        pl = self.pl
        x0, y = esquina_sup_izq
        capa = "ANOT-CONVENCIONES"
        recs = [r for r in self.p.recintos if r.nivel == nivel and not r.vacio]
        if not recs:
            return
        ilum = tipo == "loc_iluminacion"
        cols = [("RECINTO", 78), ("UNIDAD", 34), ("ÁREA m²", 22)] + (
            [("LUMIN.", 22), ("INTERR.", 22), ("TOMAS", 22)] if ilum else
            [("TOMAS", 22), ("GFCI", 22), ("ESP./COM", 22)])
        fila = pl.mm(5.5)
        n_max = int((y - y_min) / fila) - 3
        if n_max < 3:
            return
        h = pl.mm(2.4)
        self.b.relleno_solido([(x0, y), (x0 + pl.mm(3), y), (x0 + pl.mm(3), y - pl.mm(8)), (x0, y - pl.mm(8))],
                              capa, color=2)
        self.b.texto("CUADRO DE RECINTOS Y SALIDAS", (x0 + pl.mm(6), y - pl.mm(4)), pl.mm(5), capa)
        y -= pl.mm(11)
        ancho = pl.mm(sum(w for _, w in cols))
        filas = []
        for r in sorted(recs, key=lambda r: (r.unidad or "~", r.id)):
            ss = [s for s in self.p.salidas if s.recinto == r.id]
            lum = sum(s.simbolo.startswith(("BALA_", "LUM_", "EXTRACTOR")) for s in ss)
            inte = sum(s.simbolo.startswith("INT_") or s.simbolo == "SENSOR_MOV" for s in ss)
            tom = sum(s.simbolo in ("TOMA_DOBLE", "TOMA_GFCI") for s in ss)
            gf = sum(s.simbolo == "TOMA_GFCI" for s in ss)
            esp = sum(s.simbolo in ("SALIDA_ESPECIAL", "TOMA_220", "TOMA_AA", "COM") for s in ss)
            nombre = r.nombre if len(r.nombre) <= 30 else r.nombre[:29] + "…"
            filas.append([nombre, r.unidad or "Común", num(r.area)] + ([lum, inte, tom] if ilum else [tom, gf, esp]))
        filas = filas[:n_max]
        tot = ["TOTAL", "", num(sum(r.area for r in recs))] + [sum(f[k] for f in filas) for k in (3, 4, 5)]
        todas = [[c for c, _ in cols]] + filas + [tot]
        alto = fila * len(todas)
        self.b.polilinea([(x0, y), (x0 + ancho, y), (x0 + ancho, y - alto), (x0, y - alto)], capa, True)
        xs = [x0]
        for _, w in cols:
            xs.append(xs[-1] + pl.mm(w))
        for xv in xs[1:-1]:
            self.b.linea((xv, y), (xv, y - alto), capa)
        for k, f in enumerate(todas):
            yc = y - fila * (k + 0.5)
            if k:
                self.b.linea((x0, y - fila * k), (x0 + ancho, y - fila * k), capa)
            for j, v in enumerate(f):
                if j == 0:
                    self.b.texto(str(v), (xs[0] + pl.mm(1.5), yc), h * (0.85 if k == 0 else 1), capa)
                else:
                    self.b.texto(str(v), ((xs[j] + xs[j + 1]) / 2, yc), h * (0.85 if k == 0 else 1), capa,
                                 centrado=True)

    def _rotulo(self, nivel: str, tipo: TipoLamina, plano_n: Optional[str], esquina_inf_der) -> None:
        pl = self.pl
        r = self.p.rotulo
        x1, y0 = esquina_inf_der
        ancho, alto = pl.mm(225), pl.mm(150)
        x0 = x1 - ancho
        capa = "ANOT-ROTULO"
        h = pl.mm(3.2)
        self.b.polilinea([(x0, y0), (x1, y0), (x1, y0 + alto), (x0, y0 + alto)], capa, True)

        def celda(xa, ya, xb, yb, etiqueta, valor, hv=h):
            self.b.polilinea([(xa, ya), (xb, ya), (xb, yb), (xa, yb)], capa, True)
            self.b.texto(etiqueta, (xa + pl.mm(2), yb - pl.mm(3)), pl.mm(2.2), capa, color=8)
            if not valor:
                return
            disp = (xb - xa) - pl.mm(6)
            if len(valor) * 0.72 * hv <= disp:
                self.b.texto(valor, (xa + pl.mm(4), (ya + yb) / 2 - pl.mm(1.5)), hv, capa)
                return
            # texto largo: dos renglones partidos en el espacio más cercano a la mitad
            esp = [i for i, c in enumerate(valor) if c == " "] or [len(valor) // 2]
            k = min(esp, key=lambda i: abs(i - len(valor) / 2))
            lineas = [valor[:k].strip(), valor[k:].strip()]
            hl = min(hv, disp / (0.72 * max(len(t) for t in lineas)), (yb - ya - pl.mm(4)) / 2.6)
            yc = (ya + yb) / 2 - pl.mm(1.5)
            for j, t in enumerate(lineas):
                self.b.texto(t, (xa + pl.mm(4), yc + (0.65 - 1.3 * j) * hl), hl, capa)

        f = alto / 7
        xm = x0 + ancho * 0.6
        # fila 1: empresa
        celda(x0, y0 + 6 * f, x1, y0 + 7 * f, "", "")
        self.b.texto(r.empresa or "EMPRESA DE DISEÑO", (x0 + pl.mm(4), y0 + 6.62 * f), pl.mm(5), capa)
        self.b.texto(r.contacto, (x0 + pl.mm(4), y0 + 6.25 * f), pl.mm(3), capa)
        celda(x0, y0 + 5 * f, x1, y0 + 6 * f, "NOMBRE DE PROYECTO:", r.proyecto or self.p.nombre, pl.mm(4.5))
        celda(x0, y0 + 4 * f, xm, y0 + 5 * f, "DIRECCIÓN:", r.direccion)
        celda(xm, y0 + 4 * f, x1, y0 + 5 * f, "MUNICIPIO:", r.municipio)
        contiene = r.contiene or (TITULO_LAMINA[tipo] if tipo == "cuadros" else f"{TITULO_LAMINA[tipo]} {nivel}")
        celda(x0, y0 + 3 * f, xm, y0 + 4 * f, "CONTIENE:", contiene)
        celda(xm, y0 + 3 * f, x1, y0 + 4 * f, "TIPO DE PROYECTO:", r.tipo_proyecto)
        celda(x0, y0 + 2 * f, xm, y0 + 3 * f, "CONSTRUCTOR:", r.constructor)
        celda(xm, y0 + 2 * f, x1, y0 + 3 * f, "DIBUJO:", r.dibujante)
        disen = r.disenador + (f"  ·  M.P. {r.matricula}" if r.matricula else "")
        celda(x0, y0 + f, xm, y0 + 2 * f, "DISEÑO (INGENIERO ELECTRICISTA):", disen)
        celda(xm, y0 + f, x1, y0 + 2 * f, "FECHA:", r.fecha)
        celda(x0, y0, xm, y0 + f, "FIRMA:", "")
        xe = xm + (x1 - xm) / 2
        celda(xm, y0, xe, y0 + f, "ESCALA:", r.escala)
        celda(xe, y0, x1, y0 + f, "PLANO N°:", plano_n or r.plano_n)

    def _marco(self, ox: float, oy: float) -> None:
        pl = self.pl
        m = pl.mm(5)
        self.b.polilinea([(ox, oy), (ox + pl.ancho, oy), (ox + pl.ancho, oy + pl.alto), (ox, oy + pl.alto)],
                         "ANOT-ROTULO", True)
        self.b.polilinea([(ox + m, oy + m), (ox + pl.ancho - m, oy + m), (ox + pl.ancho - m, oy + pl.alto - m),
                          (ox + m, oy + pl.alto - m)], "ANOT-ROTULO", True, ancho=pl.mm(0.5))


def _d(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _arco(a, b, flecha: float = 0.12, n: int = 8) -> list:
    """Puntos de un arco entre a y b cuya flecha es `flecha` × cuerda (hacia la izquierda de a→b)."""
    L = _d(a, b)
    if L < 1e-6:
        return [a, b]
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    nx, ny = -uy, ux
    h = flecha * L
    pts = []
    for i in range(n + 1):
        t = i / n
        off = 4 * h * t * (1 - t)  # parábola: aproxima el arco con flecha h
        pts.append((a[0] + ux * L * t + nx * off, a[1] + uy * L * t + ny * off))
    return pts
