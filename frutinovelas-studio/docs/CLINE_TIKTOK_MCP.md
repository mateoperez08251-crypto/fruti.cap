# Fruticap: Cline, Qwen en Colab, UserFlex y publicación en TikTok

Estado (26-10-2026): diseño y código en desarrollo. **No se ha probado UserFlex ni se ha publicado en TikTok real**.
Este módulo no modifica ni importa nada del repositorio `my-content`.

## Arquitectura elegida

- **ChatGPT:** prepara guiones, prompts, continuidad y referencias cuando tú lo solicites a través del MCP habitual.
- **Qwen 27B:** está en **Colab** y tú ya lo seleccionas como modelo de **Cline**, con URL de Cloudflare y API key. No hay que instalar ni ejecutar Qwen en tu PC o VM; esa URL pertenece al proveedor de modelo, no al MCP.
- **Cline (Windows):** cliente MCP que invoca las herramientas locales de Fruticap; idealmente corre **dentro de la misma VM** en la primera configuración.
- **Fruticap:** conserva su API, colas, escenas, montajes y el agente Flow que ya estaba implementado.
- **UserFlex/Flow:** ejecutable cerrado; haces el inicio de sesión y el segundo factor manualmente. Su automatización por UI Automation **requiere comprobar controles reales** con `docs/FLOW_AUTOMATION.md`. F12 no hace falta ni debe forzarse. **El control visual autónomo todavía no está implementado.**
- **TikTok:** Chrome normal, separado de UserFlex, con un perfil persistente exclusivo de Fruticap y Playwright. Tú inicias sesión manualmente. El MCP local solo admite videos MP4 de montajes **terminados** dentro de Fruticap.

**Nunca envíes cookies, claves de Google, tokens de sesión o códigos de 2FA a Qwen, ChatGPT, Colab ni GitHub.**

## Preparación del equipo (i5 cuarta generación, 24 GB RAM, SSD C: 128 GB con 16 GB libres, otro disco de 480 GB)

1. Identifica si el disco de 480 GB es SSD o HDD en `Desfragmentar y optimizar unidades`.
2. **No** pongas los archivos de la VM en C: (solo quedan 16 GB). Usa el disco de 480 GB, con al menos 80 GB libres como margen de instalación/crecimiento.
3. VirtualBox (gratuito) + Windows invitado correctamente licenciado y con actualizaciones de seguridad. Con i5 de cuarta generación **no des por supuesta la compatibilidad oficial de Windows 11**; verifica antes la posibilidad de un Windows invitado compatible y soportado. Windows 10 terminó su soporte general en 2025: necesita una vía de parches válida para uso conectado a internet.
4. Para comenzar probar **6144 MB RAM, 2 procesadores virtuales y disco VDI dinámico 70 GB**. El HDD puede hacer lento Windows; si el i5 no soporta bien la VM, usa provisionalmente el Windows anfitrión y la misma configuración MCP.
5. Preparador opcional de VM: ejecuta desde PowerShell `frutinovelas-studio/scripts/preparar_vm_userflex.ps1` con rutas reales a la ISO y el disco de 480 GB. **Solo crea el hardware virtual**, no instala ni activa Windows ni UserFlex. No se ejecuta automáticamente.

## Primer inicio en Windows de la VM (o en el anfitrión, sin VM)

1. Instala Python 3.12, uv, Node.js acorde al README, FFmpeg/FFprobe, Google Chrome y UserFlex por las fuentes autorizadas.
2. Clona `https://github.com/mateoperez08251-crypto/fruti.cap` y entra a `frutinovelas-studio`.
3. En PowerShell, ejecuta:

   ```powershell
   uv sync --extra flow-agent --extra dev --frozen
   npm --prefix frontend ci
   npm --prefix frontend run build
   .\iniciar.cmd
   # En otra terminal, DESPUÉS del último uv sync:
   uv pip install --python .venv/Scripts/python.exe playwright
   ```

   Para preparar Chromium en caso de que Chrome no esté instalado: `uv run python -m playwright install chromium`.
   De forma predeterminada TikTok usa Google Chrome instalado (`channel="chrome"`).
