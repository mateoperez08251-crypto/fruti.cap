# Conectar ChatGPT o Claude a Studio

Abre **Conexión MCP** en la barra lateral de Studio. El cuadro **Conectar ChatGPT
o Claude** reúne los comandos, la configuración del cliente y un diagnóstico
local. **Conexión ComfyUI** sigue siendo el lugar donde guardas la URL y el token
del servidor GPU; esos datos no son los del MCP.

Si el botón no aparece después de actualizar el repositorio, cierra Studio y el
MCP cuando no haya trabajos pendientes y ejecuta `iniciar.cmd` desde la carpeta
`frutinovelas-studio`. Este paso instala las dependencias y recompila la interfaz.
Vuelve a abrir Studio y recarga la página. Un `git pull` por sí solo no actualiza
la interfaz compilada ni los procesos que siguen abiertos.

## ChatGPT: usar el túnel privado

1. En el panel, elige **ChatGPT**. Si el MCP no está iniciado, copia su comando
   y ejecútalo en la consola indicada por el panel —**PowerShell** en Windows—;
   mantén esa consola abierta. El comando usa las rutas de esta instalación e
   incluye el puerto de Studio mediante `--api-port`.
2. Reutiliza tu perfil de `tunnel-client` y su túnel de OpenAI. La URL local que
   muestra Studio —normalmente `http://127.0.0.1:8766/mcp`— debe coincidir con la
   dirección de destino del perfil. Sigue la [guía completa del túnel](CONEXION_MCP_Y_TUNNEL.txt)
   si todavía no lo has configurado.
3. En la conexión de ChatGPT, selecciona ese túnel. Para el MCP de este repositorio
   se utiliza **No authentication**: la API key de runtime autentica
   `tunnel-client`, y se introduce mediante el procedimiento privado de la guía.
4. Con el plugin seleccionado, pide una llamada a `get_directing_guidance` y
   comprueba que devuelve las guías. No necesitas encender ComfyUI para esa prueba.

