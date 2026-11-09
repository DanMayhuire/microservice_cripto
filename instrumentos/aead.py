"""Adaptadores AEAD para el banco de pruebas local."""

import ctypes
import os
from functools import lru_cache
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

AAD = b"ppi-grupo-04/s05/v1"
TAG_SIZE = 16
KEY_SIZE = {
    "ascon-aead128": 16,
    "aes-128-gcm": 16,
    "chacha20-poly1305": 32,
    "sin-cifrado": 0,
}
NONCE_SIZE = {
    "ascon-aead128": 16,
    "aes-128-gcm": 12,
    "chacha20-poly1305": 12,
    "sin-cifrado": 0,
}


@lru_cache(maxsize=1)
def _ascon_library(path):
    library = ctypes.CDLL(path)
    source = ctypes.c_char_p
    target = ctypes.POINTER(ctypes.c_char)
    length = ctypes.c_ulonglong
    size_out = ctypes.POINTER(length)
    library.crypto_aead_encrypt.argtypes = [
        target, size_out, source, length, source, length, source, source, source,
    ]
    library.crypto_aead_decrypt.argtypes = [
        target, size_out, target, source, length, source, length, source, source,
    ]
    library.crypto_aead_encrypt.restype = ctypes.c_int
    library.crypto_aead_decrypt.restype = ctypes.c_int
    return library


class _Ascon:
    def __init__(self, key):
        self.key = key
        self.library = _ascon_library(str(Path(os.environ["S05_ASCON_LIB"]).resolve()))

    def encrypt(self, nonce, plaintext, aad):
        if len(nonce) != NONCE_SIZE["ascon-aead128"]:
            raise ValueError("Ascon-AEAD128 requiere un nonce de 16 bytes")
        expected = len(plaintext) + TAG_SIZE
        ciphertext = ctypes.create_string_buffer(expected)
        size = ctypes.c_ulonglong()
        code = self.library.crypto_aead_encrypt(
            ciphertext, ctypes.byref(size), plaintext, len(plaintext),
            aad, len(aad), None, nonce, self.key,
        )
        if code != 0 or size.value != expected:
            raise RuntimeError("ascon-c devolvió un cifrado inválido")
        return ciphertext.raw

    def decrypt(self, nonce, ciphertext, aad):
        if len(nonce) != NONCE_SIZE["ascon-aead128"]:
            raise ValueError("Ascon-AEAD128 requiere un nonce de 16 bytes")
        expected = len(ciphertext) - TAG_SIZE
        if expected < 0:
            raise InvalidTag
        # Se reserva un byte aun cuando el mensaje sea vacío.
        plaintext = ctypes.create_string_buffer(max(1, expected))
        size = ctypes.c_ulonglong()
        code = self.library.crypto_aead_decrypt(
            plaintext, ctypes.byref(size), None, ciphertext, len(ciphertext),
            aad, len(aad), nonce, self.key,
        )
        if code != 0:
            raise InvalidTag
        if size.value != expected:
            raise RuntimeError("ascon-c devolvió una longitud inválida")
        return plaintext.raw[:size.value]


class _Plaintext:
    def encrypt(self, nonce, plaintext, aad):
        return plaintext

    def decrypt(self, nonce, ciphertext, aad):
        return ciphertext


def make_cipher(algorithm, key):
    if len(key) != KEY_SIZE[algorithm]:
        raise ValueError(f"Longitud de clave inválida para {algorithm}")
    match algorithm:
        case "ascon-aead128":
            return _Ascon(key)
        case "aes-128-gcm":
            return AESGCM(key)
        case "chacha20-poly1305":
            return ChaCha20Poly1305(key)
        case "sin-cifrado":
            return _Plaintext()
