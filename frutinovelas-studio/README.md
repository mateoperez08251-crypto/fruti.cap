# FRUTINOVELAS Studio

## Abrir el programa en Windows

Para repetir el arranque que ya funcionó en tu PC, consulta
[Inicio diario y recuperación de MCP en PowerShell](docs/INICIO_DIARIO_MCP_WINDOWS.md).
Incluye las tres ventanas, el perfil existente y el diagnóstico de errores sin guardar claves.

Desde esta carpeta, ejecuta `iniciar.cmd` (también admite doble clic). Instala las
dependencias necesarias, compila la interfaz e inicia la API. Necesita Python y
Node.js 24 LTS (también admite la rama 22 desde 22.13). El programa abre http://127.0.0.1:8765; mantén la terminal
abierta mientras lo utilizas. Los datos existentes se migran al arrancar.

`iniciar.cmd` comprueba actualizaciones antes de abrir. Solo actualiza `main` limpio
mediante fast-forward y conserva los cambios locales. `actualizar.cmd` permite comprobar
manualmente. Consulta [actualización segura](docs/ACTUALIZACIONES.md).

En la barra lateral, **Conexión MCP** abre **Conectar ChatGPT o Claude**. El panel
ofrece los comandos y la URL local para ChatGPT mediante su túnel, el JSON de
configuración para Claude Desktop y un diagnóstico del servidor MCP local.
Consulta [Conexión MCP desde Studio](docs/CONEXION_MCP.md) para elegir el cliente.
Los pasos completos de Windows y del túnel de ChatGPT están en
[CONEXION_MCP_Y_TUNNEL.txt](docs/CONEXION_MCP_Y_TUNNEL.txt).

Después de actualizar, ejecuta `iniciar.cmd` para recompilar la interfaz y reinicia
el MCP que estuviera abierto. El panel conserva la conexión y las credenciales
existentes; copiar una configuración o comprobar el servidor no inicia sesión en
ChatGPT o Claude ni demuestra que ese cliente ya esté conectado.

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
En **Audio y voces** de la escena selecciona las voces que hablan y escribe sus
diálogos nuevos en el prompt de animación. H3 Ref2VA usa las muestras como referencia
de timbre; no hace falta grabar cada frase. La escena conserva su selección y sus
imágenes de inicio y final. Admite hasta tres voces, con muestras de 2–15 segundos
cada una y 15 segundos en total. También se pueden usar audios de diálogo ya
grabados como alternativa explícita.

Consulta [Voces y audio por escena](docs/AUDIO_Y_VOCES.md) para uso, formatos,
compatibilidad y límites. Activa el complemento del kit con `--voces-personajes si`
(en Colab, `ACTIVAR_VOCES_PERSONAJES`); descarga Ref2VA INT8, 20,97 GB adicionales,
y reutiliza encoder y VAEs H3. Después vuelve a comprobar la conexión de Studio.
La muestra se reutiliza en cada generación, sin entrenamiento permanente. La calidad
de voz y sincronización requiere revisar un clip real.
La [explicación de autenticación](docs/AUTENTICACION.md) distingue la API local,
MCP y el gateway, así como la configuración declarada y los controles implementados.

## Iniciar el servidor en Colab

Abre la [libreta Colab actualizada](notebooks/FRUTINOVELAS_ComfyUI_Imagenes_H3_Colab.ipynb).
Incluye el kit autocontenido y trae `ACTIVAR_VOCES_PERSONAJES = True` para iniciar
con muestras reutilizables. La celda de planificación muestra el espacio de los
modelos antes de descargarlos; puedes desactivar voces si no las usarás en esa sesión.

1. Actualiza Studio y su MCP a la misma versión del repositorio que la libreta.
2. Selecciona GPU y ejecuta las celdas en orden. La exportación debe incluir
   `H3_VOZ_PERSONAJES.api.json` cuando las voces están activas.
3. Copia la URL y el token privado. En Studio abre **Conexión ComfyUI** y pulsa
   **Guardar y comprobar** con esos datos.
4. Reinicia el MCP si estaba abierto para cargar las herramientas y guías
   actualizadas. El catálogo de estilos se consulta desde el MCP local de Studio;
   Colab ejecuta la generación audiovisual.

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

