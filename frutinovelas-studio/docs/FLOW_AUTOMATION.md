# Flow Automation: instalación, alcance y prueba pendiente

Fecha: 20 de octubre de 2026. Base inspeccionada: `3a61c3f8cc1a3bfca8ecd9c71bbf7415f89ceaa7`.

**Estado: integración en revisión. No se ha ejecutado una generación real en Userlfex/UserFLEX.**
El entorno de desarrollo no tiene Windows, el programa instalado, su sesión ni su contrato.
No se incluye un perfil que invente sus controles. La aceptación de extremo a extremo
queda pendiente del diagnóstico de la instalación autorizada del usuario.

## Qué se puede ejecutar

- **Modo asistido:** seleccionar un capítulo/escenas, encolar imágenes o videos, consultar
  los prompts guardados, generar en la ventana de Flow e importar cada descarga. Las imágenes
  se decodifican con Pillow. Los MP4 se inspeccionan con FFprobe y se decodifican con FFmpeg.
  Un archivo inválido no completa el trabajo. Aprobar una imagen la asigna al inicio de
  su escena mediante una nueva revisión. Los originales, solicitudes y versiones se conservan.
- **Agente Windows UIA:** proceso independiente que puede ejecutar operaciones reales de
  accesibilidad (`invoke`, `select`, `set_edit_text`) únicamente dentro del ejecutable
  configurado y sus procesos hijos. Requiere un perfil local construido con controles
  observados. Comprueba identidad del proceso/ventana, referencias, perfil y ejecutable;
  guarda el envío en su diario antes de invocar Generar. No utiliza clics por coordenadas.
- **MCP:** herramientas tipadas para conexión, detección, consulta, lotes, reintentos,
  importación de imágenes registradas y revisión. No ofrece shell, clics genéricos,
  selección de ejecutables, lectura arbitraria de archivos ni extracción de sesiones.
- **Motores locales:** Qwen, H3, ComfyUI, personajes, audio y montaje mantienen sus rutas,
  workflows y manifiestos. Flow tiene una cola separada; no usa la reserva de ComfyUI.

Los MP4 de Flow se consultan y descargan desde su escena en **Flow Automation**. No se
introducen automáticamente en el montaje H3 ni sustituyen el audio de videos narrados.
El original conserva su pista de audio; `use_provider_audio_in_montage` permanece en `false`.
Esta entrega no añade un montador de capítulos de clips Flow: el objetivo implementado
es generación/importación por escena y su biblioteca de versiones.

## Investigación previa y límites de la evidencia

| Alternativa | Evidencia / decisión |
|---|---|
| API oficial de Userlfex | No se localizó documentación técnica verificable para ese nombre. No se implementó ningún endpoint supuesto. |
| Identidad del producto | Apareció un producto llamado UserFLEX, anunciado por su vendedor como aplicación instalada para acceder a herramientas. La coincidencia con «Userlfex» necesita confirmación. El anuncio no acredita API, motor de escritorio, permisos de automatización ni cuotas ilimitadas. |
| Electron / Chromium / WebView2 | Desconocido en la instalación del usuario. El diagnóstico busca indicios locales: `resources/app.asar`, procesos hijos WebView2 y frameworks de controles accesibles. Los indicios no prueban CDP. |
| Playwright / CDP | Playwright necesita un navegador/control de depuración al que realmente se pueda conectar. No se habilita depuración ni se abren puertos del programa para forzar acceso a una sesión. |
| Windows UI Automation | Adaptador implementado sobre controles accesibles de una ventana autorizada. Si el programa no los expone, el perfil no se valida. |
| Visión / coordenadas | No se incorpora un controlador visual especulativo. El modo asistido permite trabajar con descargas reales mientras se resuelve la compatibilidad. |

Fuentes consultadas (no sustituyen los términos del proveedor):

