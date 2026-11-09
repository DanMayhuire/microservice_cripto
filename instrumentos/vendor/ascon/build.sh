#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    printf 'Uso: %s RUTA_DE_LA_BIBLIOTECA\n' "$0" >&2
    exit 2
fi

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$(uname -s)" in
    Darwin) library_flag=-dynamiclib ;;
    Linux) library_flag=-shared ;;
    *) printf 'El sistema requiere configurar un compilador compatible.\n' >&2; exit 2 ;;
esac

"${CC:-cc}" -std=c99 -O2 -fPIC "$library_flag" "$source_dir/aead.c" -o "$1"
