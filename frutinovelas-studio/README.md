# FRUTINOVELAS Studio

## Abrir el programa en Windows

Desde esta carpeta, ejecuta `iniciar.cmd` (también admite doble clic). Instala las
dependencias necesarias, compila la interfaz e inicia la API. Necesita Python y
Node.js 24 LTS (también admite la rama 22 desde 22.13). El programa abre http://127.0.0.1:8765; mantén la terminal
abierta mientras lo utilizas. Los datos existentes se migran al arrancar.

`iniciar.cmd` comprueba actualizaciones antes de abrir. Solo actualiza `main` limpio
mediante fast-forward y conserva los cambios locales. `actualizar.cmd` permite comprobar
manualmente. Consulta [actualización segura](docs/ACTUALIZACIONES.md).

Para los comandos de CMD, el MCP local y el túnel de ChatGPT, sigue
[CONEXION_MCP_Y_TUNNEL.txt](docs/CONEXION_MCP_Y_TUNNEL.txt).

Alternativa manual:

```powershell
py -3.12 -m uv sync --frozen
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
py -3.12 -m uv run --frozen frutinovelas-api
```

## Generar solo una escena con RunPod

1. Mantén ComfyUI y el gateway de RunPod activos. Copia la URL de `fruti status`
   y el token completo de `fruti token --mostrar`.
2. En la aplicación, abre **Conexión ComfyUI**, pega URL y token, y pulsa
   **Guardar y comprobar**. Se exige el flujo H3 API del kit y se verifica su SHA-256.
3. Abre tu escena. Selecciona la imagen inicial y, si corresponde, la final.
   Escribe el prompt y una duración entre **4 y 15 segundos**. Pulsa **Guardar**.
4. Pulsa **Generar esta escena**. El progreso indica preparación, cola, inferencia
   y descarga reales, sin simular porcentajes de sampling.
5. Al terminar aparece el reproductor y **Descargar video**. Puedes volver a generar;
   cada versión conserva su revisión, referencias, duración y semilla originales.

El perfil conserva los modelos del servidor y usa 576×1024 (9:16), 20 pasos y 24 fps.
Las referencias se preparan en RGB y se ajustan al centro al canvas; los originales
permanecen intactos. H3 cuantiza la duración a `17k+5` frames: 5 s solicitados producen
124 frames, aproximadamente 5,17 s. La interfaz muestra ambas duraciones.

La URL puede cambiar si reemplazas el pod. Vuelve a comprobar la conexión. Los trabajos
ya enviados conservan la conexión e identidad originales y nunca se reasignan a otro
runtime silenciosamente. Ante timeout después del envío, se comprueba cola e historial
sin reenviar la solicitud. Si no se puede resolver, revisa la cola remota antes de
**Marcar como interrumpida** y crear otra versión. Ese botón no interrumpe trabajos ajenos.

La cola y los resultados se guardan en el directorio de datos del usuario, fuera del
repositorio. El token se cifra con una clave local (`comfy_credentials.key`); incluye
todo ese directorio si haces una copia de seguridad. No subas la clave ni los datos a Git.

Antes de aplicar migraciones pendientes a una base SQLite existente, Studio crea una
copia coherente (incluido WAL) en `backups/`, junto a la base. La migración `0004`
recupera instalaciones antiguas cuya revisión de imágenes quedó incompleta, incluido
el error `no such column: generation_jobs.kind`. Añade solo los objetos que falten y
conserva personajes, guiones, referencias, versiones y credenciales. También puede
retomar una `0003` parcialmente aplicada. No borres la base para resolver este error:
actualiza el código y vuelve a iniciar Studio con las otras copias cerradas.
Al terminar las migraciones se comprueban las columnas reales antes de arrancar la
cola; si el esquema sigue incompleto, el inicio se detiene con un mensaje concreto.


La biblioteca de personajes, el selector por escena y la generación de imágenes Qwen
con referencias ya están integrados. Cada escena guarda por separado el prompt de
imagen y el de animación. La aprobación es manual de forma predeterminada; puedes
activar el modo automático por escena o para un capítulo completo.
Consulta [Personajes y escenas](docs/PERSONAJES_Y_ESCENAS.md) para interfaz, cola,
MCP, límites y alcance probado. El capítulo automático ejecuta los prompts guardados
en serie y une los clips con FFmpeg; no evalúa su calidad. ChatGPT puede estimar y
guardar los segundos según el prompt y las imágenes de inicio/final; el editor
conserva el ajuste manual. Ver [guía de escenas y duración](docs/GUIA_ESCENAS_Y_DURACION.md).