- [Anuncio del vendedor UserFLEX](https://forobeta.com/temas/prueba-por-1-reviews-positivas-chatgpt-envato-hailuo-midjourney-canva-capcut-freepik-riffusion-ideogram-c-monetizacion.1058181/).
  El sitio `https://userflex.pro` no pudo consultarse con la herramienta de investigación.
- [Microsoft: UI Automation](https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/ui-automation-overview).
- [pywinauto: elegir e inspeccionar el backend](https://pywinauto.readthedocs.io/en/latest/getting_started.html).
- [pywinauto: conexión a aplicaciones y controles](https://pywinauto.readthedocs.io/en/latest/HowTo.html).
- [Playwright: BrowserType y conexión a navegadores](https://playwright.dev/python/docs/api/class-browsertype).
- [Google Flow: crear videos](https://support.google.com/flow/answer/16353334?hl=en).
- [Google Flow: modelos y funciones](https://support.google.com/flow/answer/16352836?hl=en).

Las funciones descritas por Google no prueban su disponibilidad en la cuenta compartida
o aplicación concreta. No se programaron duraciones, modelos o límites comerciales
supuestos. Las capacidades del agente proceden del perfil local; validar controles
principales no equivale a verificar calidad generativa ni toda la secuencia.

## Arquitectura

`MCP autenticado / interfaz → API Studio → FlowWorker → agente localhost → UIA → ventana autorizada`.

La migración aditiva `0008` crea `flow_batches`, `flow_jobs` y `flow_connections`.
El mecanismo existente de migración hace una copia SQLite previa. Los prompts se
congelan en cada solicitud; el texto editado para Flow no modifica el original H3.
Los lotes validan todas las escenas antes de insertarlas. Cada hijo tiene un UUID
determinista derivado de la solicitud, escena y tipo de medio.

El proceso de Studio usa `flow/studio.lock` para serializar mutaciones entre procesos.
El agente tiene otro diario SQLite con `synchronous=FULL`, identidad persistente y
una única reserva global de escritorio. Cada lado conserva sus registros tras reiniciar.
El adaptador separa el contrato de trabajo/descarga de las acciones UIA; para otro
proveedor debe implementarse su transporte y capacidades sin reutilizar controles
de Userflex ni modificar los workflows Qwen/H3.

## Uso inmediato: modo asistido

1. Inicia Studio con `iniciar.cmd` y entra en **Flow Automation** desde la barra lateral
   o **Generar con Flow** desde un capítulo.
2. Elige **Asistido** y confirma que tienes autorización para usarlo con tu sesión.
3. Selecciona proyecto, capítulo y escenas. Revisa los prompts. Para video, adapta
   la dirección H3 a texto natural aceptado por Flow; conserva diálogos y referencias.
4. Selecciona imágenes, videos o imágenes seguidas de videos. La aprobación automática
   está desactivada de forma predeterminada. Pulsa **Encolar**.
5. En **Ver prompt y referencias**, copia el prompt del trabajo que espera descarga.
   Genera en tu sesión de Flow usando las referencias, formato y duración compatibles.
6. Descarga el resultado e impórtalo en **ese trabajo**. Seleccionar el archivo declara
   que corresponde a la escena y solicitud mostradas; el software valida el archivo,
   no puede demostrar por sus píxeles que el proveedor lo generó con ese prompt.
7. Aprueba o rechaza la imagen. La aprobación asigna el fotograma inicial y desbloquea
   el video previamente solicitado, si la revisión no cambió. Si cambió, solicita una
   nueva animación; la anterior no se ejecuta silenciosamente con otro prompt.

No reutilices una descarga ajena para cerrar un envío incierto. Si hay un resultado
real, impórtalo; si aún se está generando, conserva la reserva.

## Instalar y diagnosticar el agente en Windows

Requisitos: Python 3.12, el entorno de Studio, FFmpeg/FFprobe en PATH para MP4,
Windows con sesión gráfica abierta y permisos normales del mismo usuario que abre
Userlfex. No ejecutes el agente como administrador ni como servicio de sesión 0.

Desde PowerShell, en `frutinovelas-studio`:

```powershell
py -3.12 -m uv sync --extra dev --extra flow-agent --frozen
py -3.12 -m uv run --extra flow-agent --frozen frutinovelas-flow-agent inspect --executable 'C:\RUTA_REAL\Userflex.exe'
```

Sustituye la ruta por la del ejecutable real; no es una ruta detectada. El diagnóstico
solo examina ese ejecutable y sus procesos hijos. No lee cookies, tokens, contraseñas,
valores de campos editables ni líneas de comando. Los títulos de ventana y botones
pueden contener nombres de proyectos: revisa el informe antes de compartirlo.

Para construir un perfil con el esquema exacto:

```powershell
py -3.12 -m uv run --extra flow-agent --frozen frutinovelas-flow-agent schema
```

Guarda el perfil fuera de Git en `<directorio de datos de Studio>\flow\profile.json`.
El directorio de datos se muestra al iniciar Studio. Tanto Studio como el agente deben
usar el mismo `FRUTINOVELAS_DATA_DIR` y cuenta de Windows. No copies credenciales al repositorio.

Campos del perfil:

| Campo | Cómo obtenerlo |
|---|---|
| `executable`, `window_title_contains` | Ruta real y fragmento inequívoco del título de una sola ventana autorizada. |
| `automation_authorized` | Actívalo solo después de comprobar que tu autorización y condiciones permiten estas acciones. |
| `flow_marker`, `authenticated_marker`, `ready_marker` | Selectores de controles reales que prueben sección, sesión y disponibilidad. No deducir sesión solo del título. |
| `blockers` | Selectores de verificaciones humanas, cuota agotada, acceso rechazado u otros estados observados que exijan pausa. |
| `modes.image`, `modes.video` | Solo los modos que se hayan observado. Omite los que no puedas comprobar. |
| `aspect_ratios`, `durations`, `reference_count` | Capacidades del modo real y cantidad exacta de referencias que cargarán sus acciones. No heredar límites H3. |
| `prepare` | Acciones para seleccionar modo/opciones, adjuntar referencias y escribir el prompt. No incluir Generar. |
| `submit`, `busy`, `completed` | Controles inequívocos de envío, ejecución y un resultado nuevo. Un resultado anterior visible bloquea la correlación. |
| `save` | Acciones de descarga/Guardar como. Deben escribir `output_path` en el diálogo del mismo proceso autorizado. |

Cada selector exige `control_type` y al menos `auto_id` o `title` exacto. Un diálogo
propio del programa puede especificar `window_title`. No se admite regex, índice de
coincidencia, coordenadas, shell, código JavaScript ni lectura de otra aplicación.
Cada acción admite `invoke`, `select` o `set_text`; los valores provienen de `literal`,
`prompt`, `reference_0`…`reference_2`, `aspect_ratio`, `duration_seconds` u `output_path`.
No se omiten referencias cuando un modo no las admite: se rechaza esa solicitud.

Antes de habilitar el controlador:

```powershell
py -3.12 -m uv run --extra flow-agent --frozen frutinovelas-flow-agent verify-profile
.\iniciar_flow_agente.cmd
```

`verify-profile` comprueba los controles principales y vincula la autorización al hash
del perfil y del ejecutable. Cambiar uno exige verificar nuevamente. No pulsa Generar
ni certifica el recorrido completo. Un perfil puede necesitar ajustes de controles
que solo aparecen después de seleccionar un modo o abrir un diálogo.

El agente escucha únicamente en `127.0.0.1:8767`; el puerto se puede cambiar mediante
`FRUTINOVELAS_FLOW_AGENT_PORT` en ambos procesos. No hay opción para escuchar en una
IP pública. La comunicación exige una credencial aleatoria cifrada con la clave
local de Studio. No habilita CORS ni acepta peticiones originadas en páginas web.

En Studio, elige **Windows UIA**, conecta y prueba **una imagen**. No uses simultáneamente
la misma ventana de Flow mientras el agente trabaja. Otras secciones de Studio pueden
seguir abiertas. No hay captura continua de pantalla: se inspeccionan controles a
intervalos de tres segundos durante generación/descarga.

Si la interfaz no expone controles accesibles, el resultado no se puede correlacionar
o Guardar como pertenece a un proceso fuera del permitido, utiliza el modo asistido.
No se añaden permisos, banderas de depuración ni excepciones de antivirus automáticamente.

### Inicio automático opcional

Después de validar la instalación, ejecuta explícitamente:

```powershell
.\scripts\configurar_inicio_flow.ps1 -Enable
# Para quitarlo:
.\scripts\configurar_inicio_flow.ps1 -Disable
```

Solo crea/quita el acceso directo de este agente en Inicio del usuario. No modifica
la política de ejecución de PowerShell, no inicia sesión en el proveedor y no evita
una verificación humana. Tras reiniciar Windows, inicia sesión y abre Userlfex/Flow.

## MCP y permisos

Por **stdio**, el cliente local autorizado obtiene las herramientas `flow_*` al iniciar
`frutinovelas-mcp`. Studio y el agente permanecen en el mismo PC.

Por **HTTP**, Flow solo se registra cuando `FRUTINOVELAS_MCP_TOKEN` está configurado.
El transporte exige `Authorization: Bearer <token>` también para inicializar y listar
herramientas. El token no se devuelve en el panel de conexión. El túnel/cliente debe
transmitir esa cabecera; si no lo admite, utiliza stdio. No se implementa OAuth.
La modalidad pública de prueba sin autenticación conserva las herramientas previas,
pero **no publica Flow ni acceso al agente Windows**.

La API verifica una credencial interna distinta para llamadas MCP a Flow y aplica
`FRUTINOVELAS_MCP_PROJECT_ID` y `FRUTINOVELAS_MCP_ACCESS_MODE=read_only|read_write`.
La reconciliación manual solo está disponible en la interfaz local. Los controles
locales rechazan hosts, orígenes web y cabeceras de proxy no permitidos.

| Herramienta | Operación |
|---|---|
| `flow_detect_window`, `flow_get_status`, `flow_list_available_modes` | Detección y capacidades del perfil; estado desconocido cuando falta evidencia. |
| `flow_connect`, `flow_disconnect`, `flow_focus_window` | Conectar, pausar la cola o enfocar la ventana autorizada. |
| `flow_submit_image`, `flow_submit_video`, `flow_generate_scene` | Encolar una escena con IDs/revisión reales, prompt opcional y UUID de solicitud. |
| `flow_generate_chapter` | Selección ordenada de escenas con `scene_revisions`; inserción atómica. |
| `flow_get_job`, `flow_list_jobs` | Solicitud congelada, estados y resultados por proyecto. |
| `flow_cancel_job`, `flow_retry_job` | Cancelación local y nueva versión de un intento definitivamente terminado. |
| `flow_import_result` | Validar/asociar una imagen por `asset_id` ya registrado. MP4: agente o carga local. |
| `flow_review_image` | Aprobar/rechazar conforme a una decisión explícita del usuario. |

No cambies `request_id` al perder una respuesta. Repetir el mismo cuerpo devuelve
la solicitud original, aunque la escena haya cambiado después. Cambiar el cuerpo
con ese ID produce conflicto. Reintentar un fallo crea otra versión con el snapshot
original; un cambio editorial requiere una solicitud nueva con la revisión actual.
Si se reintenta una imagen fallida cuya animación todavía espera aprobación, se crea
también una nueva animación dependiente de esa imagen. Las versiones anteriores se
conservan; una animación que el usuario ya canceló no se reactiva.

## Estados, cancelación y recuperación

| Estado | Acción permitida |
|---|---|
| `queued` | Envío pendiente; se puede cancelar antes de que salga. |
| `awaiting_import` | Modo asistido; espera una descarga de esa escena. |
| `awaiting_approval` | Video bloqueado hasta aprobación de su imagen. |
| `submitting`, `running`, `downloading` | Ejecución/recuperación identificada. |
| `unknown`, `blocked` | No reenviar. Verificar ventana, cuota, CAPTCHA o resultado; se conserva la reserva. |
| `cancel_requested` | Se solicitó cancelar, pero la detención remota no está confirmada. |
| `completed` | Archivo descargado/importado y validado; aprobación de imagen es otra decisión. |
| `failed`, `cancelled` | Solo se reintenta cuando `remote_stopped=true`. |

Un reinicio del agente convierte preparaciones/envíos/descargas interrumpidos en
`unknown`, conservando su reserva. El backend consulta por ID; **nunca repite un POST
incierto**, incluso si el agente responde que no conoce ese ID. La ausencia de un
registro no demuestra que la generación no haya ocurrido.

El perfil actual no implementa una cancelación remota verificable. **Cancelar localmente**
no pulsa un botón global de Flow ni cancela el trabajo de otra persona. Si el resultado
termina después de pedir cancelación, se conserva como resultado y no se reenvía.

Para cerrar un trabajo incierto de UIA:

1. Comprueba en Flow que terminó o se detuvo. Importa el resultado si existe.
2. Cierra el agente con Ctrl+C. Usa el UUID mostrado en el trabajo:

```powershell
py -3.12 -m uv run --extra flow-agent --frozen frutinovelas-flow-agent resolve --job-id UUID_REAL --confirmed-no-remote-work
.\iniciar_flow_agente.cmd
```

3. Studio consultará el diario y confirmará su cierre. Si no se puede recuperar el
   agente original, usa **Resolver manualmente** solo tras comprobar la ventana;
   conserva el diario original para auditoría. No borres su SQLite para liberar la cola.

Desconectar pausa la cola local sin destruir registros. Un agente con otra identidad
no puede hacerse cargo silenciosamente de un envío previo. Cuotas, CAPTCHA y controles
de acceso requieren intervención legítima; no se reintentan para eludirlos.

## Validación y aceptación

```powershell
py -3.12 -m uv sync --extra dev --extra flow-agent --frozen
py -3.12 -m uv run --frozen pytest
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
```

Las pruebas nuevas cubren persistencia, idempotencia, orden del capítulo, aislamiento
por proyecto, aprobación explícita/automática, conflictos de revisión, recuperación
sin reenvío, diario del agente, cancelación, credenciales, origen/host, importación
PNG y decodificación MP4 real. Las interacciones con ventanas se prueban con un doble
de UIA; no prueban compatibilidad con Userlfex, licencias, calidad visual ni cuotas.

Aceptación real pendiente, antes de procesar un capítulo completo:

1. Identificar producto, versión, ejecutable y permisos del proveedor.
2. Inspeccionar controles y preparar/verificar el perfil de la ventana real.
3. Generar una imagen 9:16 desde Studio; descargar, importar y revisar identidad visual.
4. Aprobarla y generar un MP4 con su imagen inicial y prompt editorial.
5. Verificar asociación, formato, duración real, original y conservación de la narración.
6. Interrumpir la conexión tras el envío, reiniciar agente/Studio y comprobar que no
   se genere una segunda solicitud. Probar cuota, verificación humana y cancelación.

Hasta completar estas pruebas, el PR permanece como borrador y la automatización
completa de la ventana Userlfex no debe presentarse como comprobada.
