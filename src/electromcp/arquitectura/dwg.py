"""Conversión DWG -> DXF.

ezdxf solo lee DXF. Para un DWG hay dos caminos, en este orden:

1. **ODA File Converter** (gratuito, de la Open Design Alliance), si está instalado.
2. **AutoCAD 2026** por COM (Windows): abre una copia del DWG, la guarda como DXF y la cierra.
   El dibujo original no se toca.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

AC2018_DXF = 65  # AcSaveAsType.ac2018_dxf
AC2013_DXF = 61  # AcSaveAsType.ac2013_dxf


def _con_oda(dwg: Path, dxf: Path) -> bool:
    try:
        from ezdxf.addons import odafc
    except ImportError:
        return False
    if not odafc.is_installed():
        return False
    odafc.convert(str(dwg), str(dxf), version="R2018", replace=True)
    return dxf.exists()


def _con_autocad(dwg: Path, dxf: Path) -> bool:
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception:
        acad = win32com.client.Dispatch("AutoCAD.Application")
        acad.Visible = True
    tmp = Path(tempfile.mkdtemp(prefix="electromcp_")) / dwg.name
    shutil.copy2(dwg, tmp)  # se trabaja sobre una copia: el original queda intacto
    doc = None
    for _ in range(40):
        try:
            doc = acad.Documents.Open(str(tmp), True)  # solo lectura
            break
        except Exception:
            time.sleep(0.25)
    if doc is None:
        return False
    try:
        try:
            doc.SaveAs(str(dxf), AC2018_DXF)
        except Exception:
            doc.SaveAs(str(dxf), AC2013_DXF)
    finally:
        try:
            doc.Close(False)
        except Exception:
            pass
    return dxf.exists()


def convertir_dwg_a_dxf(ruta_dwg: str | Path, ruta_dxf: Optional[str | Path] = None) -> Path:
    dwg = Path(ruta_dwg)
    if not dwg.exists():
        raise FileNotFoundError(dwg)
    dxf = Path(ruta_dxf) if ruta_dxf else dwg.with_suffix(".dxf")
    if dxf.resolve() == dwg.resolve():
        raise ValueError("La ruta de salida debe ser distinta del DWG")
    dxf.parent.mkdir(parents=True, exist_ok=True)
    if _con_oda(dwg, dxf) or _con_autocad(dwg, dxf):
        return dxf
    raise RuntimeError("No se pudo convertir el DWG: instale ODA File Converter o abra AutoCAD 2026 "
                       "(o guarde el plano como DXF con el comando GUARDARCOMO / SAVEAS).")


def dibujo_activo_a_dxf(ruta_dxf: Optional[str | Path] = None) -> Path:
    """Exporta a DXF el dibujo abierto en AutoCAD (debe estar guardado en disco)."""
    import win32com.client  # type: ignore

    acad = win32com.client.GetActiveObject("AutoCAD.Application")
    doc = acad.ActiveDocument
    nombre = doc.FullName
    if not nombre:
        raise RuntimeError("Guarde primero el dibujo activo en AutoCAD.")
    if doc.Saved is False:
        raise RuntimeError("El dibujo activo tiene cambios sin guardar. Guárdelo antes de exportar.")
    dwg = Path(nombre)
    destino = Path(ruta_dxf) if ruta_dxf else dwg.with_name(dwg.stem + "_electromcp.dxf")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if not _con_autocad(dwg, destino):
        raise RuntimeError("AutoCAD no pudo exportar el dibujo a DXF.")
    return destino
