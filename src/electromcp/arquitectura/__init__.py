"""Paso 2: depuración e interpretación del plano arquitectónico.

Uso típico::

    from electromcp.arquitectura import depurar_plano
    res = depurar_plano("Apartamentos.dxf", "salidas/")
    res.interpretacion.recintos      # recintos con nombre, uso, unidad y polígono
    res.archivos                     # DXF depurado, PNG de verificación, reporte JSON
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .analisis import Interpretacion, interpretar
from .capas import Categoria, clasificar_capas
from .exportar import aplicar_a_proyecto, escribir_dxf, guardar_reporte, plano_verificacion, reporte
from .lectura import PlanoLeido, leer_plano

__all__ = ["depurar_plano", "analizar_capas", "Resultado", "Categoria", "aplicar_a_proyecto", "leer_plano",
           "clasificar_capas", "interpretar"]


@dataclass
class Resultado:
    plano: PlanoLeido
    interpretacion: Interpretacion
    reporte: dict
    archivos: dict[str, str] = field(default_factory=dict)


def analizar_capas(ruta: str | Path, mapa_capas: Optional[dict[str, str]] = None,
                   unidades: Optional[str] = None) -> dict:
    """Solo lectura y clasificación de capas (rápido), para revisar antes de depurar."""
    plano = leer_plano(ruta, unidades)
    capas = clasificar_capas(plano.elementos, mapa_capas)
    return {"unidades_origen": plano.unidad_origen, "entidades": len(plano.elementos),
            "bloques": plano.n_bloques, "avisos": plano.avisos,
            "capas": [i.resumen() for i in sorted(capas.values(), key=lambda i: (i.categoria.value, i.nombre))]}


def depurar_plano(ruta: str | Path, carpeta_salida: Optional[str | Path] = None,
                  mapa_capas: Optional[dict[str, str]] = None, unidades: Optional[str] = None,
                  nombre: Optional[str] = None, incluir_aparatos: bool = True, incluir_ejes: bool = True,
                  vista_previa: bool = True) -> Resultado:
    """Lee, clasifica, interpreta y escribe el plano depurado.

    mapa_capas: correcciones {capa: categoría}, p. ej. {"_F5": "muros", "BLANCO": "ignorar"}.
    """
    ruta = Path(ruta)
    plano = leer_plano(ruta, unidades)
    capas = clasificar_capas(plano.elementos, mapa_capas)
    interp = interpretar(plano, capas)
    rep = reporte(interp, plano)
    res = Resultado(plano, interp, rep)
    if carpeta_salida is not None:
        base = Path(carpeta_salida) / (nombre or f"{ruta.stem}_depurado")
        res.archivos["dxf"] = str(escribir_dxf(interp, base.with_suffix(".dxf"), incluir_aparatos, incluir_ejes,
                                               titulo=ruta.stem))
        res.archivos["reporte"] = str(guardar_reporte(rep, base.with_name(base.name + "_reporte.json")))
        if vista_previa:
            res.archivos["verificacion_png"] = str(plano_verificacion(
                interp, base.with_name(base.name + "_verificacion.png"), titulo=f"Interpretación de {ruta.name}"))
    return res
