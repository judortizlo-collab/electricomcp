# ElectroMCP

Servidor MCP para diseño eléctrico residencial y comercial en Colombia (NTC 2050, RETIE),
que dibuja en **AutoCAD 2026 en vivo** o genera **archivos DXF**.

> El diseño que produce esta herramienta es un borrador técnico. La revisión, la firma y la
> responsabilidad del diseño son del ingeniero electricista con matrícula profesional vigente.

## Estado del proyecto

| Paso | Contenido | Estado |
|---|---|---|
| 1 | Modelo de datos, símbolos, capas, láminas, salida DXF y AutoCAD en vivo, servidor MCP | **Listo (v0.1)** |
| 2 | Importar y depurar el plano arquitectónico (DWG/DXF), detectar muros, vanos, recintos y apartamentos | **Listo (v0.2)** |
| 3 | Motor de diseño NTC 2050: ubicación automática de tomas, iluminación, circuitos, tableros, tubería, cuadros de carga y unifilares | **Listo (v0.3)** |
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
* **Servidor MCP** (`server.py`) con 13 herramientas del paso 1 (y 5 más del paso 2): `crear_proyecto`, `abrir_proyecto`,
  `listar_proyectos`, `estado_proyecto`, `agregar_recinto`, `agregar_tablero`,
  `agregar_circuito`, `agregar_salidas`, `trazar_tuberia`, `eliminar_elemento`,
  `listar_simbolos`, `generar_dxf`, `dibujar_en_autocad`.

## Paso 2: depuración e interpretación del plano arquitectónico

Módulo `electromcp.arquitectura`. Toma un plano tal como lo entrega el arquitecto (capas con
nombres arbitrarios, bloques anidados y espejados, bloques dinámicos, basura lejos del dibujo,
cotas, mobiliario, achurados) y produce:

* **DXF depurado** (`*_depurado.dxf`): dibujo nuevo, en metros, solo con capas `ARQ-*` en gris:
  muros con achurado sólido, columnas, puertas (hoja y barrido), ventanas, escaleras, aparatos
  sanitarios y de cocina, ejes, y el nombre y área de cada recinto. Sin bloques heredados, sin
  cotas, sin muebles sueltos: queda como base limpia para las láminas eléctricas.
* **Plano de verificación** (`*_verificacion.png`): recintos coloreados por apartamento, puertas
  y ventanas detectadas, y la lista de puntos "para revisar".
* **Reporte** (`*_reporte.json`): recintos con nombre, uso, área, perímetro y unidad; puertas
  (ancho y recintos que conecta); ventanas; aparatos (inodoro, ducha, lavamanos, cocina...);
  clasificación de cada capa con el criterio usado.
* **Carga al proyecto**: muros, vanos y recintos quedan en el `Proyecto`, listos para el paso 3.

Cómo interpreta el plano:

1. **Lectura**: explota todos los bloques (también los espejados y los dinámicos), aplica la regla
   de la capa 0, convierte a metros (`$INSUNITS`, o lo deduce del tamaño) y descarta lo que está
   lejos de la planta.
2. **Capas**: las clasifica por nombre (español e inglés: MUROS, A-WALL, PUERTAS, COTAS...) y, si
   el nombre no dice nada (`_F5`, `252`), por geometría: figuras delgadas y alargadas = muros,
   cuadradas pequeñas = columnas, rellenos con patrón = achurados. Todo se puede corregir con
   `mapa_capas`, p. ej. `{"_F5": "muros", "BLANCO": "ignorar"}`.
3. **Muros**: figuras cerradas delgadas, achurados sólidos de muro y caras delgadas que salen de
   poligonizar muros dibujados con líneas sueltas (incluidos tramos cortos como jambas).
4. **Puertas**: por el barrido (arco de 60° a 100°, radio 0,45 a 1,30 m) con la bisagra en un muro;
   la hoja cerrada define el vano. **Ventanas**: su linework cierra el vano. También cierran vanos
   las líneas que unen dos muros en la dirección del muro (vidrios, barandas) y los vacíos con su "X".
5. **Recintos**: el espacio libre entre muros y vanos cerrados. Las rendijas de dibujo menores a
   8 cm se consideran cerradas.
6. **Nombres y usos**: por los textos dentro de cada recinto. Las notas ("Ven. Mecánica",
   "Ruta de evacuación", alarmas) se guardan como observaciones, no como nombre. Un espacio
   abierto con varios usos (sala-comedor-cocina) se divide en zonas aproximadas.
7. **Apartamentos**: recintos unidos por puertas sin pasar por zonas comunes; el nombre sale del
   texto "APTO 01", "Apartamento 302", "Local 1"...

Prueba rápida:

```powershell
.venv\Scripts\python examples\depurar_plano.py C:\Planos\Apartamentos.dxf
```

Herramientas MCP nuevas: `analizar_plano`, `depurar_plano`, `corregir_recinto`,
`convertir_dwg_a_dxf`, `exportar_dibujo_activo`.

