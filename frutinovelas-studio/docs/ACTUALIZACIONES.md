# Actualizar el programa sin descartar cambios

`iniciar.cmd` comprueba GitHub al abrir el programa. Solo descarga la rama `main`
publicada de `mateoperez08251-crypto/fruti.cap` y avanza mediante **fast-forward**:
no crea fusiones, no reescribe commits y nunca ejecuta `reset`, `clean` ni `stash`.
Una PR pendiente no se instala hasta que esté integrada en `main`.

La automatización se ejecuta en tu equipo **al abrir el programa**. No es una tarea
nocturna ni un proceso permanente; una conversación en la nube no ejecuta comandos
en tu PC. Una copia antigua necesita descargar esta mejora una primera vez.

## Primera actualización en Windows

1. Termina las generaciones y cierra las terminales de Studio y su MCP.
2. Abre CMD en la carpeta del repositorio y ejecuta `git status --short` y
   `git branch --show-current`. Se requiere `main` y ningún archivo pendiente.
3. Si está limpio y las mejoras ya están en `main`, ejecuta `git pull --ff-only origin main`.
   Si falla o aparecen cambios locales, revísalos antes de continuar; no fuerces ni borres archivos.
4. Abre `frutinovelas-studio\iniciar.cmd`. Las próximas aperturas comprobarán la actualización.

No basta con actualizar el repositorio: el proceso que ya estaba ejecutándose conserva
el código anterior hasta reiniciarlo. Inicia el MCP de nuevo después de actualizar Studio.

## Actualizar solo el código

Dentro de `frutinovelas-studio`, ejecuta:

```cmd
actualizar.cmd
```

También funciona `py -3 scripts\safe_update.py`; en Linux/macOS, `python3 scripts/safe_update.py`.
Este comando no instala dependencias, no inicia servidores ni envía generaciones.

## Cuándo se detiene

- La rama no es `main`, el checkout está separado de una rama, o `origin` apunta a otro repositorio.
- Hay cambios guardados en el índice, modificaciones o archivos nuevos sin seguimiento.
- Hay una operación Git, un bloqueo u otra actualización en curso.
- Hay commits locales o divergencia que impide avanzar por fast-forward.
- Se detecta un servidor escuchando en los puertos locales de API/MCP (8765/8766 por defecto).
- No hay conexión o permisos para descargar de GitHub, o Git supera su límite de tiempo.
- Un archivo nuevo del remoto chocaría con un archivo local ignorado por Git.

Se comprueban también `FRUTINOVELAS_API_PORT`, `FRUTINOVELAS_MCP_PORT`,
`FRUTINOVELAS_API_HOST` y `FRUTINOVELAS_MCP_HOST` en el entorno y en `.env`, sin
mostrar credenciales. La detección cubre loopback IPv4/IPv6 y las interfaces configuradas;
no identifica MCP por stdio ni servidores iniciados manualmente en otro puerto/interfaz.
Cierra esos procesos antes de actualizar. No se mata ningún proceso.

Las operaciones locales de Git tienen un límite de 15 segundos; descarga y avance,
45 segundos cada uno. Si se interrumpe una operación, revisa `git status` antes de
reintentar. Un bloqueo `fruti-update.lock` abandonado por un cierre forzado requiere
comprobar que no queda un actualizador vivo antes de retirarlo manualmente.

Los errores detienen el arranque antes de instalar dependencias. No se imprimen
las URLs configuradas ni la salida de error de Git, que podría incluir credenciales.
Git conserva su autenticación habitual; no se piden tokens en scripts ni se guardan en el repositorio.

## Desactivar la comprobación automática

Para abrir el código local sin consultar GitHub, en CMD:

```cmd
set FRUTINOVELAS_AUTO_UPDATE=0
iniciar.cmd
```

Esto solo afecta a esa terminal. Para conservarlo en futuras terminales:

```cmd
setx FRUTINOVELAS_AUTO_UPDATE 0
```

Abre una terminal nueva tras `setx`. Para reactivarlo usa `setx FRUTINOVELAS_AUTO_UPDATE 1`.
El comando explícito `actualizar.cmd` sigue comprobando Git aunque la comprobación al inicio esté desactivada.

## Dependencias y datos

Tras una actualización válida, `iniciar.cmd` carga el launcher recién descargado,
comprueba una versión de Node.js compatible con el lockfile (24 LTS recomendado;
también 22.13+ de la rama 22 o versiones >=26, excluyendo 23 y 25), sincroniza Python
con `uv sync --frozen`, ejecuta
`npm ci` para respetar el lockfile y compila la interfaz antes de arrancar la API.
Si falla una etapa, no inicia la aplicación. Las instalaciones y el build tienen un
límite de diez minutos por comando. Este proceso necesita acceso a los registros
de paquetes, incluso si se ha desactivado la comprobación automática de Git.

El actualizador no modifica la configuración ni los datos privados ignorados por Git.
Los proyectos y medios del directorio de datos del usuario permanecen fuera del checkout;
la API aplica sus migraciones habituales al arrancar. Conserva una copia de seguridad
del directorio de datos antes de cambios mayores de versión.

## Verificación

`tests/test_update.py` utiliza repositorios Git locales y cubre fast-forward,
conservación de cambios y archivos ignorados, ramas incorrectas, divergencias,
fallos de conexión, concurrencia, puertos activos y fallos de compilación. No necesita
GitHub ni ejecuta instalaciones, servidores o generaciones reales.