4. Mantén el programa abierto y comprueba `http://127.0.0.1:8765`. No intentes trasladar bases de datos/cookies de `my-content`.
5. Abre **Cline** en VS Code dentro del mismo Windows y configura tu proveedor Qwen a la URL de Colab/Cloudflare como ya lo tienes, **sin agregar la API key a los archivos del repo**.
6. En **Cline > MCP Servers > Configure**, añade este servidor stdio local,
   sustituyendo las DOS rutas del ejemplo por la ruta real a tu copia y su Python:

   ```json
   {
     "mcpServers": {
       "fruticap-local": {
         "command": "D:\\\\fruti.cap\\\\frutinovelas-studio\\\\.venv\\\\Scripts\\\\python.exe",
         "args": [
           "-m", "frutinovelas.mcp_server", "--transport", "stdio",
           "--directory", "D:\\\\fruti.cap\\\\frutinovelas-studio"
         ],
         "disabled": false,
         "autoApprove": []
       }
     }
   }
   ```

   Usa el Python de la misma `.venv`, sin ejecutar `uv run` desde Cline:
   eso permite mantener instalado Playwright manualmente. Si ejecutas otro
   `uv sync`, comprueba o reinstala Playwright. Evita duplicar el MCP.
   Para las herramientas de escritorio y TikTok **usa stdio local**,
   nunca una URL HTTP expuesta.

7. Reinicia la conexión MCP de Cline y comprueba la presencia de `tiktok_browser_status`, `tiktok_open_manual_login`, `tiktok_publish_chapter`, `tiktok_get_publication` y `flow_detect_window`. El MCP de TikTok no debe aparecer en un endpoint HTTP público.

## Inicio de sesión y trabajo

- **UserFlex / Flow:** abre UserFlex, selecciona Flow, inicia sesión tú mismo y completa el 2FA. Ejecuta el diagnóstico de `docs/FLOW_AUTOMATION.md` para determinar si UIA puede controlar esa ventana. No se inventarán selectores ni se habilitará depuración prohibida.
- **TikTok:** desde Cline ejecuta `tiktok_open_manual_login`; se abrirá Google Chrome con **perfil privado de Fruticap**. Inicia sesión tú mismo. Al cerrar/abrir Cline, puede ser necesario volver a abrir el navegador; el perfil persistirá en la carpeta de datos de Fruticap, a menos que TikTok caduque la sesión.
- **Publicación:** genera un capítulo y su montaje MP4 con las funciones existentes de Fruticap. Solo cuando el montaje haya terminado, solicita `tiktok_publish_chapter(request_id, render_id, caption, authorized=true)`. Los IDs deben ser UUID auténticos. El contenido se envía únicamente tras tu orden expresa. El módulo **no** tiene acceso a archivos arbitrarios de Windows.
- **Comprobación:** `tiktok_get_publication(request_id)` y `tiktok_browser_status`. `published` significa que se observó aviso de publicación; `unknown` significa que pudo publicarse pero no se confirmó: **no repetir sin revisar TikTok manualmente**.
- **Reconciliación:** `tiktok_confirm_not_published(request_id, confirmed_not_published=true)` únicamente cuando compruebes que el video NO se publicó. El registro previo se conserva.
- No se suministra API oficial de TikTok; se utiliza solamente su interfaz visible. Los cambios futuros en TikTok podrían romper selectores y necesitar mantenimiento.

## Pruebas de aceptación pendientes (hacer cuando estés en casa)

- [ ] Windows gráfico disponible en la VM y virtualización habilitada; CPU/RAM sin saturación.
- [ ] Cline llama al MCP local, Qwen responde desde Colab sin usar GPU local.
- [ ] Diagnóstico UserFlex detecta la ventana de Flow, sin F12 ni cookies.
- [ ] El perfil de controles de UserFlex está verificado; probar una escena **asistida** y descarga antes de intentar automatizar toda la cola.
- [ ] Chrome de TikTok inicia sesión manualmente con la cuenta correcta.
- [ ] En una cuenta de prueba, probar una subida autorizada y comprobar el aviso de publicación.
- [ ] Reiniciar y comprobar que no se duplica ninguna subida `posting` o `unknown`.
- [ ] Verificar que una sesión de Google o TikTok caducada exige intervención manual.
- [ ] Revisar consumo de VM, tamaño de almacenamiento y condiciones de uso de UserFlex.

El código y los tests de GitHub son **pruebas de software**, no prueba de compatibilidad real de UserFlex, Google Flow o TikTok.
