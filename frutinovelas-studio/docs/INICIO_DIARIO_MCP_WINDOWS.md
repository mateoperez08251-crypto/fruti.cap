# Iniciar y recuperar el MCP de Frutinovelas en Windows

Guía de la instalación que se conectó el **18 de octubre de 2026**.
La prueba real desde ChatGPT pudo leer las guías de dirección y listar los
proyectos de Studio. No se enviaron generaciones GPU.

## Datos de esta instalación

| Elemento | Valor |
|---|---|
| Carpeta del repositorio | D:\fruti.cap |
| Carpeta de Studio | D:\fruti.cap\frutinovelas-studio |
| Programa y API | http://127.0.0.1:8765 |
| MCP local | http://127.0.0.1:8766/mcp |
| Carpeta de tunnel-client | D:\descargas\tunnel-client-v0.0.16-windows-amd64 |
| Perfil creado durante la recuperación | fruti-nuevo |
| Archivo del perfil | %APPDATA%\tunnel-client\fruti-nuevo.yaml |
| Plugin seleccionado en la prueba correcta | mcp |

Estas rutas corresponden a esta PC; adáptalas si mueves las carpetas. La versión
0.0.16 identifica la copia instalada, no una recomendación de versión permanente.
No deduzcas el Tunnel ID a partir del identificador del plugin: revisa el perfil
y comprueba que ChatGPT selecciona el mismo túnel.

**Conserva el túnel y el perfil que funcionan.** No hace falta recrearlos cada día.
No borres proyectos, bases de datos, referencias ni credenciales para reconectar.

## Arranque diario: tres ventanas de PowerShell

Ejecuta cada bloque completo, espera su resultado y después continúa.
No copies los prefijos PS ...> o >> de una conversación.

### Ventana 1: programa

~~~powershell
& "D:\fruti.cap\frutinovelas-studio\iniciar.cmd"
~~~

Espera a que abra http://127.0.0.1:8765. Deja la ventana abierta.
En el código revisado, iniciar.cmd prepara dependencias, compila la interfaz y
arranca la API. **No inicia el MCP ni tunnel-client.**
actualizar.cmd solo comprueba/aplica actualizaciones; no es otro iniciador.

### Ventana 2: MCP

~~~powershell
& "D:\fruti.cap\frutinovelas-studio\.venv\Scripts\python.exe" -m frutinovelas.mcp_server --directory "D:\fruti.cap\frutinovelas-studio" --transport streamable-http --host 127.0.0.1 --port 8766 --api-port 8765
~~~

Espera Application startup complete y Uvicorn running en el puerto 8766.
Deja la ventana abierta. Si ya responde un MCP de esta instalación, reutilízalo.
El panel Conexión MCP también ofrece el comando adaptado a la instalación.

### Ventana 3: túnel

~~~powershell
Set-Location "D:\descargas\tunnel-client-v0.0.16-windows-amd64"
Test-Path ".\tunnel-client.exe"
.\tunnel-client.exe profiles list
~~~

Test-Path debe devolver True. Comprueba que aparece fruti-nuevo. Después:

~~~powershell
py -3.12 -c "import getpass,os,subprocess; e=os.environ.copy(); e['CONTROL_PLANE_API_KEY']=getpass.getpass('API key de runtime del tunel: ').strip(); r=subprocess.call([r'D:\descargas\tunnel-client-v0.0.16-windows-amd64\tunnel-client.exe','doctor','--profile','fruti-nuevo','--explain'],env=e); raise SystemExit(r or subprocess.call([r'D:\descargas\tunnel-client-v0.0.16-windows-amd64\tunnel-client.exe','run','--profile','fruti-nuevo','--health.listen-addr','127.0.0.1:8080'],env=e))"
~~~

Al aparecer API key de runtime del tunel:, pega la clave y pulsa Enter.
**No se ven caracteres mientras la introduces. Es normal.**
La clave solo se pasa al entorno de los procesos hijos; no queda disponible
en la PowerShell para otro comando posterior. Si otro doctor anuncia que
CONTROL_PLANE_API_KEY no está definida, eso no demuestra que la clave sea inválida.

