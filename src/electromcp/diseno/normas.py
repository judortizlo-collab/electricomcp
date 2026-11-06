"""Parámetros y tablas normativas del motor de diseño.

Referencias: NTC 2050 segunda actualización (2020, basada en NFPA 70-2017), adoptada por el
RETIE 2024 (Res. MME 40117 de 2024) y RETILAP. La numeración usa el formato de la NTC 2050:2020
("210.52(A)"). Todos los valores son parámetros: el ingeniero puede cambiarlos en
`ParametrosDiseno` sin tocar el código, y cada regla cita su artículo para que el diseño sea
auditable. Verifique siempre contra el texto vigente de la norma.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from ..model import UsoRecinto

# ----------------------------------------------------------------- referencias citadas
ART = {
    "espaciamiento": "NTC 2050 210.52(A)(1)",
    "espacio_pared": "NTC 2050 210.52(A)(2)",
    "pequenos_artefactos": "NTC 2050 210.11(C)(1) y 210.52(B)",
    "meson": "NTC 2050 210.52(C)",
    "bano": "NTC 2050 210.52(D) y 210.11(C)(3)",
    "lavanderia": "NTC 2050 210.52(F) y 210.11(C)(2)",
    "pasillo": "NTC 2050 210.52(H)",
    "gfci": "NTC 2050 210.8(A)",
    "alumbrado": "NTC 2050 210.70(A)",
    "carga_alumbrado": "NTC 2050 220.12 y Tabla 220.12",
    "carga_pa": "NTC 2050 220.52(A) y (B)",
    "factor_demanda": "NTC 2050 220.42 y Tabla 220.42",
    "conductor_minimo": "NTC 2050 240.4(D)",
    "ampacidad": "NTC 2050 Tabla 310.15(B)(16), columna 60 °C (110.14(C)(1))",
    "tierra": "NTC 2050 250.122 y Tabla 250.122",
    "llenado": "NTC 2050 Capítulo 9, Tablas 1, 4 y 5",
    "regulacion": "NTC 2050 210.19(A) NI 4 y 215.2(A)(1) NI 2; RETIE",
    "iluminancia": "RETILAP Tabla 410.1 (valores medios)",
    "metodo_lumenes": "RETILAP 440 (método de cavidad zonal / lúmenes)",
    "tr": "NTC 2050 406.12 (tomacorrientes resistentes a la manipulación)",
}

# ----------------------------------------------------------------- RETILAP: iluminancia media (lx)
ILUMINANCIA_LX: dict[UsoRecinto, float] = {
    UsoRecinto.SALA: 150,
    UsoRecinto.COMEDOR: 150,
    UsoRecinto.SALA_COMEDOR: 150,
    UsoRecinto.COCINA: 300,
    UsoRecinto.BANO: 100,
    UsoRecinto.ALCOBA: 100,
    UsoRecinto.ESTUDIO: 300,
    UsoRecinto.ROPAS: 200,
    UsoRecinto.CIRCULACION: 100,
    UsoRecinto.VESTIER: 100,
    UsoRecinto.GARAJE: 75,
    UsoRecinto.TERRAZA: 75,
    UsoRecinto.BALCON: 75,
    UsoRecinto.EXTERIOR: 50,
    UsoRecinto.CUARTO_TECNICO: 200,
    UsoRecinto.ESCALERA: 100,
    UsoRecinto.OTRO: 100,
}

# Coeficiente de utilización de una bala LED de incrustar (reflectancias techo 0,7 / pared 0,5 /
# piso 0,2) en función del índice del local K = L·A / (h·(L + A)).
TABLA_CU = [(0.6, 0.40), (0.8, 0.47), (1.0, 0.52), (1.25, 0.57), (1.5, 0.61), (2.0, 0.66), (2.5, 0.69),
            (3.0, 0.72), (4.0, 0.75), (5.0, 0.77)]

# ----------------------------------------------------------------- conductores (Cu THHN/THWN-2)
# Ampacidad 60 °C, Tabla 310.15(B)(16)
AMPACIDAD_60C = {"14": 15, "12": 20, "10": 30, "8": 40, "6": 55, "4": 70, "3": 85, "2": 95, "1": 110,
                 "1/0": 125, "2/0": 145, "3/0": 165, "4/0": 195}
CALIBRES = list(AMPACIDAD_60C)
# Protección máxima de conductores pequeños, 240.4(D)
PROTECCION_MAX = {"14": 15, "12": 20, "10": 30}
# Área de conductor THHN (mm²), Tabla 5
AREA_THHN_MM2 = {"14": 6.258, "12": 8.581, "10": 13.61, "8": 23.61, "6": 32.71, "4": 53.16, "3": 62.77,
                 "2": 74.71, "1": 102.3, "1/0": 119.7, "2/0": 143.4, "3/0": 172.8, "4/0": 208.8}
# Resistencia en c.a. (ohm/km) de Cu en tubo PVC, Tabla 9
R_OHM_KM = {"14": 10.2, "12": 6.6, "10": 3.9, "8": 2.56, "6": 1.61, "4": 1.02, "3": 0.82, "2": 0.62,
            "1": 0.49, "1/0": 0.39, "2/0": 0.33, "3/0": 0.253, "4/0": 0.203}
# Conductor de puesta a tierra de equipos, Tabla 250.122 (protección A -> calibre Cu)
TIERRA_250_122 = [(15, "14"), (20, "12"), (60, "10"), (100, "8"), (200, "6"), (300, "4"), (400, "3")]
# Área interna total de tubo PVC SCH 40 (mm²), Tabla 4
AREA_PVC40_MM2 = {'1/2"': 184, '3/4"': 327, '1"': 535, '1-1/4"': 935, '1-1/2"': 1282, '2"': 2124}
PROTECCIONES_A = [15, 20, 30, 40, 50, 60, 70, 80, 100, 125, 150, 175, 200, 225]


class ParametrosDiseno(BaseModel):
    """Criterios del diseño automático. Todo se puede ajustar por proyecto."""

    # Tomacorrientes
    dist_max_toma_m: float = Field(1.8, description="210.52(A)(1): ningún punto a más de 1,8 m de una toma")
    espacio_pared_min_m: float = Field(0.6, description="210.52(A)(2): espacio de pared de 0,6 m o más")
    dist_max_meson_m: float = Field(0.6, description="210.52(C)(1): ningún punto del mesón a más de 0,6 m")
    dist_toma_lavamanos_m: float = Field(0.9, description="210.52(D): a menos de 0,9 m del lavamanos")
    pasillo_min_m: float = Field(3.0, description="210.52(H): pasillos de 3 m o más llevan toma")
    dist_esquina_m: float = 0.30
    altura_toma_m: float = 0.30
    altura_toma_meson_m: float = 1.10
    altura_toma_bano_m: float = 1.10
    retiro_ducha_m: float = 0.60  # 406.9(C): nada dentro ni encima de la ducha
    # Iluminación
    potencias_bala_w: tuple[int, ...] = (9, 12, 18)
    lumenes_por_w: float = 85.0  # eficacia de la bala LED (lm/W), según ficha del fabricante
    factor_mantenimiento: float = 0.80
    plano_trabajo_m: float = 0.85
    espaciamiento_max_m: float = 2.40  # separación máxima entre balas (uniformidad, ≈ 1,5 × altura útil)
    iluminancia_lx: dict[str, float] = Field(default_factory=lambda: {u.value: v for u, v in ILUMINANCIA_LX.items()})
    altura_interruptor_m: float = 1.20
    sensores_zonas_comunes: bool = True
    # Circuitos
    tension_fn_v: float = 120.0
    tension_ff_v: float = 240.0
    max_salidas_iluminacion: int = 12
    max_tomas_por_circuito: int = 8
    factor_carga_continua: float = 0.80
    proteccion_iluminacion_a: float = 15.0
    proteccion_tomas_a: float = 20.0
    va_por_toma: float = 180.0  # 220.14(I)
    va_alumbrado_m2: float = 33.0  # Tabla 220.12: 33 VA/m² (3 VA/ft²) para unidades de vivienda
    va_pequenos_artefactos: float = 1500.0  # 220.52(A)
    va_lavanderia: float = 1500.0  # 220.52(B)
    va_nevera: float = 300.0
    va_lavadora: float = 1000.0
    va_extractor: float = 40.0
    estufa: Literal["gas", "electrica"] = "gas"
    potencia_estufa_va: float = 6000.0
    calentador: Literal["gas", "electrico", "ninguno"] = "gas"
    potencia_calentador_va: float = 3000.0
    reserva_circuitos: int = 2
    proteccion_general_min_a: float = 40.0
    regulacion_max_ramal_pct: float = 3.0
    regulacion_max_alimentador_pct: float = 2.0
    # Tubería
    tubo_min: str = '1/2"'
    llenado_max: float = 0.40  # Tabla 1, Cap. 9: más de dos conductores
    comunicaciones: bool = True

    def lux(self, uso: UsoRecinto) -> float:
        return float(self.iluminancia_lx.get(uso.value, ILUMINANCIA_LX.get(uso, 100)))


# ----------------------------------------------------------------- funciones de tabla
def coef_utilizacion(k: float) -> float:
    if k <= TABLA_CU[0][0]:
        return TABLA_CU[0][1]
    for (k0, c0), (k1, c1) in zip(TABLA_CU, TABLA_CU[1:]):
        if k <= k1:
            return c0 + (c1 - c0) * (k - k0) / (k1 - k0)
    return TABLA_CU[-1][1]


def proteccion_estandar(i: float, minimo: float = 15) -> float:
    for p in PROTECCIONES_A:
        if p >= max(i, minimo) - 1e-9:
            return p
    return PROTECCIONES_A[-1]


def calibre_para(proteccion_a: float, minimo: str = "14") -> str:
    """Menor calibre Cu cuya ampacidad (60 °C) y límite 240.4(D) admiten la protección."""
    for c in CALIBRES[CALIBRES.index(minimo):]:
        lim = PROTECCION_MAX.get(c, AMPACIDAD_60C[c])
        # 240.4(B): se permite la protección estándar inmediatamente superior hasta 800 A
        if c not in PROTECCION_MAX and proteccion_estandar(AMPACIDAD_60C[c]) >= proteccion_a:
            return c
        if lim >= proteccion_a:
            return c
    return CALIBRES[-1]


def calibre_tierra(proteccion_a: float) -> str:
    for lim, c in TIERRA_250_122:
        if proteccion_a <= lim:
            return c
    return TIERRA_250_122[-1][1]


def diametro_tubo(conductores: list[str], minimo: str = '1/2"', llenado: float = 0.40) -> str:
    """Diámetro PVC SCH 40 según el área total de los conductores (Cap. 9, Tablas 1, 4 y 5)."""
    area = sum(AREA_THHN_MM2[c] for c in conductores)
    if len(conductores) == 1:
        llenado = 0.53
    elif len(conductores) == 2:
        llenado = 0.31
    tubos = list(AREA_PVC40_MM2)
    for t in tubos[tubos.index(minimo):]:
        if area <= llenado * AREA_PVC40_MM2[t]:
            return t
    return tubos[-1]


def regulacion_pct(i_a: float, longitud_m: float, calibre: str, tension_v: float, monofasico: bool = True) -> float:
    """Caída de tensión porcentual: ΔV = k·I·R·L (k = 2 monofásico a 2 hilos, √3 trifásico)."""
    k = 2.0 if monofasico else math.sqrt(3)
    return 100.0 * k * i_a * R_OHM_KM[calibre] * longitud_m / 1000.0 / tension_v


def demanda_220_42(carga_va: float) -> float:
    """Tabla 220.42, unidades de vivienda: primeros 3000 VA al 100 %, de 3001 a 120 000 al 35 %, resto 25 %."""
    if carga_va <= 3000:
        return carga_va
    if carga_va <= 120000:
        return 3000 + 0.35 * (carga_va - 3000)
    return 3000 + 0.35 * 117000 + 0.25 * (carga_va - 120000)
