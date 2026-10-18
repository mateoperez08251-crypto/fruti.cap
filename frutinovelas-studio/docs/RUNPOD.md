# FRUTINOVELAS en RunPod (por comandos)

En RunPod todo se hace desde la **terminal del pod** (web terminal o SSH) con la herramienta `fruti`.
El programa del PC se conecta por el **proxy HTTPS de RunPod** al gateway con token.

```
PC: FRUTINOVELAS Studio ──HTTPS + token──▶ https://<POD_ID>-8189.proxy.runpod.net ──▶ gateway :8189 ──▶ ComfyUI 127.0.0.1:8188
```

## 0. En tu PC: preparar el kit

```powershell
cd D:\fruti.cap\frutinovelas-studio
uv run python scripts/build_remote_kit.py
```

Genera `dist\frutinovelas-kit.tar.gz` (≈60 KB): scripts, manifiesto de modelos, perfiles y tu flujo H3 sin cambios.
No lleva secretos ni modelos.

## 1. Secretos en RunPod (recomendado)

Consola de RunPod → **Secrets**:

| Secreto | Valor |
|---|---|
| `hf_token` | Token de lectura de Hugging Face |
| `fruti_gateway_token` | Token aleatorio de 32 caracteres o más |

Generar un token en PowerShell:

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 40 | ForEach-Object {[char]$_})
```

Si no lo defines, `fruti` genera uno y lo guarda en `/workspace/FRUTINOVELAS_data/secrets/`.

## 2. Crear el pod

| Ajuste | Valor |
|---|---|
| Plantilla | Oficial **Runpod PyTorch** reciente (CUDA 12.8 o superior) |
| GPU | Recomendado ≥ 80 GB de VRAM (H100, H200, A100 80 GB, RTX PRO 6000). Requisito real no verificado |
| Disco del contenedor | ≥ 40 GB |
| Disco de volumen (`/workspace`) | ≥ 80 GB solo H3 · ≥ 150 GB con Qwen · ≥ 200 GB con perfil BF16 |
| Expose HTTP Ports | **`8189`** (añade `8888` solo si también quieres Jupyter) |
| Expose TCP Ports | `22` si vas a entrar por SSH |
| Variables de entorno | `HF_TOKEN` = `{{ RUNPOD_SECRET_hf_token }}` |
| | `FRUTI_GATEWAY_TOKEN` = `{{ RUNPOD_SECRET_fruti_gateway_token }}` |

> [!CAUTION]
> **No expongas el puerto 8188.** ComfyUI no tiene contraseña: `fruti` lo deja en `127.0.0.1` y solo publica el
> gateway (8189), que exige token. `fruti start` comprueba desde Internet que sin token responde 401.

## 3. Subir el kit al pod

**Opción A · `runpodctl` (viene instalado en el pod):**

```powershell
# PC (descarga runpodctl para Windows desde https://github.com/runpod/runpodctl/releases)
runpodctl send dist\frutinovelas-kit.tar.gz
# → muestra un código, p. ej. 8338-galileo-collect-fidel
```

```bash
# Pod
cd /workspace
runpodctl receive 8338-galileo-collect-fidel
```

**Opción B · `scp`** (con TCP 22 expuesto y tu clave SSH en RunPod):

```powershell
scp -P <PUERTO> dist\frutinovelas-kit.tar.gz root@<IP>:/workspace/
```

**Opción C · `git clone`** si publicas el repositorio: `fruti_remote.py` funciona igual desde `frutinovelas-studio/`.

## 4. Instalar y arrancar (una sola orden)

```bash
cd /workspace
tar -xzf frutinovelas-kit.tar.gz
python3 frutinovelas-kit/scripts/fruti_remote.py setup
```

`setup` hace, en orden:
1. `doctor`: GPU, VRAM, RAM, disco.
2. `install`: ComfyUI fijado al commit `3541246`, dependencias, Chromium para la exportación y FFmpeg.
3. `models`: descarga ≈40 GB con revisiones fijadas y verifica tamaño y SHA-256.
4. `start`: arranca ComfyUI, **exporta tus flujos a API** (inicio+final y solo inicio), los valida contra el
   servidor real, levanta el gateway y comprueba el acceso público.

Al final imprime la URL y el comando para el PC. Opciones útiles:

```bash
fruti setup --qwen-t2i si              # añade Qwen-Image-2512 (texto a imagen)
fruti setup --qwen-edit fp8mixed       # añade Qwen-Image-Edit-2511
fruti setup --voces-personajes si     # añade H3 Ref2VA para muestras de voz reutilizables
fruti setup --perfil h3_quality_bf16_optional
fruti setup --acceso quick             # Cloudflare Quick Tunnel en vez del proxy de RunPod
fruti setup --sin-sha256               # solo tamaños (más rápido, menos seguro)
```

Las opciones se guardan: los siguientes `fruti start` las reutilizan.

### Añadir voces a una instalación existente

Primero reconstruye y vuelve a subir el kit actualizado (secciones 0 y 3).
Descomprímelo sobre `/workspace/frutinovelas-kit` y ejecuta:

```bash
fruti models --voces-personajes si
fruti start --voces-personajes si --reexportar
```

Se descarga el checkpoint Ref2VA INT8 verificado (20,97 GB adicionales); el encoder
y los VAEs del perfil H3 seleccionado se reutilizan. El kit publica
`H3_VOZ_PERSONAJES.api.json` y registra su SHA-256. En Studio vuelve a **Guardar y comprobar** la
conexión para leer esa identidad. Después guarda una muestra en cada personaje y
selecciona sus voces en la escena: los diálogos nuevos se escriben en el prompt.
Ver [Voces de personajes](AUDIO_Y_VOCES.md) para los límites y la conservación de
versiones. Descargar y validar el flujo no demuestra todavía la calidad de voz.

## 5. Órdenes del día a día

| Orden | Qué hace |
|---|---|
| `fruti status` | Procesos, URL pública, cola, uso de GPU y resultado de las pruebas |
| `fruti token --mostrar` | Muestra el token para pegarlo en el programa |
| `fruti token --regenerar` | Crea un token nuevo (después: `fruti start`) |
| `fruti test --modo i2va --segundos 5` | Prueba real H3 solo-inicio |
| `fruti test --modo ambos` | Prueba solo-inicio e inicio+final |
| `fruti test --modo ninguno --qwen` | Prueba Qwen-Image-2512 |
| `fruti logs comfyui -f` | Log en directo (`gateway`, `cloudflared` también) |
| `fruti start --reexportar` | Repite la exportación API |
| `fruti stop` | Detiene ComfyUI, gateway y túnel |
| `fruti doctor` | Diagnóstico |

Los servicios siguen funcionando aunque cierres la terminal o la sesión SSH.

## 6. Conectar desde el PC

```powershell
$env:FRUTI_COMFY_TOKEN = "PEGA_AQUI_EL_TOKEN"
uv run python scripts/check_colab_connection.py --url https://IDDELPOD-8189.proxy.runpod.net
Remove-Item Env:FRUTI_COMFY_TOKEN
```

Comprueba la conexión, que se rechaza sin token, la GPU, y descarga los flujos API verificando su SHA-256.
Después, en el programa: *Conexiones → ComfyUI* → URL + token → **Probar conexión** → **Importar flujo**.

Para traer al PC un vídeo de prueba: en el pod `runpodctl send /workspace/FRUTINOVELAS_data/tests/<archivo>.mp4`
y en el PC `runpodctl receive <código>`.

## 7. Detener, reanudar y costes

| Acción | Qué se conserva | Al volver |
|---|---|---|
| *Stop* del pod | Todo `/workspace`: modelos, ComfyUI, token, flujos, configuración | `python3 /workspace/frutinovelas-kit/scripts/fruti_remote.py start` (reinstala pip si hace falta y recrea el atajo `fruti`) |
| *Terminate* | Nada, salvo que uses volumen de red | Crear pod nuevo y repetir el paso 4 |

- Un pod detenido no cobra GPU, pero **el disco de volumen sigue cobrando**.
- La URL del proxy depende del ID del pod: se mantiene al reanudar el mismo pod y cambia con un pod nuevo.
- Con un **volumen de red** los modelos se conservan aunque borres el pod (mismo centro de datos).

> [!NOTE]
> Tras reanudar el pod, `start` detecta que faltan los paquetes pip (el disco del contenedor se borra),
> los reinstala solo y después arranca. Los modelos no se vuelven a descargar.

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| «no responde. Expose HTTP Ports…» | *Edit Pod* → añade `8189` a HTTP Ports. El pod se reinicia: ejecuta `start` |
| `RUNPOD_POD_ID no existe` | No estás en RunPod: `fruti start --acceso quick` |
| `fruti: command not found` | Pod reiniciado: usa la ruta completa `python3 /workspace/frutinovelas-kit/scripts/fruti_remote.py start` |
| Error de memoria en `fruti test` | GPU con más VRAM |
| Errores de validación en `start` | El ComfyUI no coincide con tu flujo; esos flujos no se publican. Revisa el detalle |
| 502 al descargar resultados grandes | Repite; el proxy corta peticiones que tardan más de ~100 s sin enviar datos |
| No aparecen `HF_TOKEN` / `FRUTI_GATEWAY_TOKEN` | Revisa la sintaxis `{{ RUNPOD_SECRET_nombre }}` y reinicia el pod |