### Estilos visuales para la IA

Lee [ESTILOS_VISUALES.md](docs/ESTILOS_VISUALES.md) antes de redactar prompts de
imagen o animación. El catálogo incluye **Angulado y Geométrico (Mignola & Y2K)**,
con identificador `angulado_geometrico_y2k`: líneas rectas, siluetas afiladas,
proporciones geométricas, sombras duras y bloques de color de alto contraste.
Incluye las referencias que propusiste —Atlantis, El planeta del tesoro y Kim
Possible— y ejemplos de instrucciones visuales para los prompts.

Por MCP, `get_directing_guidance` incorpora esta guía automáticamente para las
tareas `image`, `animation` y `review`; también se puede leer directamente en
`frutinovelas://guides/visual-styles`. Para aplicarlo, indica **«Usa el estilo
angulado y geométrico»**: se activa **solo por petición expresa**, nunca por leer
el catálogo. Al solicitarlo, la IA consulta también referencias en internet,
prioriza fuentes originales y cita lo utilizado fuera del prompt. La selección
orienta el nuevo prompt y conserva la identidad y continuidad de sus personajes.

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

### MCP público temporal para probar con otras cuentas

Abre **Conexión MCP → Prueba pública HTTPS** o consulta
[la guía de prueba pública](docs/MCP_PUBLICO_PRUEBA.md).
Desde Windows, con Studio iniciado, ejecuta `publicar_mcp_prueba.cmd`. La
consola ofrece una URL HTTPS temporal para conectarla como servidor MCP remoto;
no utiliza los permisos del túnel privado de OpenAI. La prueba es deliberadamente
**sin autenticación** y expone herramientas de lectura, escritura y generación,
por lo que solo se debe realizar con proyectos descartables y cerrar con Ctrl+C.

### Crear capítulos completos desde ChatGPT por MCP

El MCP incorpora `create_studio_chapter_plan`: crea un capítulo nuevo con guion,
continuidad y escenas preparadas (prompt Qwen, prompt H3, reparto y duración de
4–15 segundos por escena), utilizando IDs reales de la biblioteca y aprobación
manual. No genera imágenes ni videos. Valida antes de escribir y permite repetir
una llamada interrumpida sin duplicar las escenas, pero nunca sobrescribe un
capítulo o escena que se haya editado en Studio. Reinicia el MCP después de
actualizar para descubrir la nueva herramienta.

El ejemplo de producción está en
[`examples/chapters/dario_capitulo_2.json`](examples/chapters/dario_capitulo_2.json).
No se importa de forma automática: hay que llamar a la herramienta MCP desde
ChatGPT con el proyecto correcto y este plan. No afecta al capítulo 1.


## Control ampliado desde MCP

El MCP publica funciones tipadas equivalentes a los controles de Studio:
consultar ComfyUI y el estado del servidor; crear y editar proyectos, capítulos,
escenas y personajes por sus IDs reales; revisar versiones, ordenar y duplicar
escenas; iniciar videos H3, consultar sus trabajos y resultados. En particular:

- \`request_chapter_images\`: envía todas las imágenes Qwen que falten, evitando
  duplicados si ya hay un resultado o trabajo activo.
- \`generate_full_chapter\`: ejecuta el mismo trabajo que el botón
  **Generar capítulo completo** (Qwen → aprobación automática → H3 → montaje MP4).
  Requiere confirmar \`automatic_approval=true\` para esa ejecución.
- \`request_scene_video\`: equivale al botón **Generar esta escena**.
- Borrados exigen \`confirmed=true\`; siguen aplicando las revisiones de Studio.

No se publica shell, acceso arbitrario a archivos ni los tokens del gateway. Las
imágenes y audios nuevos se suben desde Studio; las herramientas MCP reutilizan
sus IDs. **La URL pública de prueba sin autenticación da acceso a terceros que
conozcan el enlace y permite modificar escenas y usar la GPU.** Usar solamente
con proyectos descartables y cerrar el túnel al terminar.
Después de actualizar, reinicia MCP y renueva la conexión del plugin de ChatGPT.
