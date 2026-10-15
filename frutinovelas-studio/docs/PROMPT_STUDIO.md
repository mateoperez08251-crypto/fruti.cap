# Prompts de FRUTINOVELAS: skills, editor, API, CLI y MCP

## Empezar

Las skills están en `../.agents/skills/` desde la carpeta del estudio. `../AGENTS.md` orienta
a asistentes que trabajan en el repositorio. Para ChatGPT o asistentes que no cargan skills,
compartir [CHATGPT_DIRECTOR.md](CHATGPT_DIRECTOR.md), el guion y la imagen real. Un `.md`
no cambia el comportamiento de un chat que no lo ha leído.

En la app, **Revisar prompt H3** comprueba el borrador sin guardarlo ni generar. Si cambia
texto, duración o referencias, la revisión anterior se marca como desactualizada. Los errores
no borran contenido; la generación y su validación existente siguen separadas.

La revisión libre encuentra problemas estructurales comunes; no interpreta toda la historia.
Para comprobar intervalos, personajes silenciosos y diálogos simultáneos, usar el plan JSON.

## Alcance de las skills

- **General:** continuidad, sombras, física, actuación, cámara y sonido sirven para cualquier
  escena o sujeto. `DIRECTOR_CORE.md` establece este nivel.
- **Frutinovelas:** `FRUTINOVELAS_PREFERENCES.md` aplica tus preferencias a cualquier capítulo,
  sin imponer personajes, lugares ni una trama.
- **Historia concreta:** `FRUTINOVELAS_CONTINUITY.md` solo se carga al retomar la heladería.

Las entradas `.agents/skills/*/SKILL.md` dirigen a los procedimientos de `docs/skills/`.
El MCP publica esos mismos procedimientos; no mantiene copias divergentes. Las guías pueden
actualizarse en Git para futuras consultas, pero el servidor no aprende ni guarda nuevas
preferencias automáticamente. La petición actual prevalece sobre los valores predeterminados.

## CLI

Desde la carpeta que contiene `pyproject.toml`:

```powershell
py -3 -m uv sync --extra dev --frozen
py -3 -m uv run frutinovelas-prompts h3 examples/prompts/bruno_horn_i2va.json --output bruno_prompt.json
py -3 -m uv run frutinovelas-prompts image examples/prompts/qwen_edit_cocardo.json --output cocardo_prompt.json
py -3 -m uv run frutinovelas-prompts schema --output prompt_schemas.json
```

En Linux/macOS usar `uv run`. El resultado contiene `prompt`, `profile`, `issues` y, para H3,
`frames` y `effective_seconds`. Copiar solo el valor de `prompt` al editor o nodo apropiado.
Esto no es un workflow ComfyUI ni inicia una inferencia. El perfil declarado no cambia el
servidor conectado. Revisar las advertencias antes de guardar.

Para revisar texto existente, crear un JSON con `prompt`, `duration_seconds`,
`has_start_image` y `has_end_image`; ejecutar `frutinovelas-prompts lint archivo.json`.
Códigos de salida: 0 sin errores bloqueantes, 1 si el linter detecta errores, 2 por entrada
inválida o archivo ilegible. Las advertencias son orientativas.

## Contrato H3Draft

Consultar `frutinovelas-prompts schema`, la clase en `src/frutinovelas/prompts.py` y ejemplos.

| Campo | Uso |
|---|---|
| `profile`, `mode` | Perfil declarado y modo I2VA/FL2VA |
| `duration_seconds` | Solicitud de 4–15 s; se informa la duración efectiva |
| `has_start_image`, `has_end_image` | Declaraciones del llamador, que debe comprobar assets reales |
| `visual_style`, `lighting`, `background`, `continuity` | Dirección visual en inglés |
| `characters[].key/description/voice` | Identidad; `voice: null` significa personaje silencioso |
| `shots[].start/composition/camera` | Inicio, encuadre y cámara; el primer plano empieza en 0 |
| `shots[].beats[]` | `start`, `end`, `action`; opcional `sound` o `speaker` + `dialogue` |
| `language`, `delivery`, `voiceover` en beat | Idioma, entrega y narración fuera de pantalla |
| `end_state` | Resultado observable |
| `overall_soundscape`, `non_diegetic_music` | Ambiente y música separados |

Los tiempos de beat son absolutos dentro del clip. Deben caber en el plano y la duración
solicitada. Se permite superponer acciones visuales, pero no dos turnos de voz. Para coros
o frases que crucen cortes, redactar manualmente conforme a la guía oficial: el compilador
no representa esos casos. Los personajes listados son visibles; una voz externa sin personaje
visible requiere dirección manual.

No insertar etiquetas estructurales en los campos: el compilador añade campos H3, IDs de
voz por orden de intervención, anclajes y etiquetas. No traduce ni reescribe diálogos.
`ImageDraft` distingue T2I de EDIT; EDIT exige referencia y listas `changes` y `preserve`.
Sus instrucciones describen un fotograma sin tiempos ni voces H3.

## API local

Endpoints bajo `/api/v1`, documentados en `/docs`:

| Endpoint | Entrada | Efecto |
|---|---|---|
| `POST /prompts/h3` | H3Draft | Prompt y comprobaciones |
| `POST /prompts/image` | ImageDraft | Instrucciones Qwen |
| `POST /prompts/lint` | LintRequest | Problemas de texto y duración |

Respetan el middleware de autorización existente. No escriben BD ni llaman servicios
externos. Guardar sigue usando `PATCH /scenes/{id}` con `expected_revision`; generar requiere
la acción específica del programa. Los prompts guardados y el historial se conservan.

## MCP local de preparación

El comando que antes apuntaba a un módulo ausente tiene implementación:

```powershell
py -3 -m uv run frutinovelas-mcp
```

Usa el SDK **MCP 2.x** del proyecto, `MCPServer` y transporte **stdio** por defecto, para clientes que
lanzan procesos locales. También admite **Streamable HTTP** local para túneles privados. Conserva estas cuatro herramientas:

| Herramienta | Uso |
|---|---|
| `get_directing_guidance` | Leer skill, reglas generales, modelos y preferencias antes de redactar |
| `prepare_h3_prompt` | Compilar el plan de animación H3 |
| `prepare_image_prompt` | Preparar imagen o edición Qwen |
| `review_h3_prompt` | Comprobar un prompt H3 existente |

`get_directing_guidance` acepta `task`: `story`, `image`, `animation` o `review`; `preset`:
`frutinovelas` o `general`; e `include_example_story` (falso por defecto). Por ejemplo:

```json
{"task":"animation","preset":"general","include_example_story":false}
```

El modo general permite otros sujetos y estilos. Al compilar, especificar `visual_style`,
`language` y `non_diegetic_music` según la petición para sustituir sus valores predeterminados.
No habilita otros modelos ni cambia el canvas del servidor.

Recursos: catálogo `frutinovelas://guides` y plantilla `frutinovelas://guides/{name}`.
Prompt MCP: `direct_scene(request, task, preset)` prepara instrucciones de dirección para
la petición; no es un prompt H3 compilado. Las instrucciones iniciales del MCP piden consultar
las guías, pero cada cliente decide cómo usarlas. La herramienta también devuelve el contenido
para clientes que no muestren recursos o prompts MCP.

Ejemplo para un cliente local compatible con `mcpServers`:

```json
{
  "mcpServers": {
    "frutinovelas-prompts": {
      "command": "uv",
      "args": ["--directory", "D:/ruta/real/fruti.cap/frutinovelas-studio", "run", "frutinovelas-mcp"]
    }
  }
}
```

Sustituir la ruta por la carpeta que contiene `pyproject.toml`; `uv` debe estar en el PATH del
cliente. No publicar stdio como una URL. Para conectar mediante un túnel privado:

```cmd
py -3.12 -m uv run --frozen frutinovelas-mcp --transport streamable-http --host 127.0.0.1 --port 8766
```

El endpoint es `/mcp`. El servidor solo acepta bind en loopback y mantiene las comprobaciones
de Host/Origin del SDK. Usa sesiones HTTP sin estado; cada llamada vuelve a leer las guías.
La conexión con ChatGPT requiere configurar el túnel y el plugin conforme a
[la guía de CMD](CONEXION_MCP_Y_TUNNEL.txt). Cambiar `--port` si ya existe otro MCP en 8766.
Las guías y el compilador no requieren ComfyUI. Las nuevas herramientas Studio permiten
leer escenas, biblioteca y guion, guardar ambos prompts y encolar Qwen con referencias.
Necesitan la API local abierta; Qwen necesita su flujo activo en RunPod. Ver
[Personajes y escenas](PERSONAJES_Y_ESCENAS.md). Una conexión MCP correcta no verifica
el estado del servidor de inferencia. El montaje automático es opcional y usa
los prompts y duraciones ya guardados. Ver [guía de escenas y duración](GUIA_ESCENAS_Y_DURACION.md).

Los documentos se incluyen en el paquete Python: las guías siguen disponibles en una instalación
de la wheel sin depender de una carpeta `.agents` externa.

## Ejemplos

| Archivo en `examples/prompts/` | Lo que demuestra |
|---|---|
| `bruno_horn_i2va.json` | Bocina antes de hablar, mano derecha y auto estacionado |
| `freezer_sequential_i2va.json` | Apagado, un segundo de pausa, movimiento con roce |
| `dario_exit_fl2va.json` | Transferencia de peso y fotograma final efectivo |
| `qwen_bruno_start.json` | Imagen con espacio para el gesto |
| `qwen_edit_cocardo.json` | Corregir expresión conservando diseño |

Los ejemplos son planes, no imágenes adjuntas. `has_start_image: true` no carga un archivo;
usarlo solo tras asociar una referencia correcta.

## Validación

Ejecutar pytest y build/lint del frontend conforme al README. Los tests verifican literalidad,
límites, turnos, referencias, API, CLI y MCP. La calidad visual requiere revisar una generación
corta con el perfil real antes de producir un capítulo completo.
