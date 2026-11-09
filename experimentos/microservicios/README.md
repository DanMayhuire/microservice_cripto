# Microservicios del experimento

El emisor Flask construye un mensaje de prueba, lo protege según la condición elegida y lo envía al receptor por HTTP. El receptor usa el [instrumento de S05](../../instrumentos/receptor.py) y devuelve la longitud, el SHA-256 y el tiempo de descifrado. El emisor comprueba la longitud y el SHA-256 antes de reportar éxito. Ambos servicios usan Gunicorn. La imagen compila Ascon desde el [código C de referencia fijado](../../instrumentos/vendor/ascon/README.md).

## Laboratorio en el navegador

Desde la raíz del repositorio, elige un modo y genera la clave de prueba para ambos servicios.

```sh
cd experimentos/microservicios
export S05_ALGORITHM=aes-128-gcm
case "$S05_ALGORITHM" in
  aes-128-gcm|ascon-aead128) export S05_KEY_HEX="$(openssl rand -hex 16)" ;;
  chacha20-poly1305) export S05_KEY_HEX="$(openssl rand -hex 32)" ;;
  sin-cifrado) export S05_KEY_HEX="" ;;
esac
docker compose up -d --build --wait
curl http://localhost:8080/salud
```

Abre [el laboratorio en `localhost:8080`](http://localhost:8080/). Puedes enviar un texto o generar un mensaje por tamaño. Cada envío ejecuta el intercambio HTTP entre los dos contenedores. La interfaz muestra los tiempos medidos por los servicios, los bytes recibidos y la huella SHA-256 con la que el emisor verifica la respuesta.

La interfaz muestra la condición activa, que se configura con `S05_ALGORITHM` en Compose. Para cambiarla, repite el bloque de arranque con el nuevo valor. Para detener ambos servicios, ejecuta `docker compose down` en la misma terminal.

## Prueba desde la terminal

El emisor publica `POST /enviar` en el puerto local 8080. Acepta un tamaño en `payload_bytes` o un mensaje en `payload_hex`, de hasta 65 536 bytes una vez decodificado. El receptor atiende `POST /mensaje` en la red interna de Compose.

```sh
curl -X POST http://localhost:8080/enviar \
  -H 'Content-Type: application/json' \
  -d '{"payload_bytes":64}'
```

## Piloto reproducible en Docker

Con Docker Engine local activo, acceso a su socket Unix, Docker Compose y Python 3.9 o superior, ejecuta desde la raíz del repositorio.

```sh
python3 experimentos/microservicios/piloto_contenedores.py experimentos/s05_piloto_contenedores
```

El piloto levanta su propio proyecto de Compose y lo detiene al terminar. Por defecto ejecuta 32 corridas. Cruza las cuatro condiciones, tamaños de 64 y 4096 bytes y concurrencias de 1 y 4, con dos réplicas por celda y semilla 504. Reinicia ambos servicios para cada corrida, usa payloads de bytes cero generados por el emisor y separa 1 s de calentamiento de 3 s de admisión de solicitudes. El tiempo registrado de la ventana incluye el drenaje de solicitudes. Para comprobar el montaje con una sola corrida puedes usar lo siguiente.

```sh
python3 experimentos/microservicios/piloto_contenedores.py /tmp/s05-contenedores-smoke \
  --modes aes-128-gcm --sizes 64 --concurrency 1 --replicates 1 --warmup 0.3 --seconds 1
```

| Archivo | Evidencia |
|---|---|
| `corridas.csv` | Una fila por corrida, con parámetros de carga, conteos, latencias y throughput válido. |
| `solicitudes.csv` | Estado por solicitud y tiempos del cliente de carga, del emisor y del receptor. |
| `recursos.csv` | Tiempo de CPU acumulado en nanosegundos y memoria del cgroup en bytes, separados por contenedor. |
| `manifiesto.json` | Parámetros y argumentos para repetir la ejecución, semilla, orden, entorno, imágenes y huellas de integridad de las fuentes y los CSV. |

Para repetir una ejecución, usa el mismo código y los argumentos de `replay_args` con una carpeta de salida nueva. Comprueba que el orden y las condiciones coincidan en los manifiestos. Conserva cada manifiesto con sus CSV y registra el hardware y los recursos asignados a Ubuntu al comparar resultados. Las métricas de cgroups describen los contenedores.
