"""Capas normalizadas del plano eléctrico.

Nomenclatura inspirada en AIA/NCS adaptada al español:
  ARQ-*  arquitectura depurada (se dibuja en gris para que lo eléctrico resalte)
  E-*    instalaciones eléctricas
  COM-*  comunicaciones
  ANOT-* anotaciones, rótulo y convenciones
Colores ACI de AutoCAD. Grosores en centésimas de mm (lineweight).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Capa:
    nombre: str
    color: int  # ACI
    tipo_linea: str = "Continuous"
    grosor: int = 25  # 0.25 mm
    descripcion: str = ""
    imprimible: bool = True


CAPAS: dict[str, Capa] = {c.nombre: c for c in [
    # Arquitectura depurada
    Capa("ARQ-MUROS", 8, grosor=35, descripcion="Muros (arquitectura depurada)"),
    Capa("ARQ-VANOS", 8, grosor=18, descripcion="Puertas y ventanas"),
    Capa("ARQ-RECINTOS", 9, grosor=13, descripcion="Nombres y áreas de recintos"),
    Capa("ARQ-REFERENCIA", 9, "DASHED", 13, "Linderos, proyecciones, vacíos"),
    # Eléctrico
    Capa("E-ILUMINACION", 3, grosor=25, descripcion="Salidas de iluminación"),
    Capa("E-INTERRUPTORES", 7, grosor=25, descripcion="Interruptores y sensores"),
    Capa("E-TOMAS", 1, grosor=25, descripcion="Tomacorrientes 120 V"),
    Capa("E-TOMAS-ESPECIALES", 6, grosor=25, descripcion="Tomas 220 V y salidas dedicadas"),
    Capa("E-FUERZA", 6, grosor=25, descripcion="Motores, AA, guardamotores"),
    Capa("E-TABLEROS", 1, grosor=35, descripcion="Tableros, medidores"),
    Capa("E-TUB-MURO", 3, grosor=25, descripcion="Tubería por muro/placa"),
    Capa("E-TUB-PISO", 3, "DASHED", 25, "Tubería por piso"),
    Capa("E-TUB-TECHO", 3, "DASHDOT", 25, "Tubería por techo/cielo"),
    Capa("E-ACOMETIDA", 1, "DASHED", 35, "Acometida y alimentadores"),
    Capa("E-ACCIONAMIENTO", 7, "DOT", 13, "Líneas de accionamiento interruptor-luminaria"),
    Capa("E-CIRCUITOS", 7, grosor=13, descripcion="Marcas de circuito (C-xx)"),
    # Comunicaciones
    Capa("COM-SALIDAS", 3, grosor=25, descripcion="Salidas de datos/TV/citofonía"),
    Capa("COM-TUBERIA", 5, "DASHED", 18, "Tubería de comunicaciones"),
    # Anotación
    Capa("ANOT-TEXTOS", 7, grosor=18, descripcion="Textos y notas"),
    Capa("ANOT-CONVENCIONES", 7, grosor=18, descripcion="Cuadro de convenciones"),
    Capa("ANOT-ROTULO", 7, grosor=35, descripcion="Rótulo y marco"),
    # 3D
    Capa("E-3D-TUBERIA", 3, descripcion="Tubería modelada en 3D", imprimible=False),
    Capa("E-3D-CAJAS", 1, descripcion="Cajas de salida en 3D", imprimible=False),
]}

TIPOS_LINEA = {
    # nombre: (descripción, patrón en unidades de dibujo [m])
    "DASHED": ("__ __ __", [0.6, 0.4, -0.2]),
    "DASHDOT": ("__ . __ .", [0.8, 0.4, -0.15, 0.0, -0.15]),
    "DOT": (". . . .", [0.2, 0.0, -0.2]),
}
