"""Vista previa PNG/PDF de un DXF (para revisar sin abrir AutoCAD)."""

from __future__ import annotations

from pathlib import Path


def dxf_a_png(ruta_dxf: str | Path, ruta_png: str | Path | None = None, dpi: int = 200,
              fondo_blanco: bool = True, ventana: tuple[float, float, float, float] | None = None,
              lado_mayor_pulg: float = 30.0) -> Path:
    """Renderiza el espacio modelo a PNG. `ventana` = (x0, y0, x1, y1) limita la zona."""
    import ezdxf
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    ruta_dxf = Path(ruta_dxf)
    ruta_png = Path(ruta_png) if ruta_png else ruta_dxf.with_suffix(".png")
    doc = ezdxf.readfile(ruta_dxf)
    from ezdxf import bbox

    if ventana:
        x0, y0, x1, y1 = ventana
    else:
        ext = bbox.extents(doc.modelspace(), fast=True)
        x0, y0, x1, y1 = (ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y) if ext.has_data else (0, 0, 1, 1)
    ancho, alto = x1 - x0, y1 - y0
    base = lado_mayor_pulg
    tam = (base, max(base * alto / ancho, 1.0)) if ancho >= alto else (max(base * ancho / alto, 1.0), base)
    fig = plt.figure(figsize=tam)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    cfg = Configuration(
        background_policy=BackgroundPolicy.WHITE if fondo_blanco else BackgroundPolicy.DEFAULT,
        color_policy=ColorPolicy.COLOR,
        lineweight_scaling=0.6,
    )
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace())
    ax.set_aspect("equal")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    fig.set_size_inches(*tam)
    fig.savefig(ruta_png, dpi=dpi)
    plt.close(fig)
    return ruta_png