Usa una clave de runtime de la organización autorizada para el túnel.
El token del gateway de Colab/ComfyUI es otra credencial.
No pegues claves en el chat, Git, comandos literales, YAML ni capturas.
No uses setx para guardar esta clave.

Deja la ventana abierta. Si doctor falla, el comando no inicia run.
Si el puerto de salud 8080 está ocupado, identifica primero su proceso:
puede pertenecer a otro túnel ya activo. No lo cierres a ciegas.

### ChatGPT: comprobar la conexión real

Selecciona con @ el plugin mcp que quedó conectado. Si cambiaste el túnel,
el plugin debe apuntar al nuevo Tunnel ID; cambiar el perfil local no cambia
automáticamente el plugin. Si la interfaz no permite editar ese destino,
crea una conexión nueva mediante Tunnel y selecciona el túnel correcto.
Para el MCP de este repositorio se usa No authentication; la clave de runtime
autentica el cliente del túnel ante OpenAI.

Pide una prueba de lectura:

> Usa este MCP. Llama a get_directing_guidance con task="animation",
> preset="frutinovelas" e include_example_story=false. Después llama a
> list_studio_projects. No guardes cambios ni generes imágenes o videos.

La conexión solo se considera comprobada cuando las llamadas terminan bien.
El nombre del plugin, doctor correcto, un mensaje verde de arranque o un
HTTP 200 del panel de estado no acreditan por sí solos acceso desde ChatGPT.
No hace falta encender ComfyUI para leer guías o preparar prompts.

## Diagnóstico: separar MCP local y túnel

### A. ¿Responde el MCP en esta PC?

En otra PowerShell:

~~~powershell
curl.exe --noproxy "*" --max-time 5 -i http://127.0.0.1:8766/mcp
~~~

| Resultado | Qué significa |
|---|---|
| 200 y content-type: text/event-stream | El servidor respondió y abrió SSE. La petición puede quedar abierta hasta el límite de curl. |
| 405 o 406 | El servidor respondió; la petición GET de prueba puede no cumplir el protocolo/cabeceras requeridos. |
| Timeout con 0 bytes | No recibió respuesta HTTP; investigar el MCP local antes de modificar el túnel. |
| Conexión rechazada | No hay un servidor accesible en esa dirección/puerto. |

Esta prueba no inicializa una sesión MCP completa. El panel Conexión MCP →
comprobar intenta inicializar y listar herramientas; la prueba final sigue
siendo una llamada real desde ChatGPT.

Si no responde, identifica el proceso:

~~~powershell
Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess
~~~

Copia el OwningProcess real en esta consulta:

~~~powershell
$frutiMcpPid = Read-Host "PID que escucha en 8766"
Get-CimInstance Win32_Process -Filter "ProcessId = $frutiMcpPid" |
    Select-Object ProcessId, Name, ExecutablePath, CommandLine |
    Format-List
~~~

Si se confirma que es frutinovelas.mcp_server y sigue sin responder, detén
ese MCP con Ctrl+C en su ventana y vuelve a ejecutar el bloque de la ventana 2.
Si no puedes detenerlo desde su consola, Stop-Process -Id seguido del PID
confirmado permite detener solo ese proceso. Los PID cambian; no reutilices
los números de un registro antiguo.

No detengas todos los Python ni cierres Studio para reiniciar solo el MCP.
Si seleccionaste texto en una consola clásica de Windows, pulsa Esc: esa
selección puede pausar su proceso.

Durante la recuperación, un MCP antiguo escuchaba pero agotaba el tiempo.
Al reiniciarlo, respondió 200. Esto resolvió el problema local, no el 401 de OpenAI.

### B. ¿Se autentica el túnel?

