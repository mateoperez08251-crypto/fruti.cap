# Autenticación y credenciales de FRUTINOVELAS Studio

Esta explicación contrasta el código con los documentos del repositorio. La revisión
inicial usó el commit 84af42e4da879cb19796822c5343c51dabe2580f. La incorporación de
audios conserva estos mecanismos: una subida de audio pasa por la misma API local
y su envío a ComfyUI utiliza el cliente autenticado del trabajo.

## Componentes y recorrido de una solicitud

| Trayecto | Componente | Credencial efectiva |
|---|---|---|
| Navegador → Studio | frontend/src/api.ts y src/frutinovelas/api.py | Token API opcional; la interfaz actual no lo añade. |
| Cliente → MCP local | src/frutinovelas/mcp_server.py | stdio o HTTP en loopback; sin validador propio de token MCP. |
| MCP → API local | src/frutinovelas/mcp_studio.py | FRUTINOVELAS_API_TOKEN, si está configurado. |
| API → cola local | services/generation.py y modelos SQLAlchemy | Copia cifrada del token del gateway, dentro del trabajo. |
| Worker → gateway | worker.py y services/comfy.py | Authorization: Bearer con el token del gateway. |
| Gateway → ComfyUI | scripts/comfy_gateway.py | Se eliminan las credenciales del gateway antes de reenviar. |

No hay cuentas de usuario, inicio de sesión con contraseña, cookies de sesión,
OAuth, JWT ni refresh tokens implementados en estos componentes. Las credenciales
operativas son secretos compartidos; no identifican usuarios distintos.

## API local y navegador

[Settings](../src/frutinovelas/config.py) carga variables de entorno y, opcionalmente,
un archivo .env. El token local es FRUTINOVELAS_API_TOKEN.

El middleware require_token de [api.py](../src/frutinovelas/api.py) exige coincidencia
exacta con Authorization: Bearer cuando se cumplen las tres condiciones siguientes:

- Hay un token configurado.
- La ruta empieza por /api/.
- El método no es GET, HEAD ni OPTIONS.

La comparación usa secrets.compare_digest. Un fallo devuelve HTTP 401. Sin token,
ese middleware no exige credenciales. Las lecturas quedan exentas incluso si existe
token; esto incluye los archivos accesibles mediante GET.

[frontend/src/api.ts](../frontend/src/api.ts) utiliza fetch con rutas relativas
/api/v1. Su ayuda JSON añade Content-Type, pero no Authorization. Por ello, activar
el token API hace que las escrituras de la interfaz incluida reciban 401, salvo que
otra capa introduzca la cabecera. El adaptador MCP sí la envía.

El lanzador principal rechaza escuchar fuera de loopback cuando no hay token.
Esta comprobación está en main(), no en create_app(): un despliegue ASGI distinto
no recibe automáticamente la protección del lanzador.

La configuración CORS acepta los dos orígenes locales del servidor Vite.
CORS es una política del navegador; no es autenticación ni equivale a un control
propio de Host, Origin o CSRF. La API inspeccionada no implementa ese control propio.

La prueba [test_api.py](../tests/test_api.py), test_token_required_for_writes, comprueba escrituras
sin token rechazadas, lectura sin token permitida y escritura con Bearer aceptada.

## MCP y túnel

[mcp_server.py](../src/frutinovelas/mcp_server.py) registra las herramientas mediante
MCPServer. El transporte predeterminado es stdio; el modo streamable-http escucha
en loopback, normalmente en el puerto 8766 y en /mcp. El CLI rechaza hosts públicos.

El servidor no configura un proveedor de autenticación ni valida
FRUTINOVELAS_MCP_TOKEN. La documentación atribuye las comprobaciones Host/Origin al
SDK; [test_mcp_http.py](../tests/test_mcp_http.py) prueba el rechazo de un Host no
confiable con 421 y una conexión MCP local sin token propio.

