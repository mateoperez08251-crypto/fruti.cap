# Google Flow con el navegador de My Content

El puente `scripts/flow_mycontent_browser.py` carga únicamente
`bot/navegador.py` del repositorio My Content. Reutiliza su apertura de navegador
y su gestión de perfiles para iniciar sesión manualmente en Google Flow.
No importa el motor de publicaciones, cuentas, colas ni cookies de My Content.

Usa el Python existente del bot y el Chromium ya instalado. No requiere VM ni
una descarga adicional de navegador. El perfil nuevo queda en la carpeta de
datos de Studio, dentro de `flow/google_browser/profile`, fuera de Git.

En Windows abre `conectar_flow_navegador.cmd`. Detecta My Content junto al
repositorio Fruticap; para otra ubicación define `FRUTINOVELAS_MY_CONTENT_DIR`.
El selector de Python de My Content conserva su comportamiento y omite entornos
rotos. La conexión se puede comprobar sin abrir ventanas:

```powershell
& 'RUTA_AL_PYTHON_DEL_BOT' scripts/flow_mycontent_browser.py --source 'RUTA_A_MY_CONTENT' --check
```

El acceso oficial consultado redirige a [Google Flow](https://flow.google.com/).
El inicio de sesión lo realiza el usuario en una ventana normal de Chromium.
Después cierra esa ventana para liberar su perfil y permitir la siguiente apertura
controlada. No se exportan contraseñas, cookies ni códigos de acceso.

## Controles observados y comprobación

El 27 de octubre de 2026 se comprobó la sesión iniciada en un proyecto propio
de Flow. `flow_browser_controls.py` seleccionó y confirmó en el navegador real
imagen, formato vertical 9:16, una salida y Nano Banana 2.1, con el botón
Agente desactivado para conservar las instrucciones literales. No se pulsó
Iniciar generación.

Los controles observados dependen del tipo y modelo elegidos:

| Control | Imagen: Nano Banana 2.1 | Video: Omni 1.1 Flash |
| --- | --- | --- |
| Formato | 16:9, 4:3, 1:1, 3:4, 9:16 | 16:9, 9:16 |
| Salidas por envío | x1, x2, x3, x4 | x1, x2, x3, x4 |
| Duración | No aplica | 4, 6, 8 o 10 segundos |
| Resolución | No se observó un selector | 360p, 720p |
| Entrada de video | No aplica | Fotogramas, Ingredientes |

Son observaciones de esta cuenta y fecha. El adaptador comprueba los controles
visibles en cada ejecución; si falta una opción, se detiene. No redondea cinco
segundos a otra duración ni sustituye el modelo. Actualmente comprueba el modelo
visible; todavía no implementa cambiar de familia de modelos.

La cantidad x1–x4 significa resultados por envío, no número de reintentos.
La integración de reintentos y descarga de todas las alternativas sigue pendiente.
Un envío cuyo resultado se desconozca necesita reconciliarse antes de repetirlo.

Para repetir solo la comprobación de imagen, sin generar contenido:

```powershell
& 'RUTA_AL_PYTHON_DEL_BOT' scripts/flow_mycontent_browser.py --source 'RUTA_A_MY_CONTENT' --inspect-project --screen configure-image
```

Storyboard Studio está disponible en Plantillas. Se conserva la URL de su copia
en el proyecto para reutilizarla. Se comprobó la carga de su interfaz interna:
pasos Script, Assets y Storyboard; estilo Realistic; Add Character, Add Location
y Add Prop; bienvenida Get Started. Su textarea de asistencia tiene el placeholder
`Describe the story, edit scenes, update dialog...`. No se ha ejecutado ese asistente
ni la creación de assets. El editor exterior de la herramienta tiene otro cuadro
de texto que no equivale al campo de generación de la plantilla. La inspección
descarta el iframe oculto de compilación para no confundirlo con la aplicación.

**Alcance actual:** conexión y configuración comprobadas; la rutina específica
de generar y descargar imágenes sigue pendiente. `automation_ready` permanece
falso. El controlador de escritorio UserFLEX existente no se convierte
automáticamente en un controlador de pestaña.

Las 16 pruebas focalizadas cubren el puente, perfil separado, navegador existente,
estados de sesión, selección explícita, opciones inválidas y detención si el modelo
o duración no están disponibles. No prueban calidad generativa ni una descarga real.
