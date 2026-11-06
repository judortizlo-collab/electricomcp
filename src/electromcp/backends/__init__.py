from .base import Backend
from .dxf_backend import DXFBackend

__all__ = ["Backend", "DXFBackend", "AutoCADBackend"]


def __getattr__(name):  # importación diferida: pywin32 solo existe en Windows
    if name == "AutoCADBackend":
        from .autocad_com import AutoCADBackend

        return AutoCADBackend
    raise AttributeError(name)
