# Ascon-AEAD128 de referencia

Implementación oficial en C del proyecto [ascon/ascon-c](https://github.com/ascon/ascon-c/tree/446347f21b209f3921c65ece70027c366cbe1693),
fijada en el commit `446347f21b209f3921c65ece70027c366cbe1693`.
Se incluye bajo [CC0 1.0](LICENSE).

- `aead.c` y sus cabeceras provienen de [`crypto_aead/asconaead128/ref/`](https://github.com/ascon/ascon-c/tree/446347f21b209f3921c65ece70027c366cbe1693/crypto_aead/asconaead128/ref).
- `crypto_aead.h` proviene de [`tests/crypto_aead.h`](https://github.com/ascon/ascon-c/blob/446347f21b209f3921c65ece70027c366cbe1693/tests/crypto_aead.h).
- `LWC_AEAD_KAT_128_128.txt` conserva 25 registros completos de los [vectores originales](https://github.com/ascon/ascon-c/blob/446347f21b209f3921c65ece70027c366cbe1693/crypto_aead/asconaead128/LWC_AEAD_KAT_128_128.txt).
  Se seleccionaron los registros 1–5, 34–38, 529–533, 544–548 y 562–566 para cubrir mensajes vacíos y datos asociados de distintas longitudes, incluidos límites de bloque.
  Los números de registro se conservan para facilitar la verificación.

El script de compilación usa la variante de referencia con `-O2` y sin trazas internas. El binario exporta `crypto_aead_encrypt` y `crypto_aead_decrypt`.

```sh
# Linux
sh instrumentos/vendor/ascon/build.sh /tmp/libascon.so
# macOS
sh instrumentos/vendor/ascon/build.sh /tmp/libascon.dylib
```
