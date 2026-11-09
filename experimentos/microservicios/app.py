import hashlib
import json
import os
import secrets
import time
import urllib.request

from flask import Flask, jsonify, render_template, request

from aead import AAD, NONCE_SIZE, TAG_SIZE, make_cipher

ALGORITHM = os.environ["S05_ALGORITHM"]
KEY = bytes.fromhex(os.environ["S05_KEY_HEX"])
RECEIVER_URL = os.environ.get("S05_RECEIVER_URL", "http://receptor:8081")
NONCE_BYTES = NONCE_SIZE[ALGORITHM]
MAX_PAYLOAD_BYTES = 65536
cipher = make_cipher(ALGORITHM, KEY)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * MAX_PAYLOAD_BYTES


@app.get("/")
def laboratory():
    return render_template("index.html")


@app.get("/salud")
def health():
    return jsonify(ready=True, service="emisor", algorithm=ALGORITHM)


@app.post("/enviar")
def send_message():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="json_invalido"), 400
    payload_hex = data.get("payload_hex")
    if payload_hex is not None:
        if not isinstance(payload_hex, str):
            return jsonify(error="payload_hex_invalido"), 400
        try:
            payload = bytes.fromhex(payload_hex)
        except ValueError:
            return jsonify(error="payload_hex_invalido"), 400
        if len(payload) > MAX_PAYLOAD_BYTES:
            return jsonify(error="payload_bytes_invalido"), 400
    else:
        size = data.get("payload_bytes", 64)
        if type(size) is not int or not 0 <= size <= MAX_PAYLOAD_BYTES:
            return jsonify(error="payload_bytes_invalido"), 400
        payload = bytes(size)

    digest = hashlib.sha256(payload).hexdigest()
    nonce = secrets.token_bytes(NONCE_BYTES)
    started = time.perf_counter_ns()
    frame = nonce + cipher.encrypt(nonce, payload, AAD)
    encrypt_ns = time.perf_counter_ns() - started
    request_data = urllib.request.Request(
        RECEIVER_URL + "/mensaje", data=frame,
        headers={"Content-Type": "application/octet-stream"}, method="POST")
    try:
        with urllib.request.urlopen(request_data, timeout=5) as response:
            result = json.load(response)
    except (OSError, ValueError) as error:
        return jsonify(error=type(error).__name__), 502
    if (
        not isinstance(result, dict)
        or result.get("plaintext_bytes") != len(payload)
        or result.get("sha256") != digest
    ):
        return jsonify(error="respuesta_inconsistente"), 502
    elapsed_ns = time.perf_counter_ns() - started
    return jsonify({"algorithm": ALGORITHM, "payload_bytes": len(payload),
                    "sha256": digest,
                    "encrypt_ns": encrypt_ns, "elapsed_ns": elapsed_ns,
                    "receiver": result})


@app.get("/metricas")
def metrics():
    return jsonify(algorithm=ALGORITHM, key_bytes=len(KEY), tag_bytes=TAG_SIZE if NONCE_BYTES else 0)
