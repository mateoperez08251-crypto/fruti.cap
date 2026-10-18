# Importar imágenes externas mediante MCP

La herramienta `import_studio_image` permite importar imágenes **ya creadas** fuera
de ComfyUI mediante dos entradas excluyentes: `content_base64` o `url`.
No inicia Qwen, H3, FFmpeg ni la GPU. Devuelve ID, nombre, MIME, dimensiones,
SHA-256 y si el archivo era nuevo o se reutilizó por hash.

## Entradas

```json
{
  "request_id": "8c1815e8-e65c-47f3-a596-e3001ae7f0c1",
  "filename": "escena-inicio.png",
  "mime_type": "image/png",
  "content_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
}
```

Por URL sustituye `content_base64` por
`"url": "https://servidor-publico.example/escena.png"`.
El enlace debe ser públicamente descargable desde la **PC del usuario**
con HTTPS válido; no se permiten redirecciones, DNS privados, IP literales,
credenciales en URL, puertos alternos, localhost ni redes internas.
Tiempo de conexión máximo 5 s y 18 s de lectura; descarga limitada durante
el streaming. No se reenvían cookies, tokens ni cabeceras de autenticación.

- Base64 MCP: máximo **4 MiB de bytes decodificados**. Algunos clientes MCP
  limitan el tamaño del JSON antes de llegar al servidor.
- HTTPS: máximo **40 MiB** o el límite menor configurado en Studio
  (`FRUTINOVELAS_MAX_UPLOAD_MB`).
- Formatos: PNG, JPEG, WebP; lado mayor máximo **8192 px** por defecto,
  lado menor mínimo 16 px. Se inspeccionan los bytes con Pillow.
- Repetir exactamente el mismo `request_id` devuelve el asset original y
  no inicia otra descarga; reutilizarlo con otro contenido o URL se rechaza.
  Archivos idénticos se deduplican por SHA-256 aunque usen otro request_id.

## Transferencia desde ChatGPT o Claude

Una imagen que está en el chat no reside en el PC de Studio. Para enviarla,
el cliente debe **leer sus bytes** y convertirlos a base64 antes de llamar a
`import_studio_image`. Un nombre local como `/tmp/foto.png` o
`sandbox:/mnt/data/foto.png` **no es una URL HTTP pública ni una ruta
del PC del usuario**. Si el cliente no permite leer esos bytes o excede el
límite MCP, usa un enlace HTTPS público válido, o transfiere los bytes
desde una aplicación que permita realizar un POST multipart a la API local
existente `POST /api/v1/assets`, por ejemplo el selector de imagen de Studio.

Una URL que exige la sesión privada de ChatGPT no es descargable
automáticamente por Studio. No se garantiza que todos los clientes puedan
transferir su resultado de imagen: depende de sus permisos y límites.

## Importar, revisar y asignar

1. `import_studio_image` crea/reutiliza el asset.
2. `inspect_studio_image(asset_id)` muestra miniatura y metadatos.
3. Solo con autorización explícita, usar
   `set_studio_scene_frame(scene_id, expected_revision, role, asset_id)`,
   con `role="start"` o `role="end"`. El backend valida que un final
   tenga una imagen inicial y conserva revisiones.
4. `get_scene_preparation` devuelve el nuevo estado I2VA o FL2VA.
   El botón habitual de Studio permite iniciar H3 **por petición separada**.

Los originales se almacenan fuera de Git en el directorio de datos de Studio.
H3 prepara una copia en 576×1024, sin modificar el archivo importado.
No hace falta migrar ni borrar los assets anteriores manualmente: la migración
0006 añade únicamente un registro de reintentos.

## Actualizar Windows

Con trabajos finalizados, detener Studio y MCP/túnel. Ejecutar
`actualizar.cmd`, después `iniciar.cmd`, y volver a iniciar
`publicar_mcp_prueba.cmd` si usas la prueba pública. Volver a configurar
la URL HTTPS temporal en ChatGPT si cambió; Claude Desktop debe reiniciarse
para descubrir la herramienta. La URL temporal sin autenticación sigue
exponiendo los proyectos a cualquier persona que la conozca.
