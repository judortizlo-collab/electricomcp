# ElectroMCP

Servidor MCP para diseño eléctrico residencial y comercial en Colombia (NTC 2050, RETIE),
que dibuja en **AutoCAD 2026 en vivo** o genera **archivos DXF**.

> El diseño que produce esta herramienta es un borrador técnico. La revisión, la firma y la
> responsabilidad del diseño son del ingeniero electricista con matrícula profesional vigente.

## Estado del proyecto

| Paso | Contenido | Estado |
|---|---|---|
| 1 | Modelo de datos, símbolos, capas, láminas, salida DXF y AutoCAD en vivo, servidor MCP | **Listo (v0.1)** |
| 2 | Importar y depurar el plano arquitectónico (DWG/DXF), detectar muros, vanos y recintos | Pendiente |
| 3 | Motor de diseño NTC 2050: ubicación automática de tomas, iluminación, circuitos y tubería | Pendiente |
| 4 | Cálculos (cargas, conductores, regulación, protecciones, SPT, DPS), memoria RETIE y modelo 3D | Pendiente |

## Qué hace hoy (paso 1)

* **Modelo del proyecto** (`model.py`): recintos con área, perímetro y centroide; salidas con
  circuito, altura y rotación; circuitos; tableros; tuberías por muro, piso, techo,
  comunicaciones y acometida. Se guarda como JSON, así que el proyecto se puede reabrir,
  modificar y volver a dibujar.
* **Biblioteca de símbolos** (`symbols.py`) con tus convenciones: toma doble 120 V, GFCI, 220 V,
  salida especial, AA, condensadora, guardamotor, motor, transformador 12 V, comunicaciones,
  gabinete, tablero, medidor, más balas LED (3/5/9/12/18 W), colgante, aplique, cinta LED,
  sensor e interruptores. Cada símbolo es un **bloque real de AutoCAD** con atributo
  `CIRCUITO`, así que se puede contar o extraer con `DATAEXTRACTION`. Los textos de los
  símbolos (GFCI, 220, COM) y los números de circuito siempre quedan horizontales, aunque la
  salida esté girada sobre el muro.
* **Capas normalizadas** (`layers.py`): `ARQ-*` arquitectura en gris, `E-*` eléctrico,
  `COM-*` comunicaciones, `ANOT-*` rótulo y convenciones, `E-3D-*` para el modelo 3D. Cada
  capa tiene color, tipo de línea y grosor de impresión.
* **Láminas** (`render.py`): igual que tus planos de referencia, un pliego de 100 × 70,7 cm a
  1:50 por cada nivel, separado en **ILUMINACIÓN** y **TOMAS**, con el cuadro de
  convenciones y las cantidades **contadas automáticamente** para esa lámina, el rótulo y el
  marco.
* **Dos salidas con el mismo resultado**:
  * `DXFBackend`: genera el `.dxf` sin necesidad de tener AutoCAD.
  * `AutoCADBackend`: dibuja en el AutoCAD 2026 abierto mediante COM/ActiveX (solo Windows).
* **Servidor MCP** (`server.py`) con 13 herramientas: `crear_proyecto`, `abrir_proyecto`,
  `listar_proyectos`, `estado_proyecto`, `agregar_recinto`, `agregar_tablero`,
  `agregar_circuito`, `agregar_salidas`, `trazar_tuberia`, `eliminar_elemento`,
  `listar_simbolos`, `generar_dxf`, `dibujar_en_autocad`.

## Instalación en Windows

1. Instala **Python 3.12** desde python.org y marca *"Add python.exe to PATH"*.
2. Descomprime esta carpeta en `C:\ElectroMCP`.
3. Abre **PowerShell** en esa carpeta y ejecuta:

   ```powershell
   py -m venv .venv
   .venv\Scripts\pip install -e ".[preview]"
   ```

   Esto instala `ezdxf`, el SDK de MCP y `pywin32` (para hablar con AutoCAD).
4. Prueba la generación de DXF:

   ```powershell
   .venv\Scripts\python examples\demo_apartamento.py
   ```

   El resultado queda en `salidas\apartamento_demo.dxf`, con una vista previa en `.png`.
5. Prueba el dibujo en vivo: abre **AutoCAD 2026** y ejecuta:

   ```powershell
   .venv\Scripts\python examples\demo_apartamento.py --autocad
   ```

## Conectarlo a Claude Desktop

Edita `%APPDATA%\Claude\claude_desktop_config.json` y agrega:

```json
{
  "mcpServers": {
    "electromcp": {
      "command": "C:\\ElectroMCP\\.venv\\Scripts\\electromcp.exe",
      "env": { "ELECTROMCP_DIR": "C:\\Users\\TU_USUARIO\\Documents\\ElectroMCP" }
    }
  }
}
```

Reinicia Claude Desktop. Después puedes pedir cosas como: *"Crea el proyecto Casa San Miguel en
Circasia, agrega la sala de 6 × 5 m, un tablero TD-1 junto a la puerta, y dibújalo en AutoCAD."*

Los proyectos (`.json`) y los planos (`.dxf`) se guardan en la carpeta `ELECTROMCP_DIR`.

## Convenciones técnicas

* Unidades: **metros** en planta (1 unidad = 1 m); alturas en metros sobre el NPT.
* Rotación de una salida: 0° significa que su frente mira hacia +Y (la cara del muro queda
  en −Y). Una toma en un muro oeste que mira hacia el recinto lleva 270°.
* Tipos de línea en AutoCAD: se cargan desde `acadiso.lin` con `LTSCALE = 0.05`, adecuado
  para un dibujo en metros impreso a 1:50.
* Si el dibujo ya tiene un bloque con el mismo nombre (por ejemplo `TOMA_DOBLE`), **se respeta
  el tuyo**. Así puedes reemplazar cualquier símbolo por tu propio bloque.

## Pruebas

```powershell
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pytest
```

Las pruebas incluyen un AutoCAD simulado, que recorre todo el flujo COM sin Windows. La prueba
definitiva es la ejecución con `--autocad` en tu equipo.