El panel **Conexión MCP** no añade OAuth ni un inicio de sesión. Lee
`GET /api/v1/mcp/connection` para obtener rutas, comandos y configuración sin
tokens. `GET /api/v1/mcp/status` inicializa una sesión MCP HTTP local y lista
herramientas; no verifica una cuenta de ChatGPT o Claude ni llama a inferencia.
Estos endpoints siguen las reglas de lectura de la API local descritas arriba.

Para Claude Desktop, el JSON generado usa el Python de Studio, el puerto API y
`--directory` con la carpeta del proyecto. El MCP lee así su `.env` antes de
cargar Settings; el token API, si existe ahí, no se copia en el JSON ni se
devuelve al navegador. El cliente arranca el MCP por stdio. Esta configuración
no equivale a publicar un servidor remoto para Claude web. Véase
[Conexión MCP desde Studio](CONEXION_MCP.md).

studio_request(), en [mcp_studio.py](../src/frutinovelas/mcp_studio.py), llama a
http://127.0.0.1:{api_port}/api/v1/ y añade FRUTINOVELAS_API_TOKEN si existe.
No sigue redirecciones ni hereda proxies del entorno.

### Configuración declarada que no aplica una política real

Settings y .env.example declaran MCP_TOKEN, MCP_BACKEND_TOKEN, MCP_PROJECT_ID y
MCP_ACCESS_MODE con prefijo FRUTINOVELAS_. En los componentes inspeccionados:

- MCP_TOKEN no se comprueba al entrar.
- MCP_BACKEND_TOKEN no se usa en la solicitud al backend; se usa api_token.
- MCP_PROJECT_ID y MCP_ACCESS_MODE no restringen las herramientas.
- Las anotaciones read_only_hint describen herramientas; no son controles de acceso.
- El adaptador construye su URL local con api_port; no toma api_url para ese trayecto.

Configurar estas variables no equivale a habilitar las políticas que describen sus
comentarios. Esta es una discrepancia entre configuración/documentación e implementación.

La [guía del túnel](CONEXION_MCP_Y_TUNNEL.txt) utiliza un servidor MCP sin
autenticación propia. CONTROL_PLANE_API_KEY autentica el proceso tunnel-client.
El ejemplo lee la clave sin eco y la entrega al entorno de sus procesos hijos.
El repositorio no implementa la emisión ni renovación de esa clave externa.

## Credenciales de descarga y de túneles remotos

Estos secretos tienen funciones distintas de los tokens de la API y del gateway:

| Variable | Uso comprobado en el código |
|---|---|
| HF_TOKEN | [fruti_remote.py](../scripts/fruti_remote.py) lo lee del entorno y lo entrega a hf_hub_download para descargar modelos. El generador de Colab lo obtiene mediante su ayuda secreto() y lo pasa a la misma biblioteca. |
| CF_TUNNEL_TOKEN | En el modo de túnel con nombre, los scripts lo entregan a cloudflared mediante TUNNEL_TOKEN en el entorno del proceso hijo; no lo incluyen como argumento de la orden. |
| FRUTI_COMFY_TOKEN o COMFYUI_TOKEN | Son alias de Settings.comfyui_token. [routes/system.py](../src/frutinovelas/routes/system.py) utiliza ese valor para consultar el estado de ComfyUI cuando aún no hay una conexión guardada. |

CF_TUNNEL_HOSTNAME es el nombre público del túnel, no su credencial. Estos scripts
no implementan la emisión ni renovación de tokens de Hugging Face o Cloudflare.
Véanse [fruti_remote.py](../scripts/fruti_remote.py) y
[build_colab_notebook.py](../scripts/build_colab_notebook.py).

## Conexión con ComfyUI

### Captura y guardado

[ConnectionPage.tsx](../frontend/src/pages/ConnectionPage.tsx) conserva el token en
estado React y lo muestra en un campo password. Lo envía a
PUT /api/v1/comfy/connection y vacía el campo cuando el guardado tiene éxito.
No lo persiste en localStorage en este recorrido.

[routes/generation.py](../src/frutinovelas/routes/generation.py) recibe el token
como SecretStr, quita espacios y exige al menos 16 caracteres. Dejarlo vacío
conserva el anterior únicamente cuando la URL coincide con la conexión guardada.