Los listados leen solo la revisión actual de cada escena; el historial completo se
consulta al abrirlo. El progreso lee resúmenes sin cargar los flujos guardados.
Se muestran inicialmente tres versiones y las anteriores se abren bajo demanda;
los videos se descargan para reproducirlos al pulsar play, sin precargarlos al abrir
el editor. El estado se consulta cada 30 segundos en reposo y el progreso cada 2,5
segundos con trabajo activo (15 segundos si la recepción es incierta). El sondeo
periódico se pausa con la pestaña oculta y se actualiza al volver. Estas consultas
no inician inferencias: la GPU se usa al solicitar una generación.

## Voces y audios de las escenas

La biblioteca permite guardar una descripción y una muestra de voz por personaje.
En **Audio y voces** de la escena puedes subir el diálogo, asignar quién habla y
elegir el segundo de inicio. Los audios se guardan con la revisión y entran como
guía en el flujo H3 actual mediante `MiniMaxH3AddGuide`.

Consulta [Voces y audio por escena](docs/AUDIO_Y_VOCES.md) para uso, formatos,
compatibilidad y límites. La muestra del personaje no genera frases nuevas
automáticamente; la calidad de voz y sincronización requiere revisar un clip real.
La [explicación de autenticación](docs/AUTENTICACION.md) distingue la API local,
MCP y el gateway, así como la configuración declarada y los controles implementados.

## Comprobar los cambios

```powershell
py -3.12 -m uv sync --extra dev --frozen
py -3.12 -m uv run --frozen pytest
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
```

Las pruebas cubren concurrencia de guardados, conservación de borradores, actualización
segura, gateway y conexión MCP HTTP. Las de generación simulan el servidor GPU: comprueban
autenticación, migración, versiones, descarga, duplicados y recuperación.
No miden calidad ni rendimiento GPU. GitHub Actions ejecuta esta verificación en cada PR
y al publicar en `main` o ramas `codex/`; no inicia modelos ni actualiza tu PC.


## Dirección de prompts y skills

El editor incluye **Revisar prompt H3**: estructura, referencias y duración, sin guardar ni generar.
Hay cuatro skills para asistentes en `../.agents/skills/`, un compilador validable para H3 y Qwen,
cinco ejemplos y una guía de continuidad basada en el chat compartido. Las reglas sirven para
cualquier escena; el preset `frutinovelas` añade tus preferencias y `general` permite otros sujetos
y estilos. La historia de la heladería se consulta solo cuando corresponde.

```powershell
py -3 -m uv run frutinovelas-prompts h3 examples/prompts/bruno_horn_i2va.json
py -3 -m uv run frutinovelas-prompts image examples/prompts/qwen_edit_cocardo.json
```

El comando `frutinovelas-mcp` sirve cuatro herramientas de guías y doce de preparación y ejecución de escenas **por stdio o HTTP local**, recursos y el prompt
`direct_scene`. `get_directing_guidance` permite al asistente leer las skills y preferencias antes
de redactar; las otras tres herramientas preparan y revisan prompts. No conecta automáticamente
ChatGPT web: la conexión requiere configurar su túnel. Las herramientas Studio leen y guardan ambos prompts y pueden encolar Qwen bajo petición. La animación y el montaje automáticos requieren activar esa opción expresamente. Las guías no entrenan al modelo ni crean
memoria automática entre chats.

```cmd
py -3.12 -m uv run --frozen frutinovelas-mcp --transport streamable-http --host 127.0.0.1 --port 8766
```

El endpoint es `http://127.0.0.1:8766/mcp`. Funciona aunque ComfyUI esté apagado;
preparar prompts y ejecutar una generación son capacidades distintas. Las herramientas Studio requieren la API local abierta; generar requiere también Qwen activo en ComfyUI.
Ver [uso completo](docs/PROMPT_STUDIO.md), [instrucciones para ChatGPT](docs/CHATGPT_DIRECTOR.md),
[compatibilidad](docs/MODEL_COMPATIBILITY.md) y [fuentes consultadas](docs/PROMPT_RESEARCH.md).
