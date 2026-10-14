# FRUTINOVELAS Studio — Especificación para construir el programa

Fecha: 14 de octubre de 2026. Idioma de la interfaz y documentación: español.

## 1. Encargo al modelo desarrollador

Construye una aplicación funcional llamada **FRUTINOVELAS Studio** para preparar capítulos de una serie, gestionar sus escenas e imágenes, enviarlas a ComfyUI para generar animaciones, revisar versiones, repetir escenas y montar el capítulo. Añade un servidor MCP para que ChatGPT o Claude puedan consultar el proyecto, revisar imágenes y guardar los prompts que redacten.

Este documento es una orden de implementación, no una petición de recomendaciones. Crea el código, instaladores de desarrollo, migraciones, documentación y pruebas. Trabaja por fases hasta completar el alcance obligatorio. No entregues únicamente una maqueta, botones sin acción, pseudocódigo o progreso simulado.

Si recibes un repositorio, trabaja en él y respeta sus instrucciones. Si aún no existe, crea el proyecto local y prepara el repositorio para GitHub. Publica o sube cambios cuando el usuario haya proporcionado el repositorio y autorización; mientras tanto deja el código y commits preparados. No inventes una URL de GitHub ni una conexión a ComfyUI.

Resuelve las decisiones rutinarias con esta especificación. Solicita solamente datos que bloqueen una integración real: flujo ComfyUI exportado en formato API, URL accesible y, si corresponde, autenticación. Continúa construyendo los módulos independientes mientras falten esos datos.

## 2. Experiencia que necesita el usuario

El usuario quiere cargar las imágenes y los prompts de un capítulo completo. Cada escena tiene su propio tiempo y puede tener **imagen inicial y final**, o solamente inicial. El programa debe generar las escenas mediante su ComfyUI, mostrarlas y permitir repetir exclusivamente las que no le gusten.

Recorrido principal:

1. Crear un proyecto y un capítulo.
2. Importar su guion y continuidad en Markdown.
3. Crear o importar escenas en orden.
4. Asignar imagen inicial, imagen final opcional, prompt y duración.
5. Seleccionar un perfil del flujo ComfyUI y validar la configuración.
6. Pulsar **Generar escena** o **Generar capítulo**.
7. Revisar cada video con su audio.
8. Elegir una versión, o pulsar **Regenerar** con nueva semilla o prompt revisado.
9. Unir las versiones seleccionadas, respetando el orden y los recortes elegidos.
10. Exportar el capítulo en MP4 y, opcionalmente, su proyecto transportable en ZIP.

El asistente conectado por MCP debe poder ayudar a preparar los prompts sin copiarlos manualmente entre el chat y el programa.

## 3. Alcance y decisiones técnicas

Implementa una **aplicación local con interfaz web**, abierta en el navegador del usuario. Windows es la plataforma principal; admite Linux cuando sea viable.

| Componente | Elección |
| --- | --- |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Interfaz | React, TypeScript y Vite |
| Base de datos | SQLite mediante SQLAlchemy 2.x; Alembic para migraciones |
| Cola | Trabajos persistentes en SQLite y un coordinador separado |
| Conexión a ComfyUI | HTTP más WebSocket, con reconciliación por historial |
| Archivos | Directorio de datos persistente fuera del código |
| Video y audio | FFmpeg y FFprobe como ejecutables externos |
| MCP | SDK oficial de Python `mcp`, stdio y Streamable HTTP |
| Pruebas | pytest para backend y Playwright para recorridos de interfaz |

No necesitas Redis, Celery, PostgreSQL, Electron ni Docker para la primera versión. No instales PyTorch ni modelos de video en el entorno de esta aplicación: las inferencias se ejecutan en el ComfyUI existente. Docker y un empaquetado de escritorio pueden añadirse después.

La primera versión debe funcionar sin claves de OpenAI o Anthropic: los prompts se introducen manualmente o son redactados por el chat conectado mediante MCP. El motor de video es ComfyUI, independiente del modelo que escribe los prompts.

## 4. Dependencias e instalación

Antes de fijar versiones, consulta las fuentes oficiales y comprueba compatibilidad. Entrega `uv.lock` y `package-lock.json` con las versiones realmente instaladas y probadas. No uses `latest` en los arranques cotidianos ni inventes números de versión.

### Requisitos del sistema

- Python 3.12.
- Node.js 22.12 o superior compatible con la versión elegida de Vite; documenta la versión probada.
- Git.
- FFmpeg y FFprobe accesibles mediante PATH, o rutas configurables desde la aplicación.
- ComfyUI ya instalado en una máquina local o remota accesible.
- GPU únicamente donde corre ComfyUI. La interfaz y el servidor MCP no requieren una GPU propia.