Antes de guardar, el cliente comprueba el gateway, su identidad y el workflow.
Un fallo de comprobación devuelve 422. El token válido se cifra con Fernet y se
guarda en ComfyConnection.encrypted_token.

### Clave local y trabajos

cipher(), en [services/comfy.py](../src/frutinovelas/services/comfy.py), crea
comfy_credentials.key en el directorio de datos. Usa creación exclusiva y modo
0600, y reutiliza la clave existente. No deriva esta clave de una contraseña ni
utiliza un almacén de credenciales del sistema operativo.

Al encolar, [services/generation.py](../src/frutinovelas/services/generation.py)
captura conexión, identidad, workflow y token cifrado. Cada GenerationJob mantiene
su propia copia cifrada. Modificar la conexión después no cambia las credenciales
de un trabajo ya enviado.

Las respuestas públicas se construyen con campos explícitos: muestran has_token
y metadatos de trabajo, pero no el secreto, su ciphertext ni el snapshot completo.

Conseguir a la vez la base de datos y comfy_credentials.key permite descifrar
los tokens. La copia de seguridad debe preservar ambos; el README indica mantener
el directorio de datos fuera de Git. Los originales de voz y los audios siguen el
almacenamiento gestionado de assets de ese directorio.

### Transporte, integridad y gateway

ComfyClient exige HTTPS para conexiones remotas; permite HTTP para los nombres
loopback admitidos. Rechaza credenciales incrustadas, parámetros y fragmentos en
la URL. Añade Authorization: Bearer, usa trust_env=False y no sigue redirecciones.

Durante la conexión consulta /system_stats, /frutinovelas/identity y el archivo
del workflow. Compara su SHA-256 con la identidad publicada y valida el contrato
del grafo. El worker vuelve a comprobar la identidad antes de continuar.
El hash viene del mismo gateway: sirve para comprobar consistencia del workflow
con la identidad anunciada, no como una firma independiente de otro emisor.

[scripts/comfy_gateway.py](../scripts/comfy_gateway.py) deja público /healthz y
protege las demás rutas. Acepta Bearer o X-Frutinovelas-Token, compara mediante
hmac.compare_digest y devuelve 401 al fallar. Después de 20 fallos recientes por
IP responde 429 a intentos inválidos; una credencial correcta sigue funcionando.

El proxy aplica una lista de rutas/métodos y elimina Authorization,
X-Frutinovelas-Token y Cookie al reenviar a ComfyUI. Los audios utilizan la ruta
de subida existente y la misma autenticación; no requieren exponer otra ruta remota.

## Emisión, rotación y errores

El token API es una cadena configurada, sin caducidad, refresh ni logout. Settings
se cachea; el funcionamiento normal requiere reiniciar procesos para cargar cambios.

[scripts/fruti_remote.py](../scripts/fruti_remote.py) obtiene el token del gateway
del entorno, reutiliza el archivo existente o genera secrets.token_urlsafe(32).
Lo guarda en secrets/gateway_token.txt, con modo 0600 dentro de una carpeta 0700.

fruti token --regenerar escribe un nuevo secreto y detiene el gateway. La herramienta
pide arrancarlo y actualizar Studio. Si FRUTI_GATEWAY_TOKEN continúa definido en
el entorno, tiene prioridad al volver a obtener el token.

Rotar la conexión no reemplaza los tokens capturados por trabajos anteriores.
Una recuperación de esos trabajos puede requerir tener en cuenta la credencial original.

El worker trata 401/403 al enviar /prompt como rechazo conocido y marca el trabajo
como fallido. Ante un timeout de envío, conserva la incertidumbre y consulta cola e
historial sin reenviar la inferencia. Un fallo en comprobaciones o sondeos no siempre
marca failed: el bucle general puede conservar el estado y registrar el error para
reintentar. Véanse _submit y el bucle de recuperación en [worker.py](../src/frutinovelas/worker.py).
