"""Servicio receptor del piloto. Ejecutar en la red aislada del benchmark."""

import hashlib
import os
import time

from cryptography.exceptions import InvalidTag
from flask import Flask, jsonify, request

from aead import AAD, NONCE_SIZE, TAG_SIZE, make_cipher

algorithm = os.environ["S05_ALGORITHM"]
cipher = make_cipher(algorithm, bytes.fromhex(os.environ["S05_KEY_HEX"]))
nonce_size = NONCE_SIZE[algorithm]
tag_size = TAG_SIZE if nonce_size else 0

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 65536 + nonce_size + tag_size


@app.get("/salud")
def health():
    return jsonify(ready=True)


@app.post("/mensaje")
def receive():
    frame = request.get_data(cache=False)
    if len(frame) < nonce_size + tag_size:
        return jsonify(error="mensaje_invalido"), 422
    nonce = frame[:nonce_size]
    ciphertext = frame[nonce_size:]
    started = time.perf_counter_ns()
    try:
        plaintext = cipher.decrypt(nonce, ciphertext, AAD)
    except InvalidTag:
        return jsonify(error="mensaje_invalido"), 422
    decrypt_ns = time.perf_counter_ns() - started
    return jsonify(
        plaintext_bytes=len(plaintext),
        sha256=hashlib.sha256(plaintext).hexdigest(),
        decrypt_ns=decrypt_ns,
    )