Proporciona instrucciones para instalar estos requisitos en Windows y Linux. Comprueba su existencia y muestra mensajes claros cuando falten. Evita descargas de modelos o cambios en el entorno de ComfyUI por iniciativa del instalador.

### Paquetes Python

Obligatorios:

```text
fastapi
uvicorn[standard]
pydantic
pydantic-settings
sqlalchemy
alembic
httpx
websockets
python-multipart
Pillow
platformdirs
mcp[cli]
```

Desarrollo:

```text
pytest
pytest-asyncio
respx
ruff
```

Usa la versión estable compatible del SDK MCP. La guía oficial consultada utiliza SDK Python 2.x y `MCPServer`; verifica sus importaciones y transportes en la versión que fijes. No mezcles ejemplos antiguos de FastMCP con otra API del SDK. Si un paquete necesita una dependencia transitiva adicional, declárala cuando tu código la importe directamente.

Bootstrap para el desarrollador, desde la raíz:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip uv
.\.venv\Scripts\uv.exe sync --extra dev
```

En Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip uv
.venv/bin/uv sync --extra dev
```

Estas órdenes presuponen que el implementador ya creó `pyproject.toml` y el lock. La instalación normal debe usar `uv sync --frozen` después de entregar el lock validado.

### Paquetes de interfaz

Usa `react`, `react-dom`, `@tanstack/react-query`, `react-router-dom`, `zod`, `lucide-react`, `@dnd-kit/core`, `@dnd-kit/sortable` y `@dnd-kit/utilities`. Para desarrollo: `vite`, `typescript`, `@vitejs/plugin-react`, los tipos de React, ESLint y `@playwright/test`.

La base se puede crear con:

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install @tanstack/react-query react-router-dom zod lucide-react @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
npm install -D @playwright/test
```

Después de resolver y validar dependencias, entrega lock y usa `npm ci`. CSS propio y componentes reutilizables son suficientes; no añadas otro sistema de estilos por obligación.

### Arranque que debe quedar implementado

```text
python -m frutinovelas.api
python -m frutinovelas.worker
python -m frutinovelas.mcp_server --transport stdio
python -m frutinovelas.mcp_server --transport http
```

Implementa esas entradas de módulo y documenta sus flags. El usuario no debe escribir SQL ni tocar el grafo para arrancar. Entrega `scripts/setup.ps1`, `scripts/start.ps1`, equivalentes `.sh` y una orden `doctor` que revise dependencias, almacenamiento y conexión. En desarrollo, Vite usa proxy a `/api`; en producción FastAPI sirve el frontend construido. El arranque normal abre una sola dirección, por ejemplo `http://127.0.0.1:8765`.

## 5. Estructura del repositorio

```text
frutinovelas-studio/
  README.md
  pyproject.toml
  uv.lock
  .env.example
  .gitignore
  src/frutinovelas/
    api.py
    worker.py
    mcp_server.py
    config.py
    models/
    schemas/
    services/
    comfy/
      client.py
      workflow_adapter.py
      output_adapters.py
    media/
    routes/
  migrations/
  frontend/
    package.json
    package-lock.json
    src/
  scripts/
  tests/
    fixtures/
  examples/
    chapter.example.json
    workflow_profile.example.json
  docs/
    INSTALL_WINDOWS.md
    INSTALL_LINUX.md
    COMFYUI_SETUP.md
    MCP_CHATGPT.md
    MCP_CLAUDE.md
    PROJECT_FORMAT.md
    TROUBLESHOOTING.md
  .github/workflows/ci.yml
```

Los ejemplos de perfiles deben estar etiquetados como ejemplos, sin atribuirles compatibilidad con el flujo real del usuario. En GitHub guarda código, documentación y fixtures pequeños. Excluye `.env`, claves, SQLite, videos, modelos, datos de capítulos, entornos y `node_modules`.

## 6. Almacenamiento y modelo de datos

Usa `platformdirs` para un directorio de usuario persistente configurable mediante `FRUTINOVELAS_DATA_DIR`. No dependas del directorio actual del proceso. Copia las imágenes importadas al almacenamiento gestionado para que cambiar o borrar el archivo original no rompa el proyecto.

Entidades mínimas:

| Entidad | Datos principales |
| --- | --- |
| Project | UUID, nombre, idioma, formato, fechas |
| Chapter | UUID, proyecto, título, orden, guion Markdown, continuidad, revisión |
| Scene | UUID, capítulo, orden, título, descripción, duración solicitada, estado derivado |
| Asset | UUID, tipo, ruta gestionada, hash SHA-256, tamaño, dimensiones o metadatos |
| SceneRevision | UUID, escena, prompt, assets inicio/final, parámetros, perfil, autor, revisión |
| WorkflowProfile | grafo API original, hash, versión, mapeo de entradas, capacidades |
| GenerationJob | UUID, revisión congelada, semilla, estado, prompt_id, endpoint, intentos, fechas |
| GenerationVersion | UUID, escena, trabajo, rutas de video/audio, metadatos, notas, selección |
| Assembly | UUID, capítulo, selección y recortes congelados, estado, resultado |
| AuditEvent | evento, actor UI/MCP, entidad, fecha; sin credenciales |

La edición de un prompt crea una revisión. Una generación conserva una instantánea inmutable de prompt, referencias, parámetros, perfil, semilla y flujo materializado. Cambiar una escena durante una ejecución afecta a trabajos futuros, nunca al trabajo en curso.

El UUID de escena no cambia al reordenarla. Seleccionar una versión no elimina las demás. Una nueva generación exitosa se marca **pendiente de revisión**; el usuario la selecciona explícitamente. No sustituir silenciosamente una versión ya elegida.

SQLite: transacciones cortas, claves foráneas activadas, timeout ocupado y política de conexiones documentada. Validar WAL y concurrencia en el sistema probado; un solo coordinador activo obtiene un lease renovable en la base de datos para evitar despachos dobles. Nunca mantengas una transacción abierta durante una inferencia o descarga.

## 7. Pantallas y controles

### Proyecto y capítulo

Listado, crear, renombrar, archivar; editor del guion y continuidad; importar/exportar. Barra de estado para ComfyUI, cola y almacenamiento. Interfaz en español con buena legibilidad y diseño compacto.

### Escenas

Lista o cuadrícula de tarjetas con número, título, duración, miniaturas de inicio/final y estado. Reordenar con arrastre y también botones accesibles. La lista mantiene el orden del montaje aunque los trabajos terminen en otro orden.

### Editor de escena

- Dos zonas de imágenes claramente rotuladas: **Inicio** y **Final opcional**.
- Subida PNG/JPEG/WebP; validar el archivo real, su tamaño y dimensiones.
- Vista ampliada; reemplazar una referencia crea revisión.
- Editor multilínea del prompt; conservar etiquetas `<d>`, saltos de línea y Unicode.
- Duración en segundos, semilla manual o aleatoria y perfil.
- Parámetros avanzados plegables: resolución, fps, pasos y sampler cuando el perfil los permita.
- Acciones: validar, guardar, generar, duplicar y abrir versiones.

### Cola

Estados honestos: esperando, enviando, en cola ComfyUI, ejecutando, recuperando resultados, listo, error, cancelado y **estado incierto**. Progreso por pasos/nodos cuando ComfyUI lo proporcione; si no existe un porcentaje global real, mostrar etapa y tiempo transcurrido, nunca un porcentaje ficticio.

### Revisión

Reproductor HTML5 con audio, pausa, avance, notas, comparación de versiones y botón **Usar esta versión**. Regenerar con nueva semilla por defecto; ofrecer reutilizar semilla para comparar cambios. Con la misma semilla y entradas idénticas puede obtenerse el mismo resultado o reutilizarse caché: no anunciar variedad garantizada.

### Montaje

Lista ordenada de versiones elegidas con puntos de entrada/salida, duración resultante y controles de audio por clip. Mostrar escenas sin selección o con selección desactualizada antes de exportar. No exportar omitiéndolas sin autorización explícita.

## 8. Integración real con ComfyUI

El backend recibe la URL de ComfyUI, por ejemplo `http://127.0.0.1:8188`, y headers de autenticación opcionales. Guarda la configuración protegida fuera del repositorio y oculta secretos en logs. Permite cambiar la URL cuando un túnel de Colab expire; los trabajos conservan la identidad del endpoint al que fueron enviados.

Usa las rutas oficiales de la instalación realmente conectada:

| Operación | Ruta |
| --- | --- |
| Comprobar servidor | `GET /system_stats` |
| Consultar tipos de nodos | `GET /object_info` |
| Subir referencia | `POST /upload/image` multipart |
| Enviar grafo API | `POST /prompt` |
| Progreso | `/ws?clientId=...` WebSocket |
| Consultar cola | `GET /queue` |
| Recuperar ejecución | `GET /history/{prompt_id}` |
| Descargar salida compatible | `GET /view` con filename/subfolder/type |
| Retirar pendiente | `POST /queue` con eliminación de IDs, según contrato actual |
| Interrumpir actual | `POST /interrupt` |