La URL de loopback se usa entre `tunnel-client` y el MCP de tu PC. No es una URL
pública para pegar en ChatGPT. El panel no crea túneles, no configura tu cuenta
ni arranca procesos; facilita los datos para que completes esos pasos.
El funcionamiento del túnel y su clave se describe en la
[guía oficial de OpenAI](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

Actualizar Studio no exige crear otro túnel ni cambiar sus credenciales. Si
cambias el puerto MCP, actualiza también el destino de tu perfil. Reinicia el
servidor MCP para que cargue las herramientas de la versión nueva.

## Claude Desktop: configuración local por stdio

1. En el panel, elige **Claude Desktop** y copia el JSON de configuración.
2. En Claude Desktop, abre **Settings → Developer → Edit Config**. Integra la
   entrada `frutinovelas` dentro de `mcpServers`; conserva las demás entradas y
   opciones del archivo. Si ya existe esa entrada, actualízala en lugar de
   añadir otra con el mismo nombre.
3. Guarda el archivo y cierra completamente Claude Desktop. Vuelve a abrirlo
   para que cargue la configuración y arranque el proceso MCP.
4. Mantén Studio abierto para consultar y guardar proyectos, personajes y escenas.
   Pide a Claude una llamada a `get_directing_guidance` para comprobar primero
   el acceso a las guías, sin solicitar una generación.

La ubicación de **Developer → Edit Config** y el reinicio completo están
documentados en la [guía oficial de servidores locales MCP](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers).

El JSON utiliza el ejecutable Python real de Studio y `--directory` con la carpeta
real del proyecto. Así el proceso MCP carga el mismo archivo `.env`; la configuración
copiada incluye el puerto de la API, sin copiar tokens. Si mueves el proyecto o
cambias su entorno Python, vuelve a copiar la configuración desde Studio.

Claude Desktop se comunica con ese proceso por **stdio**. No necesitas pegar una
URL HTTP, iniciar un segundo MCP en el puerto 8766 ni usar el túnel de OpenAI para
este cliente. Las guías se pueden consultar sin el servidor GPU; generar sí
requiere la conexión ComfyUI correspondiente.

## Claude web

Los [conectores remotos de Claude](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
reciben las solicitudes desde la nube de Anthropic. Para conectar este proyecto
a Claude web haría falta un servidor MCP remoto por HTTPS con autenticación
adecuada. Este panel todavía no prepara ese despliegue: el servidor HTTP del
repositorio acepta únicamente loopback.
No uses `localhost`, la URL del gateway ComfyUI ni el túnel privado de OpenAI
como dirección de conexión para Claude web. Para usar este proyecto localmente
con Claude, sigue los pasos de **Claude Desktop**.

## Qué comprueba el diagnóstico

El diagnóstico se ejecuta cuando lo solicitas en el panel. Studio intenta iniciar
una sesión de protocolo con el MCP HTTP local y listar sus herramientas. Si
responde, confirma que ese servidor es accesible y anuncia herramientas.
No llama a herramientas de generación, no arranca procesos y no verifica que
ChatGPT o Claude hayan cargado su conexión.

Si el MCP HTTP está detenido o escucha en otro puerto, corrige el comando y la
configuración antes de repetir la prueba. Una respuesta incompatible puede indicar
que ese puerto pertenece a otro MCP o a una versión anterior. **Un diagnóstico HTTP fallido no decide
si Claude Desktop funciona por stdio**: comprueba ese transporte desde Claude.
La prueba de extremo a extremo es una llamada real desde el cliente elegido.

Para soporte técnico, Studio ofrece dos lecturas: `GET /api/v1/mcp/connection`
devuelve metadatos y configuración sin tokens; `GET /api/v1/mcp/status` comprueba
el protocolo local con inicialización y listado de herramientas. Ninguna equivale
a una sesión iniciada en una cuenta externa. Consulta [Autenticación](AUTENTICACION.md)
para distinguir los controles efectivos de las variables declaradas.

## Conexión desde otras cuentas: URL pública temporal de prueba

Si el túnel privado de OpenAI devuelve «Acceso denegado» a otra organización o
workspace, puedes probar con una **URL HTTPS externa** sin asociar esas cuentas al
túnel privado. Consulta [MCP_PUBLICO_PRUEBA.md](MCP_PUBLICO_PRUEBA.md).

Abre **Conexión MCP → Prueba pública HTTPS** para ver los pasos. En Windows, dentro
de `frutinovelas-studio`, ejecuta `publicar_mcp_prueba.cmd` tras iniciar Studio.
El script pide escribir `PUBLICAR`, arranca el MCP en loopback (o reutiliza el
que está escuchando), crea un Cloudflare Quick Tunnel y muestra el enlace
`https://…trycloudflare.com/mcp`. En ChatGPT o Claude selecciona conexión
**remota / por URL**, no el túnel privado de OpenAI. La cuenta necesita tener
permitidos los servidores MCP personalizados.

**Aviso:** esta prueba no añade contraseña, autorización por usuario ni protección
de operaciones. Quien tenga la URL puede invocar también herramientas que
modifican proyectos o inician generaciones. Usa datos descartables y detén la
consola con Ctrl+C al terminar. No lo uses como servicio permanente.

## Importar imágenes creadas fuera de ComfyUI

Tras actualizar Studio y reiniciar el MCP, los clientes pueden descubrir `import_studio_image`. Para usarla deben transferir bytes base64 o suministrar una URL HTTPS pública que la PC pueda descargar; importar no asigna ni genera. La referencia detallada está en [IMPORTAR_IMAGENES_MCP.md](IMPORTAR_IMAGENES_MCP.md). La URL de prueba pública sin autenticación permite escrituras desde cualquier cliente que la conozca, por lo que conviene cerrarla al terminar.


## Administración de cola ComfyUI (MCP NARRAD)

Tras actualizar Studio y reiniciar MCP, `get_comfy_queue()` consulta los
trabajos propios, sus estados locales y si están pendientes o ejecutándose en
ComfyUI. No publica prompts ni entradas de trabajos ajenos.

`stop_comfy_generation(job_id, confirmed=true)` y el botón **Detener
generación** de los paneles Qwen/H3 intentan cancelar *un solo trabajo*:
- `queued`: cancela localmente antes de enviarlo.
- `waiting` / `running`: verifica la identidad del runtime y su cola remota.
  Si está pendiente, envía `POST /queue` con el ID exacto. Si está ejecutándose,
  solicita `POST /interrupt` **solo si es el único trabajo en ejecución**.
  Un interrupt es asíncrono; Studio conserva la reserva hasta confirmar que
  desapareció de la cola y no puede iniciar otro trabajo prematuramente.
- `uploading`, `submitting`, `downloading`, `unknown`: se rechaza la
  cancelación destructiva porque la recepción/descarga podría ser ambigua.
  Consultar primero la cola y el historial.

La detención nunca borra los resultados previos, referencias ni versiones. Para
una automatización de capítulo, la cancelación del trabajo activo provoca el
fallo seguro de ese proceso en el siguiente avance; no se continuarán escenas.
El gateway remoto debe admitir sus rutas nativas autenticadas `/queue` y
`/interrupt`; si el runtime ya no coincide, no se cancela nada.

**No se añade ninguna operación para vaciar indiscriminadamente toda la cola de
ComfyUI**. El cliente debe especificar el ID real del trabajo y confirmar la
acción. Los estados remotos se verifican en tiempo real; ComfyUI puede cambiar
entre lecturas, de modo que ante un conflicto hay que volver a consultar.
