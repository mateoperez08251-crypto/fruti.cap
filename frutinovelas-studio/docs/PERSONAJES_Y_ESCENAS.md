# Personajes, imágenes y prompts por escena

## Recorrido en la interfaz

1. Abre un proyecto y despliega **Biblioteca de personajes**. Sube una imagen y
   guarda su nombre (por ejemplo, Darío), descripción y referencia.
2. En el capítulo, abre una escena y despliega **1 · Personajes y prompt para crear
   la imagen**. Marca los personajes en orden. Este adaptador admite hasta dos
   referencias por imagen; no descarta personajes silenciosamente si se supera el límite.
3. Escribe o pide a ChatGPT el **prompt de imagen · Qwen**. Guarda la escena.
4. Pulsa **Generar imagen con Qwen**. Con personajes seleccionados se exige
   `QWEN_EDIT_2511.api.json`; sin personajes se utiliza `QWEN_2512_T2I.api.json`.
   El servidor debe publicar el flujo y su hash. La URL y el token existentes no cambian.
5. Revisa el resultado. **Aprobar y usar de inicio/final** crea una revisión nueva
   de la escena. Este es el modo manual predeterminado.
6. Con el guion, la continuidad y la imagen aprobada, prepara el campo separado
   **2 · Prompt de animación · H3**. Guarda y utiliza el botón de video existente.

Los prompts se conservan literalmente. El guion y la continuidad son contexto;
no se sustituyen por el prompt. El programa no llama a un chatbot ni entrena un
modelo por abrir estos paneles. ChatGPT redacta usando las herramientas MCP;
también se puede escribir todo manualmente.

Las revisiones congelan el orden, nombre, descripción, asset ID y hash de cada
referencia. Editar una imagen en la biblioteca no modifica escenas ni trabajos
anteriores. Para utilizar una referencia nueva en una escena ya preparada,
quita ese personaje, guarda, vuelve a seleccionarlo y guarda la nueva revisión.

## Cola y flujo Qwen

Imágenes y videos usan el mismo worker, bloqueo de proceso y cola persistida.
Se procesa un trabajo cada vez. No se descargan nuevos modelos ni se cambian
LoRAs, pasos, CFG o precisión. Se verifica el SHA-256 antes de guardar el grafo
para un trabajo. Los IDs de los subgrafos exportados no están codificados a mano:
se localiza el único KSampler conectado a SaveImage y su encoder positivo.

Para componer una escena nueva se prepara un latent vacío de 576×1024. Las
referencias se convierten en copias RGB conservando su proporción y con lado
máximo de 1024; se conectan como image1/image2 a los encoders Qwen Edit. Se
eliminan imágenes de ejemplo y entradas image3 no utilizadas. El prompt enviado
incluye una correspondencia explícita entre cada imagen y su personaje; el
texto guardado permanece intacto. Esto ayuda a conservar identidad, pero no
asegura un resultado idéntico sin revisión visual.

