"""Interfaz común de dibujo. El renderizador solo habla con esta interfaz."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Optional

from ..layers import Capa
from ..symbols import Simbolo

P2 = tuple[float, float]
P3 = tuple[float, float, float]


class Backend(ABC):
    nombre: str = "base"

    @abstractmethod
    def preparar(self, capas: Iterable[Capa], tipos_linea: dict) -> None:
        """Crea capas, tipos de línea y estilos de texto."""

    @abstractmethod
    def definir_bloque(self, simbolo: Simbolo) -> None:
        """Crea la definición de bloque del símbolo (si no existe)."""

    @abstractmethod
    def insertar_bloque(self, clave: str, pos: P2, rot_grados: float, capa: str,
                        atributos: Optional[dict[str, str]] = None, escala: float = 1.0) -> None: ...

    @abstractmethod
    def polilinea(self, puntos: list[P2], capa: str, cerrada: bool = False,
                  color: Optional[int] = None, ancho: float = 0.0) -> None: ...

    @abstractmethod
    def relleno_solido(self, puntos: list[P2], capa: str, color: Optional[int] = None) -> None: ...

    @abstractmethod
    def circulo(self, centro: P2, radio: float, capa: str, color: Optional[int] = None) -> None: ...

    @abstractmethod
    def texto(self, txt: str, pos: P2, altura: float, capa: str, centrado: bool = False,
              rot_grados: float = 0.0, color: Optional[int] = None) -> None: ...

    @abstractmethod
    def polilinea_3d(self, puntos: list[P3], capa: str, color: Optional[int] = None) -> None: ...

    def linea(self, p1: P2, p2: P2, capa: str, color: Optional[int] = None) -> None:
        self.polilinea([p1, p2], capa, False, color)

    @abstractmethod
    def finalizar(self) -> str:
        """Guarda/refresca y devuelve una descripción del resultado (ruta o documento)."""
