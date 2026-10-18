# MCP público temporal para pruebas (sin autenticación)

Esta alternativa resuelve el problema de **«Acceso denegado» del túnel privado de OpenAI** cuando necesitas probar FRUTINOVELAS desde otra cuenta o cliente que permita añadir servidores MCP remotos. No usa el túnel privado de OpenAI ni sus permisos de organización.

**Importante:** el URL generado es público y **NO exige autenticación**. Cualquier persona con el enlace puede usar las herramientas de FRUTINOVELAS, incluidas las que consultan proyectos, modifican escenas y solicitan generación con GPU. Usa **datos descartables**, no lo compartas públicamente y detén el túnel al terminar. No es un despliegue de producción.

## Pasos en Windows

1. Instala Cloudflare `cloudflared` si no lo tienes. En PowerShell o CMD: `winget install --id Cloudflare.cloudflared`. Abre una consola nueva tras instalar; confirma con `cloudflared --version`.
2. Cierra los procesos que estén generando o editando trabajos críticos. En la carpeta `frutinovelas-studio`, ejecuta `iniciar.cmd` para iniciar Studio y su API. Déjalo abierto.
3. En otra consola CMD, dentro de `frutinovelas-studio`, ejecuta **`publicar_mcp_prueba.cmd`** (o haz doble clic). El lanzador utiliza tu configuración `.env`, comprueba el puerto y arranca MCP en **127.0.0.1**, nunca en `0.0.0.0`.
4. Escribe **`PUBLICAR`** para confirmar que entiendes que cualquiera que tenga el enlace podrá usar las herramientas. Cloudflare Quick Tunnel mostrará algo como `https://nombre-aleatorio.trycloudflare.com/mcp`. **Es solo un ejemplo**: copia el HTTPS exacto que aparezca en tu consola. No reutilices una URL anterior.
5. En ChatGPT o Claude, donde tu cuenta permita agregar un servidor MCP personalizado, selecciona **Remote / URL** (no **Tunnel** de OpenAI), pega el HTTPS completo y elige **No authentication** si te lo pregunta. Instálalo y prueba `get_directing_guidance` con `task="animation", preset="general"`. Que el servidor local diga «ready» no confirma que el cliente externo esté conectado.
6. Pulsa **Ctrl+C** en la consola de la prueba cuando termines. El servidor y el túnel iniciados por ese comando se cierran. Si reutilizaste un servidor MCP anterior, ese servidor permanece abierto localmente; solo termina el túnel.

**Si ya tienes MCP escuchando en el puerto 8766**, ejecuta desde CMD en `frutinovelas-studio`:

```cmd
py -3.12 -m uv run --frozen python scripts\public_mcp_tunnel.py --existing-mcp
```

Si configuraste otro puerto MCP o API en `.env`, se reutiliza automáticamente; también puedes indicar `--port 8767 --api-port 8765`.

## Si no conecta

- **No aparece `cloudflared`:** ejecuta `cloudflared --version`; reinicia la consola o instala desde [Cloudflare](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
- **Puerto ocupado:** prueba `--existing-mcp` solo si sabes que es el MCP correcto; de lo contrario, detén el proceso anterior o usa otro puerto.
- **Respuesta 421 por Host:** el comando del lanzador fija el encabezado Host de origen en `127.0.0.1:PUERTO`, conservando la protección de destino local del MCP.
- **La URL deja de funcionar:** los dominios `trycloudflare.com` son temporales. Debes mantener el programa y la consola abiertos y copiar el nuevo enlace al reiniciar.
- **El cliente rechaza la URL o no permite MCP:** tu cuenta o workspace puede no permitir instalar conectores remotos personalizados, incluso si la URL es pública. Eso no se corrige en FRUTINOVELAS.
- **Claude web o ChatGPT piden OAuth:** no inventes credenciales. El modo anónimo solo funciona en clientes que admitan esa modalidad.
- **Prueba de lectura:** pide llamar a `get_directing_guidance`, verifica la llamada de herramienta y evita enviar una orden de generación durante la prueba.

Este método **no instala ni administra un servidor en la nube**: `cloudflared` entrega una URL pública temporal que reenvía solicitudes a tu servidor local. Debes dejar tu PC encendida y conectada. La URL es distinta a la URL y token del gateway de ComfyUI en Colab/RunPod.

Fuentes: [documentación de Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/), [conexión MCP a Studio](CONEXION_MCP.md), [autenticación](AUTENTICACION.md).