El adaptador conserva solo los nodos que alimentan SaveImage. Se basa en la
[plantilla oficial fijada en el kit](https://github.com/Comfy-Org/workflow_templates/blob/3e89967349dd95fa68ce3b36966f41d642af8ea7/templates/image_qwen_image_edit_2511.json)
y rechaza grafos ambiguos o incompatibles antes del envío. Las pruebas usan un
gateway simulado; la calidad y compatibilidad final deben comprobarse con el
flujo exportado de tu pod. No se ha ejecutado inferencia GPU para esta entrega.

Un timeout tras el POST no lo repite. El worker consulta cola e historial para
recuperar el resultado. Las versiones y las imágenes originales se conservan.
La API de progreso lee resúmenes sin cargar workflows o credenciales completos;
la interfaz solo consulta imágenes cuando se abre su panel y pausa el sondeo
con la pestaña oculta. No hay inferencia al seleccionar personajes o guardar.

## MCP del repositorio

Las cuatro herramientas de guías/compilación siguen disponibles. Se añaden:

| Herramienta | Efecto |
|---|---|
| `list_studio_projects` | Obtener IDs de proyectos |
| `list_studio_chapters` | Obtener resúmenes e IDs de capítulos |
| `list_studio_scenes` | Leer escenas y su preparación guardada |
| `list_project_characters` | Leer referencias reales de la biblioteca |
| `inspect_studio_image` | Ver una miniatura y sus metadatos por asset ID |
| `get_scene_preparation` | Leer escena y, opcionalmente, guion y continuidad |
| `save_scene_preparation` | Guardar reparto, prompts, duración y revisión manual/automática |
| `request_scene_image` | Encolar Qwen solo bajo petición explícita de generar |
| `list_scene_images` | Consultar estados y resultados, sin generar de nuevo |
| `approve_scene_image` | Asignar un resultado tras aprobación explícita del usuario |
| `request_chapter_render` | Encolar imágenes, videos y montaje con aprobación automática expresa |
| `list_chapter_renders` | Consultar estados y descargar el capítulo final |

Las herramientas Studio llaman a la API local ya abierta, usan su token local
si está configurado y no alteran credenciales del gateway ni del túnel. Reinicia
el MCP actualizado para que el cliente descubra las herramientas nuevas. Si el
MCP conectado es una implementación adicional ajena al módulo de este repo,
estas herramientas deben registrarse allí o conectar este endpoint por separado;
un `git pull` no modifica un servidor externo ni su configuración.

La primera vez, lee `get_directing_guidance`, el guion y las referencias. En
escenas siguientes del mismo capítulo puedes usar
`get_scene_preparation(include_chapter_context=false)` para no repetir todo el
texto. Escribe y guarda primero el prompt de imagen; encola cada escena con un
UUID distinto y reutiliza ese UUID al reintentar. La cola continúa en el programa
sin mantener una llamada MCP abierta durante la inferencia.

Después de la revisión del usuario, asigna la imagen, inspecciónala y redacta el
prompt H3 según el guion y su composición real. No aprobar resultados por cuenta
del asistente salvo que el usuario haya activado el modo automático.

## Duración según la escena

ChatGPT puede inspeccionar las imágenes de inicio y final y estimar los segundos
necesarios para las acciones, diálogo, pausas, reacciones y cámaras del prompt.
Guarda esa estimación con `save_scene_preparation(duration_seconds=...)`; no se
requiere que el usuario escriba los segundos. El editor permite ajustarlos a mano.
Dos imágenes son los extremos de una escena FL2VA; no implican dividirla. El perfil
actual genera 4–15 s. El ajuste de fotogramas puede variar ligeramente la duración
efectiva. Consultar [guía de escenas y duración](GUIA_ESCENAS_Y_DURACION.md), publicada
también por MCP como `scene-timing` e incluida en las guías de animación.

## Automatización opcional

En cada escena, **Revisión de imágenes** inicia en **Manual**. Si eliges y guardas
**Automática**, el resultado Qwen se asigna como imagen inicial sin esperar una
revisión visual. El botón **Generar imagen y después animar** añade también H3 con
el prompt y los segundos guardados. Conserva el final que hayas seleccionado.

Para un capítulo, despliega **Capítulo automático · imágenes, animación y montaje**.
Primero guarda ambas clases de prompts y las duraciones de todas sus escenas.
Marca la casilla de aprobación automática para **ese proceso** y pulsa **Generar
capítulo completo**. La casilla inicia desactivada; no cambia la preferencia de
revisión de las escenas. Se admite hasta 60 escenas por proceso.

El worker genera un inicio Qwen y anima su escena antes de continuar con la
siguiente; respeta los finales ya seleccionados. No genera un final distinto a
partir del mismo prompt de inicio. Para crear un final, prepara su prompt Qwen,
genera y aprueba ese resultado como final antes de iniciar el proceso automático.
Al terminar une los clips en orden mediante FFmpeg + ffprobe (deben estar instalados
y disponibles en el PC). Normaliza video a 576×1024/24 fps y audio a estéreo 48 kHz;
si falta audio en un clip añade silencio de esa duración. Los originales se conservan.
El montaje usa cortes directos: no reescribe diálogo ni crea sonido continuo, y no
promete transiciones invisibles ni sincronía perfecta.

Las solicitudes capturan revisiones y usan UUIDs persistentes para reintentar sin
repetir la generación. La aprobación y su marcador se guardan juntos para retomar
tras un cierre. Cambiar una escena, guion, continuidad o servidor detiene la
continuación afectada; los archivos generados se conservan para revisión. Un POST
incierto mantiene el trabajo reservado hasta reconciliar cola e historial.

La automatización usa textos ya guardados, no incorpora una llamada API de pago a
ChatGPT ni escribe prompts por sí misma. ChatGPT debe preparar el plan por MCP
antes de ejecutar la cola; el modo manual permite revisar las imágenes antes de
preparar la animación. La aprobación automática comprueba disponibilidad técnica,
no calidad visual. Las pruebas incluyen gateway simulado y un montaje FFmpeg real
con clips sintéticos; no se ha ejecutado GPU ni evaluado el video de tu instalación.

## Crear capítulos y escenas íntegros mediante MCP

Para que ChatGPT no obligue al usuario a crear escenas manualmente, el MCP publica
`create_studio_chapter_plan(plan)`: acepta `project_id`, `plan_id` estable, título,
guion y continuidad del capítulo, y escenas con título, descripción, prompt de
imagen, prompt de animación, segundos, hasta dos IDs de personajes para Qwen y
hasta tres voces si sus muestras suman como máximo 15 s. No inicia GPU y conserva
la aprobación manual. Comprueba personajes reales, límites y contenido antes de
escribir; si hay un capítulo del mismo título con contenido diferente, no lo pisa.
En reintentos, solo reutiliza un prefijo de escenas idénticas.

Tras un `git pull` hay que reiniciar Studio y el proceso MCP para que ChatGPT vea
la nueva herramienta. El ejemplo de Capítulo 2 de detectives está en
`examples/chapters/dario_capitulo_2.json` como propuesta creativa editable,
no como hechos confirmados del Capítulo 1.

## Evitar duplicados: referencias de una sola pose (preparación Qwen)

**Problema confirmado:** las fichas visuales de Darío, Bruno y Mateo muestran
múltiples vistas y expresiones del mismo personaje. Enviar la ficha completa
como `image1/image2` a Qwen Edit puede producir figuras duplicadas: el modelo
confunde vistas del diseño con más participantes de la escena. No era solamente
un problema de escribir «no clones» en el prompt.

Para nuevas generaciones, Studio reconoce las fichas de los tres personajes
mediante su SHA-256 congelado e **isola la vista frontal de una sola figura**
antes de cargar `image1/image2`. Para fichas multivista nuevas con formatos
convencionales utiliza una heurística geométrica y recomienda revisarla; para
fotos individuales mantiene el original. La imagen de la biblioteca, las
revisiones anteriores y los resultados viejos NO se reescriben.

El grafo positivo enviado a Qwen incluye además una restricción explícita
de reparto: número exacto de sujetos, una aparición de cada personaje,
correspondencia de `image1/image2` con sus nombres y rasgos, y ausencia
de extras o clones en el fondo. El **prompt guardado permanece literal**;
solo la copia del trabajo recibe las reglas. Las recetas usadas se conservan
en el snapshot de cada trabajo nuevo (`cast[].reference_preparation`).

**Límites:** se reduce la causa de duplicación pero Qwen no garantiza identidad
ni número perfecto de personajes. Revisa las miniaturas antes de aprobar. Los
resultados ya generados no se convierten retrospectivamente; si fallaron,
realiza una nueva generación con ID de solicitud distinto tras actualizar,
sin borrar el original.
