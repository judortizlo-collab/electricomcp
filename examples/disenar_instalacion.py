"""Paso 3: del plano arquitectónico a la instalación eléctrica completa.

    python examples/disenar_instalacion.py C:\\Planos\\Apartamentos.dxf
    python examples/disenar_instalacion.py C:\\Planos\\Apartamentos.dxf --estufa electrica --autocad

1. Depura e interpreta el plano (paso 2).
2. Diseña: tomas (NTC 2050 210.52), iluminación (RETILAP), interruptores, circuitos, tableros,
   medidores, tubería y cuadros de carga.
3. Dibuja las láminas de ILUMINACIÓN, TOMAS y CUADROS DE CARGA / UNIFILARES en DXF (o en AutoCAD).

Salidas en la carpeta salidas/:
  <plano>_electrico.dxf            láminas (un pliego 100x70 por tipo)
  <plano>_electrico_*.png          vista previa de cada lámina
  <plano>_diseno.json              reporte: cálculos lumínicos, cuadros de carga y verificación NTC 2050
  <plano>_proyecto.json            proyecto de ElectroMCP (se puede reabrir y modificar desde Claude)
"""

import argparse
import json
from pathlib import Path

from electromcp.arquitectura import aplicar_a_proyecto, depurar_plano
from electromcp.backends.dxf_backend import DXFBackend
from electromcp.diseno import ParametrosDiseno, disenar
from electromcp.model import Proyecto, Rotulo
from electromcp.render import Renderizador


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plano")
    ap.add_argument("--salida", default="salidas")
    ap.add_argument("--nivel", default="PISO 1")
    ap.add_argument("--estufa", choices=["gas", "electrica"], default="gas")
    ap.add_argument("--calentador", choices=["gas", "electrico", "ninguno"], default="gas")
    ap.add_argument("--autocad", action="store_true", help="dibujar en el AutoCAD abierto en vez de DXF")
    ap.add_argument("--sin-png", action="store_true")
    a = ap.parse_args()

    ruta = Path(a.plano)
    salida = Path(a.salida)
    res = depurar_plano(ruta, salida, vista_previa=False)
    p = Proyecto(nombre=ruta.stem, niveles=[a.nivel], rotulo=Rotulo(proyecto=ruta.stem.upper(),
                                                                    tipo_proyecto="RESIDENCIAL MULTIFAMILIAR"))
    aplicar_a_proyecto(p, res.interpretacion, a.nivel)
    inf = disenar(p, ParametrosDiseno(estufa=a.estufa, calentador=a.calentador), a.nivel)

    print(f"{'Unidad':<20} {'Tablero':<8} {'Circ.':>5} {'Instalada':>10} {'Demanda':>9} {'Prot.':>8}  Alimentador")
    for tid, cq in inf.cuadros.items():
        print(f"{cq.unidad:<20} {tid:<8} {len(cq.filas):>5} {cq.total_va:>9.0f}  {cq.demanda_va:>8.0f}  "
              f"2x{cq.proteccion_general_a:>3.0f} A  {cq.alimentador}")
    ok = sum(v["cumple"] for v in inf.verificacion)
    print(f"\nVerificación NTC 2050: {ok} de {len(inf.verificacion)} requisitos cumplen")
    for v in inf.verificacion:
        if not v["cumple"]:
            print(f"  NO CUMPLE  {v['recinto']}: {v['requisito']} -> {v['resultado']} ({v['articulo']})")
    for av in inf.avisos:
        print("AVISO:", av)

    salida.mkdir(parents=True, exist_ok=True)
    (salida / f"{ruta.stem}_diseno.json").write_text(json.dumps(inf.reporte(), ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    p.guardar(salida / f"{ruta.stem}_proyecto.json")
    laminas = ("iluminacion", "tomas", "cuadros")
    if a.autocad:
        from electromcp.backends.autocad_com import AutoCADBackend

        print(Renderizador(p, AutoCADBackend(nuevo_dibujo=True)).dibujar_juego(laminas))
        return
    dxf = salida / f"{ruta.stem}_electrico.dxf"
    r = Renderizador(p, DXFBackend(dxf))
    print("DXF:", r.dibujar_juego(laminas))
    if not a.sin_png:
        from electromcp.preview import dxf_a_png

        ancho = r.pl.ancho + r.pl.mm(100)
        nombres = ["iluminacion", "tomas"] + [f"cuadros_{k}" for k in range(1, 10)]
        n = len(p.niveles) * 2 + _hojas_cuadros(p, r)
        for k in range(n):
            x0 = k * ancho
            png = salida / f"{ruta.stem}_electrico_{k + 1:02d}_{nombres[k] if k < len(nombres) else k}.png"
            dxf_a_png(dxf, png, dpi=110, ventana=(x0, 0, x0 + r.pl.ancho, r.pl.alto), lado_mayor_pulg=24)
            print("PNG:", png)


def _hojas_cuadros(p, r) -> int:
    from electromcp.render_cuadros import paginar

    return len(paginar(p, r.pl))


if __name__ == "__main__":
    main()
