#!/bin/sh
set -eu

raiz=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
S05_ALGORITHM=${S05_ALGORITHM:-aes-128-gcm}
case "$S05_ALGORITHM" in
  aes-128-gcm|ascon-aead128) S05_KEY_HEX=$(openssl rand -hex 16) ;;
  chacha20-poly1305) S05_KEY_HEX=$(openssl rand -hex 32) ;;
  sin-cifrado) S05_KEY_HEX='' ;;
  *) printf 'Modo inválido: %s\n' "$S05_ALGORITHM" >&2; exit 2 ;;
esac
export S05_ALGORITHM S05_KEY_HEX
S05_HOST_PORT=${S05_HOST_PORT:-8080}
export S05_HOST_PORT

docker compose -f "$raiz/experimentos/microservicios/docker-compose.yml" up -d --build --wait
printf 'Abre http://localhost:%s/\n' "$S05_HOST_PORT"
