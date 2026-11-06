"""Paso 2: depura un plano arquitectónico y lo deja listo para el diseño eléctrico.

    python examples/depurar_plano.py C:\\Planos\\Apartamentos.dxf
    python examples/depurar_plano.py C:\\Planos\\Apartamentos.dwg      (requiere AutoCAD u ODA)
    python examples/depurar_plano.py plano.dxf --capa _F5=muros --capa BLANCO=ignorar

Genera en la carpeta salidas/:
  <plano>_depurado.dxf           plano limpio, solo capas ARQ-*, en metros
  <plano>_depurado_verificacion.png  recintos coloreados por apartamento para revisar
  <plano>_depurado_reporte.json  recintos, áreas, puertas, ventanas, aparatos, capas
  <plano>_proyecto.json          proyecto de ElectroMCP con la arquitectura y los recintos cargados
"""

import argparse
from pathlib import Path

from electromcp.arquitectura import aplicar_a_proyecto, depurar_plano
from electromcp.model import Proyecto


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plano")
    ap.add_argument("--salida", default="salidas")
    ap.add_argument("--nivel", default="PISO 1")
    ap.add_argument("--unidades", choices=["mm", "cm", "m"])
    ap.add_argument("--capa", action="append", default=[], help="corrección CAPA=categoria")
    a = ap.parse_args()

    ruta = Path(a.plano)
    if ruta.suffix.lower() == ".dwg":
        from electromcp.arquitectura.dwg import convertir_dwg_a_dxf

        ruta = convertir_dwg_a_dxf(ruta, Path(a.salida) / (ruta.stem + ".dxf"))
    mapa = dict(c.split("=", 1) for c in a.capa)
    res = depurar_plano(ruta, a.salida, mapa or None, a.unidades)

    r = res.reporte["resumen"]
    print(f"{r['recintos']} recintos, {r['unidades']} unidades, {r['puertas']} puertas, "
          f"{r['ventanas']} ventanas, {r['columnas']} columnas")
    for u, d in res.reporte["unidades"].items():
        print(f"  {u}: {d['area_m2']:.2f} m² libres, recintos {', '.join(d['recintos'])}")
    for rec in res.interpretacion.recintos:
        print(f"  {rec.id}  {rec.nombre:<34} {rec.uso.value:<14} {rec.area:7.2f} m²  {rec.unidad or ''}")
    for av in res.reporte["avisos"]:
        print("AVISO:", av)

    p = Proyecto(nombre=ruta.stem, niveles=[a.nivel])
    aplicar_a_proyecto(p, res.interpretacion, a.nivel)
    destino = p.guardar(Path(a.salida) / f"{ruta.stem}_proyecto.json")
    res.archivos["proyecto"] = str(destino)
    for k, v in res.archivos.items():
        print(f"{k:>18}: {v}")


if __name__ == "__main__":
    main()