Implementa el cliente con timeouts separados de conexión, petición y ejecución. Los videos grandes se descargan por streaming a archivo temporal; valida el resultado y renómbralo atómicamente. Nunca confíes únicamente en la extensión para dar un trabajo por terminado.

Conecta WebSocket antes del despacho o reconcilia eventos perdidos mediante cola e historial. Filtra los eventos por `prompt_id`; una conexión compartida puede recibir noticias de otras ejecuciones. Maneja `progress`, `executing`, `executed`, errores e interrupciones según la instalación. Verifica los esquemas oficiales y el código real antes de implementarlos.

Una ejecución finalizada no implica que el MP4 ya esté disponible: procesa las salidas del nodo configurado y verifica el archivo con FFprobe. Conserva audio nativo; si el flujo entrega audio y video separados, combina ambos conservando sincronía y duración.

### Salidas de nodos personalizados

MiniMax H3 y guardadores de video pueden retornar estructuras diferentes (`videos`, `gifs`, archivos bajo `images` u otras). Define un adaptador de salidas por perfil y por nodo de guardado. No hagas depender toda la integración de un único nombre de campo.

Usa nombres retornados por ComfyUI sin reconstruir rutas arbitrarias. `/view` debe probarse con el tipo de salida real. Si un nodo no expone archivos descargables por la API estándar, informa la limitación y añade un adaptador documentado, o lectura de carpeta compartida configurada explícitamente. No declare éxito si solamente se recibió una miniatura.

## 9. Importación y mapeo del flujo

Solicita el **JSON en formato API** del flujo que ya funciona con el usuario. Un JSON de interfaz con `nodes`, `links` y posiciones no es automáticamente el mismo formato. Detecta el tipo y explica cómo exportar el adecuado; no inventes una conversión para nodos desconocidos.

El perfil almacena el grafo original y un mapeo editable:

- Entrada de imagen inicial.
- Entrada de imagen final y método para deshabilitarla cuando falte.
- Prompt positivo y, solamente si existe, negativo.
- Semilla; pueden existir varias entradas enlazadas de semilla.
- Duración o número de frames.
- fps, ancho/alto, pasos y controles admitidos.
- Nodo(s) de guardado, prefijo de salida y adaptador de resultados.

Cada campo apunta a `node_id` y nombre de input reales. La UI muestra candidatos obtenidos del grafo y de `/object_info`, títulos y clases. Permite validarlos con un trabajo de prueba. Los IDs de los ejemplos son placeholders y jamás deben despacharse como flujo real.

Materializa cada trabajo sobre una **copia** del grafo importado y cambia solamente los campos mapeados. No alteres la selección de modelos, LoRA, sampler, conexiones o encoder sin una edición expresa del perfil.

### Modos

1. **I2VA:** inicio presente, final ausente. Admitirlo solo si el perfil tiene una ruta válida para esta configuración.
2. **FL2VA:** inicio y final presentes.

Los nombres de los checkpoints no determinan por sí solos si el grafo acepta omitir el fotograma final. No envíes una imagen vacía ni dupliques la inicial como final por conveniencia. Requiere bypass explícito, ruta del grafo o perfil alternativo validado.

Mostrar resolución de salida y aspect ratio reales. Si las dos referencias tienen distintas proporciones, ofrecer un preprocesado explícito que preserve los originales; no recortar ni estirar silenciosamente personajes. Guardar qué transformación se utilizó.

### Duración real

Separar `requested_duration_seconds`, `computed_frames` y `actual_duration_seconds`. El adaptador del perfil define la cuantización que exige el nodo real. Algunos flujos H3 usan una rejilla de frames; no asumir que `segundos × fps` sirve en todos.

Como antecedente del proyecto, se mencionó una rejilla `17k+5` y resultados de 124 frames a 24 fps para unos 5,17 s, y 243 frames para unos 10,125 s. Esos valores son referencias de un flujo anterior, no una regla universal ni una prueba del grafo conectado. Verificar la fórmula, redondeo y mínimos/máximos en los nodos reales. Enseñar la duración efectiva antes de generar y permitir recortar en montaje.

## 10. Cola, regeneración y recuperación

Despacha una inferencia a la vez por endpoint por defecto, evitando saturar VRAM. La cola del programa es persistente; el coordinador envía el siguiente trabajo cuando el anterior termina, falla o queda resuelto. No es necesario mandar todo el capítulo de golpe a la cola externa.

Transiciones mínimas:

```text
pending -> submitting -> queued -> running -> collecting -> succeeded
                                                    \-> failed
pending/queued -> canceled
submitting/running -> unknown -> reconciled state
```

