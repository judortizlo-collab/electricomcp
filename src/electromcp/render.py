"""Traduce el modelo del proyecto a planos (DXF o AutoCAD en vivo).

Cada plano ("lámina") replica la organización de los planos de referencia:
un nivel por lámina, separado en ILUMINACIÓN y TOMAS, con el cuadro de
convenciones a la derecha (con cantidades contadas automáticamente), el rótulo
abajo a la derecha y el marco del pliego. Escala de impresión 1:50 por defecto.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .backends.base import Backend
from .layers import CAPAS, TIPOS_LINEA
from .model import Proyecto, TipoCircuito, TipoTuberia
from .symbols import SIMBOLOS, caja

TipoLamina = Literal["iluminacion", "tomas", "completo"]

CAPA_TUBERIA = {
    TipoTuberia.MURO: "E-TUB-MURO",
    TipoTuberia.PISO: "E-TUB-PISO",
    TipoTuberia.TECHO: "E-TUB-TECHO",
    TipoTuberia.COMUNICACIONES: "COM-TUBERIA",
    TipoTuberia.ACOMETIDA: "E-ACOMETIDA",
}

GRUPOS_LAMINA = {
    "iluminacion": {"iluminacion", "tableros"},
    "tomas": {"tomas", "fuerza", "com", "tableros"},
    "completo": {"iluminacion", "tomas", "fuerza", "com", "tableros"},
}

TITULO_LAMINA = {
    "iluminacion": "REDES ELÉCTRICAS DE ILUMINACIÓN",
    "tomas": "REDES ELÉCTRICAS DE TOMAS",
    "completo": "REDES ELÉCTRICAS",
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
        total = len(self.p.niveles) * len(laminas)
        n = 0
        for nivel in self.p.niveles:
            for tipo in laminas:
                n += 1
                origen = ((n - 1) * (self.pl.ancho + self.pl.mm(100)), 0.0)
                self.dibujar_lamina(nivel, tipo, origen, f"{n:02d} DE {total:02d}")
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
        self._arquitectura(nivel)
        self._tuberias(nivel, tipo)
        self._salidas(nivel, grupos)
        self._tableros(nivel)
        conteo = self._conteo(nivel, grupos)
        self._convenciones(conteo, (ox + pl.ancho - col_der, oy + pl.alto - margen))
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
            if t.tipo == TipoTuberia.COMUNICACIONES and tipo == "iluminacion":
                continue
            pts = [self._t(q) for q in t.ruta]
            self.b.polilinea(pts, CAPA_TUBERIA[t.tipo])
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

    def _salidas(self, nivel: str, grupos: set[str]) -> None:
        for s in self.p.salidas:
            if s.nivel != nivel:
                continue
            sim = SIMBOLOS[s.simbolo]
            if sim.grupo not in grupos:
                continue
            attrs = {}
            if "CIRCUITO" in sim.atributos and s.circuito:
                attrs["CIRCUITO"] = s.circuito
            self.b.insertar_bloque(s.simbolo, self._t(s.posicion), s.rotacion, sim.capa, attrs)

    def _tableros(self, nivel: str) -> None:
        for tb in self.p.tableros:
            if tb.nivel != nivel:
                continue
            self.b.insertar_bloque("TABLERO", self._t(tb.posicion), tb.rotacion, "E-TABLEROS",
                                   {"NOMBRE": tb.id})

    def _conteo(self, nivel: str, grupos: set[str]) -> dict[str, int]:
        cuenta = {}
        for k, v in self.p.conteo_simbolos(nivel).items():
            if SIMBOLOS[k].grupo in grupos:
                cuenta[k] = v
        return cuenta

    def _convenciones(self, conteo: dict[str, int], esquina_sup_izq) -> None:
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
            if valor:
                self.b.texto(valor, (xa + pl.mm(4), (ya + yb) / 2 - pl.mm(1.5)), hv, capa)

        f = alto / 7
        xm = x0 + ancho * 0.6
        # fila 1: empresa
        celda(x0, y0 + 6 * f, x1, y0 + 7 * f, "", "")
        self.b.texto(r.empresa or "EMPRESA DE DISEÑO", (x0 + pl.mm(4), y0 + 6.62 * f), pl.mm(5), capa)
        self.b.texto(r.contacto, (x0 + pl.mm(4), y0 + 6.25 * f), pl.mm(3), capa)
        celda(x0, y0 + 5 * f, x1, y0 + 6 * f, "NOMBRE DE PROYECTO:", r.proyecto or self.p.nombre, pl.mm(4.5))
        celda(x0, y0 + 4 * f, xm, y0 + 5 * f, "DIRECCIÓN:", r.direccion)
        celda(xm, y0 + 4 * f, x1, y0 + 5 * f, "MUNICIPIO:", r.municipio)
        contiene = r.contiene or f"{TITULO_LAMINA[tipo]} {nivel}"
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