| Mensaje | Acción |
|---|---|
| CONTROL_PLANE_API_KEY is not set | Introducir la clave usando el bloque oculto de esta guía. |
| 401 Unauthorized / 403 | Revisar la credencial utilizada, su organización, la asociación del túnel y los permisos de su propietario. Reiniciar MCP no lo corrige. |
| tunnel-client started | El proceso arrancó; aún no prueba autenticación ni polling correcto. |
| tunnel meta hasn't fetched | Todavía no se obtuvieron los metadatos; no declarar conexión correcta. |
| tunnel_client_not_seen | ChatGPT no ve un cliente activo para el túnel configurado en ese plugin. Revisar destino y registro de tunnel-client. |
| oauth discovery con timeout | Comprobar respuesta del MCP local. |
| 404 en .well-known/oauth-protected-resource | Puede ser esperado en este MCP sin OAuth; no añadir OAuth solo por ese aviso. |
| 400 o 406 durante sondeos | Puede corresponder al formato/cabeceras de la prueba. Si ocurre en una llamada MCP real, revisar esa llamada. |
| Terminating session: None | Por sí solo no indica que el servidor haya terminado. |
| KeyboardInterrupt | Se detuvo el proceso con Ctrl+C. |
| WinError 2 | Comprobar la ruta del ejecutable y Test-Path; no es un rechazo de la API key. |
| >> en PowerShell | Instrucción incompleta: Ctrl+C y pegar nuevamente el bloque completo. |

Para revisar la asociación y permisos:
[Platform → Túneles](https://platform.openai.com/settings/organization/tunnels),
[API keys de runtime](https://platform.openai.com/settings/organization/api-keys)
y People/Roles de la misma organización.
Ser dueño y poder ver el túnel en el navegador no acredita qué clave se
introdujo en la terminal. La identidad de esa clave necesita Tunnels Read + Use.
No se determinó la causa exacta de los 401 de la configuración anterior:
no presentarlos como un fallo demostrado de membresía o de una clave concreta.

Con el puerto de salud 8080 configurado, en otra ventana:

~~~powershell
curl.exe --max-time 5 --fail http://127.0.0.1:8080/healthz
curl.exe --max-time 5 --fail http://127.0.0.1:8080/readyz
Start-Process "http://127.0.0.1:8080/ui"
~~~

No compartir la clave ni exportaciones sin revisar. Comparar los errores del
cliente con el túnel del plugin; un perfil nuevo no reconecta el plugin anterior.

## Evitar las dos copias del repositorio

Se encontraron rutas anidadas durante el soporte. La ruta usada en esta guía
es D:\fruti.cap\frutinovelas-studio. Para comprobar el checkout:

~~~powershell
git -C "D:\fruti.cap" rev-parse --show-toplevel
git -C "D:\fruti.cap" log -1 --oneline
Get-ChildItem "D:\fruti.cap" -Recurse -File -Filter "iniciar.cmd" |
    Select-Object -ExpandProperty FullName
~~~

No borres una copia solo por encontrar dos: compara rutas, git status, versión
y datos antes de retirarla. No ejecutes dos programas o dos MCP sobre los mismos
puertos. Para actualizar, espera a terminar las generaciones y cierra Studio y MCP;
iniciar.cmd exige servidores detenidos para actualizar.

## Cierre y siguiente inicio

Termina los trabajos y usa Ctrl+C para cerrar túnel, MCP y programa.
Al volver, repite las tres ventanas y selecciona el mismo plugin. Colab es
independiente: su URL/token se gestionan en Conexión ComfyUI y su sesión debe
estar activa cuando se vaya a generar. Cerrar Windows no detiene una GPU remota.

## Referencias

- [Guía general del repositorio](CONEXION_MCP_Y_TUNNEL.txt).
- [Panel MCP de Studio](CONEXION_MCP.md).
- [Secure MCP Tunnel de OpenAI](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
- [Diagnóstico del cliente oficial](https://github.com/openai/tunnel-client/blob/master/docs/troubleshooting.md).