Guarda `prompt_id` tan pronto se reciba. Usa idempotencia en tus endpoints para doble clic y peticiones MCP repetidas. Si la respuesta de `POST /prompt` se pierde, no hagas un reenvío ciego: ComfyUI pudo aceptar el trabajo. Reconcilia con los IDs y metadatos que el servidor soporte; utiliza un prompt_id elegido por cliente solo si esa instalación lo admite. Si no puedes demostrar el estado, marca **incierto** y ofrece resolver o repetir explícitamente.

Al reiniciar el programa, consulta cola e historial de los trabajos conocidos; no reinicies automáticamente escenas completas. Una desconexión WebSocket activa reconexión y consultas HTTP con backoff. Una conexión recuperada no autoriza repetir la inferencia.

### Cancelación

- Pendiente local: marcar cancelado.
- En cola externa: retirar exclusivamente su ID mediante el contrato de `/queue`.
- En ejecución: `/interrupt` detiene el trabajo global actual. Usarlo solamente tras verificar que el prompt en ejecución pertenece al trabajo solicitado y al endpoint correcto. Si otro usuario cambió el trabajo activo o no se puede garantizar propiedad, no interrumpirlo y comunicar el estado.
- No vaciar toda la cola de ComfyUI para cancelar un capítulo.

### Regeneración

Crear un nuevo trabajo y nueva versión, con semilla nueva por defecto y las revisiones elegidas. Conservar todos los anteriores, notas y selección. Un fallo o cancelación no borra una versión exitosa. Permitir prioridad a una escena repetida sin alterar el orden narrativo.

## 11. Montaje y exportación

Usa FFprobe para registrar resolución, fps, duración, codecs y pistas. Ensambla una instantánea de escenas y versiones seleccionadas para que cambios posteriores no alteren un montaje en curso.

Exportación MP4: H.264, `yuv420p`, AAC cuando haya audio y `faststart`. Ajustes predeterminados sugeridos: 768×1344 y 24 fps si coinciden con los clips del usuario; permitir cambiarlos. No anunciar 4K nativo cuando las fuentes no lo sean. Mantener proporción: letterbox/pillarbox por defecto; recorte únicamente elegido por el usuario.

Normaliza los clips a un formato común antes de concatenar. Solo usar copia directa de streams si codec, parámetros, timebase y pistas cumplen los requisitos comprobados. Recorta audio y video juntos; no cortes voces al ajustar una duración arbitraria. Los clips sin audio reciben silencio de longitud correspondiente para conservar la estructura de pistas.

Inicialmente cortes directos y audio original. Música opcional mediante importación del usuario, desactivada por defecto. No añadir música generada ni efectos de transición automáticamente. No aplicar normalización de volumen destructiva por defecto.

Invoca FFmpeg con lista de argumentos y `shell=False`; maneja nombres con espacios, comillas y caracteres Unicode. En manifiestos concat escapa rutas correctamente o usa nombres temporales controlados. Lee progreso del proceso, permite cancelar el montaje y conserva las generaciones originales. Escribe a temporal y publica el resultado únicamente al finalizar y verificarlo.

## 12. Importación de capítulo y ZIP

Admite creación manual y JSON estructurado. Markdown de guion se conserva como contexto; no pretendas inferir automáticamente todas las escenas de un documento libre sin revisión. Puede producirlas el asistente MCP como propuesta estructurada.

Ejemplo de intercambio:

```json
{
  "schema_version": "1.0",
  "project": {"name": "FRUTINOVELAS", "language": "es"},
  "chapter": {
    "title": "Capítulo 1",
    "script_file": "context/guion.md",
    "continuity_file": "context/continuidad.md"
  },
  "scenes": [
    {
      "external_key": "S01",
      "order": 1,
      "title": "Viaje por la costa",
      "duration_seconds": 3,
      "start_image": "assets/S01_inicio.png",
      "end_image": null,
      "prompt_file": "prompts/S01.txt",
      "workflow_profile_name": "H3 validado",
      "parameters": {"seed_mode": "random"}
    }
  ]
}
```

El ZIP exportado incluye `manifest.json`, contexto, imágenes, prompts y metadatos de versiones; incluir videos es opcional. Excluir tokens, URLs autenticadas y secretos. Permitir remapear el perfil al importar en otra máquina. Importar repetidamente no debe duplicar escenas sin una decisión explícita.

Validar schema, extensiones, límites y rutas. Impedir traversal, rutas absolutas, symlinks peligrosos y descompresión ilimitada. No ejecutar scripts incluidos en un ZIP. Mostrar resumen antes de incorporar el contenido.

