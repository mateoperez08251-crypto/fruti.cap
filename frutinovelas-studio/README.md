# FRUTINOVELAS Studio

## Abrir el programa en Windows

Desde esta carpeta, ejecuta `iniciar.cmd` (también admite doble clic). Instala las
dependencias necesarias, compila la interfaz e inicia la API. Necesita Python y
Node.js 22.12 o superior. El programa abre http://127.0.0.1:8765; mantén la terminal
abierta mientras lo utilizas. Los datos existentes se migran al arrancar.

Alternativa manual:

```powershell
py -3 -m uv sync
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
py -3 -m uv run frutinovelas-api
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

Esta entrega añade generación individual de video desde imágenes ya elegidas. La
generación de imágenes con Qwen, MCP y el montaje automático de capítulos siguen siendo
integraciones separadas. Los scripts de RunPod y sus modelos se conservan.

## Comprobar los cambios

```powershell
py -3 -m uv sync --extra dev
py -3 -m uv run pytest
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
```

Las pruebas de generación simulan el gateway: cubren autenticación, migración,
versiones, descarga, duplicados y recuperación. No miden calidad ni rendimiento GPU.
