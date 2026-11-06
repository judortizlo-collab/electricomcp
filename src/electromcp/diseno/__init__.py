"""Paso 3: motor de diseño eléctrico según NTC 2050 (2020) / RETIE / RETILAP.

    from electromcp.diseno import disenar, ParametrosDiseno
    informe = disenar(proyecto, ParametrosDiseno(estufa="electrica"))
"""

from .cuadro import CuadroCargas
from .motor import COMUNES, InformeDiseno, disenar
from .normas import ART, ParametrosDiseno

__all__ = ["disenar", "ParametrosDiseno", "InformeDiseno", "CuadroCargas", "ART", "COMUNES"]