## 13. Servidor MCP funcional

El servidor MCP es un adaptador del backend, no otro coordinador. Usa la misma lógica de negocio y estados que la UI, preferentemente mediante la API local. Evita que cada instancia stdio abra un worker nuevo.

Implementa stdio para Claude Desktop y Streamable HTTP para clientes remotos. Logs de stdio solo a stderr; stdout se reserva al protocolo. Versiona el SDK y prueba el descubrimiento y llamadas con un cliente real o MCP Inspector.

### Herramientas mínimas

| Herramienta | Propósito |
| --- | --- |
| `list_projects` | Identificar proyectos por UUID |
| `get_chapter` | Guion, continuidad, orden y revisión actuales |
| `list_scenes` | Resumen paginado y estados |
| `get_scene` | Prompt, referencias, parámetros y versiones |
| `get_scene_image` | Imagen de inicio/final accesible al modelo |
| `create_scenes` | Añadir escenas estructuradas con idempotencia |
| `update_scene` | Modificar datos mediante expected_revision |
| `save_scene_prompt` | Guardar prompt literal y crear revisión |
| `validate_scene` | Comprobar referencias, perfil y duración |
| `enqueue_generation` | Crear trabajo persistente y devolver job_id |
| `get_job_status` | Consultar estado real |
| `list_scene_versions` | Consultar resultados y notas |
| `get_version_frames` | Obtener fotogramas reales para revisión visual |
| `regenerate_scene` | Nueva versión, sin borrar las anteriores |
| `select_scene_version` | Cambiar elección explícita |
| `assemble_chapter` | Crear trabajo de montaje y devolver assembly_id |
| `get_assembly_status` | Consultar montaje y resultado |

Para imágenes remotas, devolver contenido de imagen MCP o URI soportada y recuperable; no limitarse a una ruta de Windows que el cliente en la nube no puede leer. Generar vistas reducidas configurables para no saturar contexto y conservar original intacto. Los fotogramas de videos se extraen del resultado real con FFmpeg; no afirmar revisión completa de movimiento, voz o sincronización por haber leído solo tres imágenes.

Las acciones largas retornan IDs inmediatamente y se consultan luego. No mantengas una llamada MCP abierta durante una inferencia de minutos. Describe las herramientas con esquemas claros, IDs estables, errores estructurados y anotaciones de lectura/escritura según el SDK. Aplica idempotencia y conflictos de revisión también a MCP.

**Quién redacta los prompts:** ChatGPT o Claude, como cliente, lee el guion y las imágenes mediante las herramientas y escribe el texto; después llama `save_scene_prompt`. El servidor no invoca mágicamente al modelo del chat ni obtiene acceso ilimitado a su suscripción. Un botón independiente de IA dentro del programa sería una integración adicional con un proveedor o un modelo local, fuera del alcance obligatorio inicial.

### Conectar a Claude Desktop

Entregar configuración stdio con rutas absolutas al Python del entorno y al módulo, más variables `FRUTINOVELAS_API_URL` y credencial local cuando aplique. Ejemplo de configuración de referencia, que el instalador debe adaptar:

```json
{
  "mcpServers": {
    "frutinovelas": {
      "command": "C:/ruta/frutinovelas-studio/.venv/Scripts/python.exe",
      "args": ["-m", "frutinovelas.mcp_server", "--transport", "stdio"],
      "env": {"FRUTINOVELAS_API_URL": "http://127.0.0.1:8765"}
    }
  }
}
```

Instala el paquete para que `-m` funcione desde cualquier directorio. No sobrescribas otras entradas de la configuración de Claude. Documenta comprobación de herramientas y reinicio. Empaquetado `.mcpb` puede añadirse después; no es requisito para probar stdio.

### Conectar a ChatGPT

El endpoint HTTP MCP necesita ser accesible mediante HTTPS o un mecanismo oficial como Secure MCP Tunnel. Verifica el flujo vigente de OpenAI antes de escribir el tutorial. La documentación consultada indica Plugins → añadir servidor MCP personalizado → endpoint o túnel → autenticación → crear e instalar plugin → activarlo en el chat. La cuenta y políticas pueden limitar el acceso.

Entrega la URL real una vez desplegada; nunca una URL ilustrativa presentada como operativa. El servidor local es privado por defecto. Si se publica el endpoint, implementa autenticación compatible con el cliente, TLS y permisos limitados al proyecto. No expongas ComfyUI directamente como sustituto del MCP.

## 14. API de la aplicación