**DWG**: ezdxf lee DXF. Un DWG se convierte solo si está instalado el *ODA File Converter*
(gratuito) o si AutoCAD 2026 está abierto: se abre una copia del DWG, se guarda como DXF y se
cierra; el original no se toca. También se puede guardar el plano como DXF desde AutoCAD
(`GUARDARCOMO` → DXF 2018).

## Paso 3: motor de diseño (NTC 2050 / RETILAP)

Módulo `electromcp.diseno`. A partir de los recintos del paso 2 (o de recintos dibujados a mano)
diseña la instalación completa y la deja en el proyecto, lista para dibujar:

* **Tomacorrientes** (`salidas.py`)
  * 210.52(A): cada tramo de pared ≥ 0,6 m, medido sin interrupción por puertas (las ventanas y
    columnas cuentan como pared), con tomas de modo que ningún punto quede a más de 1,8 m. Se
    alejan de las esquinas y se **verifica** la cobertura; si falla, se agrega una toma.
  * 210.52(C): mesón de cocina ubicado con el lavaplatos y la estufa del plano; tomas GFCI a
    1,10 m, ningún punto a más de 0,6 m, nunca detrás de la estufa ni del grifo.
  * 210.52(D): baños con toma GFCI junto al lavamanos, fuera de la zona de la ducha (406.9(C)).
    Si el lavamanos no está dibujado, se ubica al lado opuesto de la ducha.
  * 210.52(F) / 210.8(A)(10): toma GFCI para la lavadora; 210.52(H): pasillos ≥ 3 m.
  * Nevera como salida especial en un circuito de pequeños artefactos; estufa y calentador
    eléctricos (opcionales) en circuito individual de 240 V.
  * Salida de comunicaciones junto a una toma en sala, estudio y alcobas.
* **Iluminación** por método de lúmenes con la iluminancia media de RETILAP por uso (tabla
  editable), índice del local K y coeficiente de utilización. Para cada recinto o zona prueba
  balas de 9, 12 y 18 W y elige la de menor costo energético que cumpla iluminancia y
  uniformidad; se reporta la iluminancia calculada.
* **Interruptores** (210.70(A)) en el lado de la chapa de la puerta por la que se entra al
  recinto, a 1,20 m; doble o triple según las zonas del espacio abierto; conmutables en pasillos
  con dos puertas; extractor con su propia tecla en los baños con nota "Ven. Mecánica". Las letras
  (a, b, c) unen cada interruptor con sus luminarias en el plano. Zonas comunes con sensor de
  movimiento.
* **Circuitos**: alumbrado (15 A, #14), tomas generales (20 A, #12, máximo 8 por circuito),
  mínimo **dos de pequeños artefactos** con el mesón repartido en ambos (210.11(C)(1)), baños
  (210.11(C)(3)), lavandería (210.11(C)(2)) y especiales. Fases A/B balanceadas.
* **Tableros y medida**: un tablero por apartamento junto a la entrada (lado de la chapa, después
  del interruptor), tablero de servicios generales y centro de medición en la zona común, con el
  alimentador de cada unidad.
* **Tubería**: árbol de recorrido mínimo desde el tablero, por placa de techo para alumbrado y por
  placa de piso para tomas, sin salirse de la unidad. Cada tramo sabe qué circuitos lleva: con eso
  se cuentan conductores y se elige el diámetro PVC por llenado (Cap. 9, Tablas 1, 4 y 5).
* **Cuadro de cargas** (`cuadro.py`): carga por circuito y fase, corriente, protección,
  conductores, tubo, longitud y **regulación**; demanda de la unidad por Sección 220 (33 VA/m²,
  1500 VA por circuito de pequeños artefactos y lavandería, Tabla 220.42), protección general y
  alimentador con su regulación.
* **Verificación**: lista de cada requisito revisado, con artículo, valor obtenido y si cumple.
* **Láminas**: ILUMINACIÓN y TOMAS con circuitos, letras de encendido y tubería rotulada, más la
  lámina nueva **CUADROS DE CARGA Y DIAGRAMAS UNIFILARES** (medidor, protección general, DPS,
  barraje, un ramal por circuito y puesta a tierra).

Todos los criterios están en `ParametrosDiseno` (`normas.py`), con el artículo que aplica cada
uno: se pueden cambiar por proyecto (`disenar_instalacion(parametros={...})`). Lo que el motor
ubica queda marcado `auto`: al rediseñar se reemplaza, y lo que usted agregue a mano se conserva.

Prueba completa con un plano:

```powershell
.venv\Scripts\python examples\disenar_instalacion.py C:\Planos\Apartamentos.dxf
.venv\Scripts\python examples\disenar_instalacion.py C:\Planos\Apartamentos.dxf --estufa electrica --autocad
```

Herramientas MCP nuevas: `disenar_instalacion`, `cuadro_de_cargas`, `verificar_diseno`,
`parametros_diseno`; `generar_dxf` y `dibujar_en_autocad` aceptan `laminas="todo"` (por defecto).

> Normas de referencia: NTC 2050 segunda actualización (2020), RETIE 2024 y RETILAP. Los valores
> de la norma están en tablas editables; verifíquelos contra el texto vigente antes de firmar.

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