Implementa rutas bajo `/api/v1` para proyectos, capítulos, assets, escenas, revisiones, perfiles, jobs, versiones, selecciones, montajes e importación/exportación. OpenAPI debe reflejar esquemas y errores reales.

Acciones sugeridas: `POST /scenes/{id}/generate`, `POST /scenes/{id}/regenerate`, `POST /jobs/{id}/cancel`, `PUT /scenes/{id}/selection`, `POST /chapters/{id}/assemblies`. La lectura de medios requiere IDs gestionados y soporta Range para el reproductor. Evita aceptar rutas arbitrarias de disco desde un cliente remoto.

Usa `expected_revision` y devuelve 409 ante conflictos, sin sobreescribir. Valida duraciones, recursos, perfil y relaciones de pertenencia. Acepta una clave de idempotencia en acciones que crean jobs y montajes. UI y MCP comparten las mismas reglas.

## 15. Configuración y mantenimiento

`.env.example` debe documentar sin secretos:

```text
FRUTINOVELAS_DATA_DIR=
FRUTINOVELAS_API_HOST=127.0.0.1
FRUTINOVELAS_API_PORT=8765
FRUTINOVELAS_API_URL=http://127.0.0.1:8765
FRUTINOVELAS_MCP_HOST=127.0.0.1
FRUTINOVELAS_MCP_PORT=8766
COMFYUI_BASE_URL=http://127.0.0.1:8188
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
```

Configurar conexión y perfiles desde la interfaz. En despliegues remotos, no mostrar credenciales en frontend, exportaciones o logs. Mantener CORS limitado, validar tamaños de upload y proteger acciones de modificación si se habilita acceso de red. El modo local se enlaza a loopback por defecto.

Añadir exportación de backup consistente de base de datos y assets, restauración documentada y botón de diagnóstico sin secretos. No borrar versiones ni caché automáticamente sin mostrar qué archivos se eliminarían. Registrar errores con escena/job/endpoint y mensajes entendibles: servidor desconectado, nodo ausente, formato de flujo incorrecto, falta de VRAM, salida no descargable o montaje fallido.

Colab: se configura su endpoint accesible, no se controla la libreta mediante clics ni se promete mantenerla viva. Si la sesión desaparece, conservar trabajos locales y reconciliar al recuperar conexión; no afirmar que una inferencia remota perdida puede reanudarse a mitad de denoising.

## 16. Reglas de prompts y continuidad de FRUTINOVELAS

Incluir una plantilla de instrucciones para el asistente MCP, editable por proyecto:

- Respuestas y UI en español. Prompts visuales en inglés; diálogos en español.
- Leer el guion actual y distinguir hechos confirmados de propuestas.
- Naturalidad de expresiones, miradas, manos y actuación. No acercamientos de cámara continuos por defecto.
- Duración individual por escena. Los tiempos internos son objetivos de generación, no garantías.
- Cámara fija cuando corresponda y cortes explícitos cuando estén solicitados.
- Asignar IDs solamente a hablantes; identidad y voz fuera de `<d>`, palabras dentro.
- Personajes silenciosos descritos mediante conducta visible, con boca cerrada cuando sea pertinente.
- Audio ambiente continuo; música desactivada por defecto.
- Respetar asientos, ropa, objetos, mano del cono y luz.
- Una imagen inicial individual por escena, no una cuadrícula usada involuntariamente como primer frame.
- H3 con una referencia: instrucción I2VA. Con inicio/final: instrucción FL2VA vinculada al último shot y duración efectiva. No añadir `<Picture 2>` cuando no existe.
- Campos de trabajo de la guía base: `integrated_multimodal_description`, `overall_soundscape`, `non_diegetic_music`.

El programa debe preservar los prompts literalmente y puede advertir sobre inconsistencias verificables, como final ausente, timestamps fuera de duración o referencia inexistente. No reescribir diálogos, insertar música o cambiar el canon silenciosamente.

Contexto visual inicial opcional del proyecto: Darío es una pera amarillo-verde con camisa clara y ocupa el asiento delantero del pasajero; Bruno es un aguacate con camisa oscura y conduce. Estas reglas son datos editables de continuidad, no lógica rígida del programa. Las imágenes y el guion actuales del usuario son la fuente para cada capítulo.

## 17. Pruebas y criterios de aceptación

Las pruebas deben verificar riesgos reales de cola, archivos, revisión e integración. Las simulaciones de servidor se usan para pruebas y deben estar rotuladas como tales; nunca hacerlas pasar por inferencia H3.

Obligatorias:

1. Crear/importar capítulo con escenas y referencias; reiniciar y recuperar todos los datos.
2. Materializar un grafo de fixture cambiando exclusivamente campos mapeados; conservar el original.
3. Validar perfiles I2VA/FL2VA, final opcional y cuantización de duración.
4. Doble clic y repetición MCP no producen despachos duplicados.
5. Timeout tras aceptación externa no provoca reenvío ciego.
6. Desconexión WebSocket recupera resultados por historial sin repetir.
7. Regenerar crea versión nueva y conserva selección y archivos anteriores.
8. Cancelar no elimina ni interrumpe trabajos ajenos.
9. Editar prompt durante generación no modifica su instantánea.
10. Extraer salidas de al menos un formato real del nodo de video y rechazar un resultado que solo contiene miniatura.
11. Montar dos clips pequeños con formatos distintos, uno sin audio; verificar video final, pista y duración dentro de la tolerancia de frames.
12. Validar ZIP con Unicode, espacios, rutas maliciosas y límites de expansión.
13. MCP descubre herramientas y permite leer escena, recibir imagen y guardar prompt con control de revisión.
14. Un recorrido Playwright crea escena, edita, encola con fixture, revisa versión y solicita montaje.
15. Compilación de frontend, análisis estático y pruebas en CI sin GPU ni credenciales reales.

Antes de declarar compatible el flujo real, hacer un smoke test autorizado con ComfyUI conectado: subir referencias, ejecutar una escena corta, descargar su MP4/audio y reproducirlo. Probar también regeneración con semilla nueva. Si no se dispone del servidor o modelos, entregar todo lo comprobable e identificar expresamente qué prueba real falta; no anunciar compatibilidad probada.

## 18. Fases de construcción y definición de terminado

1. **Base:** repositorio, configuración, SQLite/migraciones, CRUD, assets y UI.
2. **Flujos:** importación API, mapeo, validación y cliente ComfyUI real.
3. **Generación:** cola persistente, recuperación, descarga, versiones y reproductor.
4. **Montaje:** selección, trims, FFmpeg, exportación y ZIP.
5. **MCP:** stdio/HTTP, herramientas, imágenes, documentación ChatGPT/Claude.
6. **Entrega:** pruebas, CI, instalación Windows/Linux, diagnóstico y README.

Son fases para organizar el trabajo, no excusas para detenerse en la primera. El alcance obligatorio termina cuando los módulos operan y la documentación permite instalar, conectar un flujo y usarlo. Funciones opcionales posteriores: modelo local redactor, integración directa de API de IA, análisis automático de videos, música, varias GPUs, `.mcpb` y empaquetado de escritorio.

Entrega final del desarrollador:

- Código y repositorio preparados; enlace GitHub solo si existe y se subió.
- Instrucciones exactas probadas de instalación y arranque.
- Lockfiles, migraciones y archivos de ejemplo.
- Pruebas ejecutadas y sus resultados, con limitaciones reales.
- Flujo/perfil configurado cuando el usuario lo haya aportado.
- Conexión MCP demostrada o configuración lista con requisitos pendientes explícitos.
- Ningún secreto, modelo pesado ni video privado dentro de GitHub.

## 19. Fuentes oficiales y verificación

Las páginas cambian. El implementador debe verificar los contratos de la versión que va a instalar y registrar las versiones realmente probadas. Estas fuentes se consultaron al preparar el documento:

- ComfyUI, rutas HTTP y WebSocket: https://docs.comfy.org/development/comfyui-server/comms_routes
- ComfyUI, mensajes: https://docs.comfy.org/development/comfyui-server/comms_messages
- ComfyUI, ejemplo API/WebSocket: https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/websockets_api_example.py
- MiniMax H3, guía base de prompts: https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md
- MCP, arquitectura: https://modelcontextprotocol.io/docs/learn/architecture
- MCP, construcción de servidor: https://modelcontextprotocol.io/docs/develop/build-server
- SDK Python MCP: https://github.com/modelcontextprotocol/python-sdk
- OpenAI, conexión de plugin/MCP: https://developers.openai.com/plugins/deploy/connect-chatgpt
- Claude Desktop, servidores locales: https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop
- Claude, conectores remotos: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- FastAPI: https://fastapi.tiangolo.com/
- Vite: https://vite.dev/guide/
- SQLAlchemy/SQLite: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html
- FFmpeg, filtros: https://ffmpeg.org/ffmpeg-filters.html

**Instrucción final:** empieza a implementar el repositorio con esta especificación, valida cada fase y continúa hasta entregar el programa. Utiliza el flujo real del usuario para la integración; conserva los prompts, archivos y versiones; comunica los bloqueos concretos sin sustituir la funcionalidad por una demostración ficticia.
