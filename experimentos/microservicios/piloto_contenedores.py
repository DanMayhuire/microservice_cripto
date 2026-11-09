"""Ejecuta un piloto HTTP contra los dos servicios reales de Docker Compose."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, ExitStack
import csv
from datetime import datetime, timezone
import hashlib
from http.client import HTTPConnection, HTTPException
from itertools import product
import json
import math
import os
from pathlib import Path
import platform
import random
import secrets
import socket
from statistics import median
import subprocess
import sys
from threading import Event, Thread
import time
from uuid import uuid4


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KEY_BYTES = {"ascon-aead128": 16, "aes-128-gcm": 16, "chacha20-poly1305": 32, "sin-cifrado": 0}
FIELDS = {
    "corridas": (
        "run_id", "implementation", "payload_bytes", "concurrency", "replicate",
        "started_utc", "window_s", "warmup_attempted", "warmup_ok", "attempted", "ok",
        "errors", "timeouts", "throughput_ok_s", "latency_p50_ms", "latency_p95_ms",
        "resource_samples", "resource_errors",
    ),
    "solicitudes": (
        "run_id", "request_id", "client_elapsed_ns", "emitter_elapsed_ns", "encrypt_ns",
        "decrypt_ns", "status", "http_status", "error",
    ),
    "recursos": (
        "run_id", "component", "container_id", "phase", "elapsed_s", "cpu_total_ns", "memory_bytes",
    ),
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def docker(*args, env=None, capture=True):
    return subprocess.run(
        ("docker", *args), env=env, check=True, text=True, capture_output=capture, timeout=300
    ).stdout


class DockerConnection(HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=3)
        self.path = path

    def connect(self):
        with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as sock:
            sock.settimeout(self.timeout)
            sock.connect(self.path)
            self.sock = sock.dup()


def engine_socket():
    host = os.environ.get("DOCKER_HOST")
    if not host or os.environ.get("DOCKER_CONTEXT"):
        host = docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}").strip()
    if not host.startswith("unix://"):
        raise RuntimeError("Usa un contexto de Docker local con socket Unix para capturar recursos.")
    return host.removeprefix("unix://")


def sample_resources(socket_path, containers, run_id, phase, started):
    rows = []
    for component, container_id in containers.items():
        with closing(DockerConnection(socket_path)) as connection:
            connection.request("GET", f"/containers/{container_id}/stats?stream=false&one-shot=true")
            with connection.getresponse() as response:
                if response.status != 200:
                    raise RuntimeError(f"Docker devolvió HTTP {response.status} al medir {component}.")
                sample = json.load(response)
        rows.append({
            "run_id": run_id,
            "component": component,
            "container_id": container_id,
            "phase": phase,
            "elapsed_s": time.monotonic() - started,
            "cpu_total_ns": sample["cpu_stats"]["cpu_usage"]["total_usage"],
            "memory_bytes": sample["memory_stats"]["usage"],
        })
    return rows


def request_payload(connection, body, algorithm, size, digest):
    started = time.perf_counter_ns()
    row = dict(emitter_elapsed_ns=None, encrypt_ns=None, decrypt_ns=None,
               status="error", http_status=None, error="")
    try:
        connection.request("POST", "/enviar", body=body, headers={"Content-Type": "application/json"})
        with connection.getresponse() as response:
            row["http_status"] = response.status
            raw = response.read()
        if row["http_status"] != 200:
            row["error"] = f"HTTP_{row['http_status']}"
        else:
            result = json.loads(raw)
            receiver = result["receiver"]
            times = [result["elapsed_ns"], result["encrypt_ns"], receiver["decrypt_ns"]]
            if (
                result["algorithm"] != algorithm
                or result["payload_bytes"] != size
                or receiver["plaintext_bytes"] != size
                or result["sha256"] != digest
                or receiver["sha256"] != digest
                or not all(type(value) is int and value >= 0 for value in times)
            ):
                raise ValueError("Respuesta incompatible con la condición probada")
            row.update(emitter_elapsed_ns=times[0], status="ok")
            if algorithm != "sin-cifrado":
                row.update(encrypt_ns=times[1], decrypt_ns=times[2])
    except TimeoutError:
        connection.close()
        row.update(status="timeout", error="TimeoutError")
    except (ValueError, KeyError, TypeError, OSError, HTTPException) as error:
        connection.close()
        row["error"] = type(error).__name__
    row["client_elapsed_ns"] = time.perf_counter_ns() - started
    return row


def drive(port, run_id, algorithm, size, concurrency, seconds):
    body = json.dumps({"payload_bytes": size}).encode("utf-8")
    digest = hashlib.sha256(bytes(size)).hexdigest()
    started = time.monotonic()
    deadline = started + seconds

    def lane(number):
        rows = []
        with closing(HTTPConnection("127.0.0.1", port, timeout=6)) as connection:
            request_id = number + 1
            while time.monotonic() < deadline:
                row = request_payload(connection, body, algorithm, size, digest)
                rows.append(dict(run_id=run_id, request_id=request_id, **row))
                request_id += concurrency
        return rows

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        rows = [row for lane_rows in executor.map(lane, range(concurrency)) for row in lane_rows]
    return sorted(rows, key=lambda row: row["request_id"]), time.monotonic() - started


def run_condition(compose, socket_path, run, args):
    run_id, algorithm = run["run_id"], run["implementation"]
    load = (run_id, algorithm, run["payload_bytes"], run["concurrency"])
    env = dict(os.environ, S05_ALGORITHM=algorithm, S05_KEY_HEX=secrets.token_hex(KEY_BYTES[algorithm]),
               S05_HOST_PORT="")
    compose("up", "-d", "--force-recreate", "--no-build", "--wait", "--wait-timeout", "45", env=env)
    port = int(compose("port", "emisor", "8080", env=env).strip().rsplit(":", 1)[1])
    containers = {service: compose("ps", "-q", service, env=env).strip()
                  for service in ("emisor", "receptor")}
    if not all(containers.values()):
        raise RuntimeError("Compose no devolvió los dos identificadores de contenedor.")

    warmup, _ = drive(port, *load, args.warmup)
    started = time.monotonic()
    resources = []
    sample_errors = []

    def sample(phase):
        try:
            resources.extend(sample_resources(socket_path, containers, run_id, phase, started))
        except (KeyError, OSError, HTTPException, RuntimeError, ValueError) as error:
            sample_errors.append({"run_id": run_id, "phase": phase, "type": type(error).__name__})

    stop = Event()

    def sample_periodically():
        while not stop.wait(args.sample_every):
            sample("during")

    sample("pre")
    sampler = Thread(target=sample_periodically, daemon=True)
    sampler.start()
    started_utc = utc_now()
    try:
        requests, window = drive(port, *load, args.seconds)
    finally:
        stop.set()
        sampler.join()
    sample("post")
    latencies = sorted(row["client_elapsed_ns"] / 1e6 for row in requests if row["status"] == "ok")
    count = len(latencies)
    summary = dict(
        run, started_utc=started_utc, window_s=window, warmup_attempted=len(warmup),
        warmup_ok=sum(row["status"] == "ok" for row in warmup), attempted=len(requests),
        ok=count, errors=sum(row["status"] == "error" for row in requests),
        timeouts=sum(row["status"] == "timeout" for row in requests),
        throughput_ok_s=count / window, latency_p50_ms=median(latencies) if count else None,
        latency_p95_ms=latencies[math.ceil(0.95 * count) - 1] if count else None,
        resource_samples=len(resources), resource_errors=len(sample_errors),
    )
    images = {service: docker("inspect", "--format", "{{.Image}}", container).strip()
              for service, container in containers.items()}
    return summary, requests, resources, sample_errors, images


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Directorio nuevo para los CSV y el manifiesto")
    parser.add_argument("--modes", nargs="+", choices=KEY_BYTES, default=list(KEY_BYTES))
    parser.add_argument("--sizes", nargs="+", type=int, default=[64, 4096])
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 4])
    parser.add_argument("--replicates", type=int, default=2)
    parser.add_argument("--warmup", type=float, default=1)
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--sample-every", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=504)
    args = parser.parse_args()
    if any(len(levels) != len(set(levels)) for levels in (args.modes, args.sizes, args.concurrency)):
        parser.error("Los niveles de cada factor deben ser distintos.")
    if not all(0 <= size <= 65536 for size in args.sizes):
        parser.error("Los tamaños deben estar entre 0 y 65 536 bytes.")
    if min(args.concurrency) < 1 or args.replicates < 1:
        parser.error("La concurrencia y las réplicas deben ser mayores que cero.")
    if not all(math.isfinite(n) and n > 0 for n in (args.warmup, args.seconds, args.sample_every)):
        parser.error("El calentamiento, la duración y el intervalo de muestreo deben ser positivos.")
    if args.output.exists():
        parser.error("El directorio de salida ya existe. Elige uno nuevo.")
    return args


def main():
    args = parse_args()
    matrix = list(product(args.modes, args.sizes, args.concurrency, range(1, args.replicates + 1)))
    random.Random(args.seed).shuffle(matrix)
    plan = [
        dict(run_id=f"D{i:03d}", implementation=mode, payload_bytes=size, concurrency=concurrency, replicate=replicate)
        for i, (mode, size, concurrency, replicate) in enumerate(matrix, 1)
    ]
    project = f"s05-piloto-{uuid4().hex[:10]}"
    base_env = dict(os.environ, S05_ALGORITHM="sin-cifrado", S05_KEY_HEX="", S05_HOST_PORT="")

    def compose(*parts, env=base_env):
        return docker("compose", "-p", project, "-f", str(HERE / "docker-compose.yml"),
                      *parts, env=env, capture=parts[0] in {"ps", "port"})

    sources = [
        HERE / name for name in (
            "piloto_contenedores.py", "docker-compose.yml", "Dockerfile", "Dockerfile.dockerignore", "app.py"
        )
    ]
    sources.extend(ROOT / "instrumentos" / name for name in ("requirements-s05.txt", "receptor.py", "aead.py"))
    sources.extend(sorted((ROOT / "instrumentos/vendor/ascon").iterdir()))
    sources.extend(sorted((HERE / "templates").rglob("*")))
    sources.extend(sorted((HERE / "static").rglob("*")))
    manifest = {
        "format": "s05-piloto-contenedores-v1",
        "status": "running",
        "started_utc": utc_now(),
        "project": project,
        "environment": {"host_platform": platform.platform(), "host_machine": platform.machine(),
                        "python": platform.python_version()},
        "design": {
            "modes": args.modes, "sizes_bytes": args.sizes, "concurrency": args.concurrency,
            "replicates": args.replicates, "seed": args.seed, "warmup_s": args.warmup,
            "measurement_admission_s": args.seconds,
            "sample_every_s": args.sample_every, "client_http_timeout_s": 6,
            "payload": "Bytes cero generados en el emisor por payload_bytes",
            "payload_sha256_by_size": {size: hashlib.sha256(bytes(size)).hexdigest() for size in args.sizes},
            "startup": "Recrear y esperar ambos servicios en cada corrida con una clave efímera compartida",
            "order": plan,
        },
        "replay_args": [
            "--modes", *args.modes, "--sizes", *map(str, args.sizes), "--concurrency", *map(str, args.concurrency),
            "--replicates", str(args.replicates), "--seed", str(args.seed), "--warmup", str(args.warmup),
            "--seconds", str(args.seconds), "--sample-every", str(args.sample_every),
        ],
        "timing": {
            "client_elapsed_ns": "POST /enviar desde el host hasta validar la respuesta",
            "emitter_elapsed_ns": "Tiempo reportado por el emisor, desde el cifrado hasta validar la respuesta interna",
            "window_s": "Desde la apertura hasta drenar las solicitudes admitidas en la ventana",
            "resources_elapsed_s": "Tiempo desde el comienzo del muestreo previo a la ventana",
            "resources": "Docker Engine one-shot. CPU acumulada en ns y memoria del cgroup en bytes, con caché; no RSS",
        },
        "sources_sha256": {str(path.relative_to(ROOT)): digest_file(path) for path in sources if path.is_file()},
        "completed_runs": [],
        "resource_sampling_errors": [],
    }
    if (ROOT / ".git").exists():
        try:
            revision = subprocess.run(
                ("git", "rev-parse", "HEAD"), cwd=ROOT, capture_output=True, text=True, check=True, timeout=5
            ).stdout.strip()
            manifest["git_head"] = revision
        except (OSError, subprocess.SubprocessError):
            pass
    args.output.mkdir(parents=True)
    failed = False
    try:
        with ExitStack() as stack:
            outputs = {}
            for name, fields in FIELDS.items():
                file = stack.enter_context((args.output / f"{name}.csv").open("w", newline="", encoding="utf-8"))
                writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                outputs[name] = (file, writer)
            socket_path = engine_socket()
            manifest["environment"]["docker_server"] = json.loads(docker("version", "--format", "{{json .Server}}"))
            manifest["environment"]["compose"] = docker("compose", "version", "--short").strip()
            manifest["environment"]["docker_resources"] = json.loads(docker(
                "info", "--format",
                '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}},"cgroup_version":{{json .CgroupVersion}},'
                '"operating_system":{{json .OperatingSystem}}}',
            ))
            compose("build")
            for run in plan:
                summary, requests, resources, errors, images = run_condition(compose, socket_path, run, args)
                for name, rows in zip(FIELDS, ([summary], requests, resources)):
                    file, writer = outputs[name]
                    writer.writerows(rows)
                    file.flush()
                manifest["completed_runs"].append(dict(run_id=run["run_id"], images=images))
                manifest["resource_sampling_errors"].extend(errors)
                failed |= bool(
                    errors or not summary["ok"] or summary["errors"] or summary["timeouts"]
                    or not summary["warmup_ok"] or summary["warmup_ok"] != summary["warmup_attempted"]
                )
                print(f"{run['run_id']} · {run['implementation']} · {summary['ok']}/{summary['attempted']} válidas", flush=True)
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyboardInterrupt) as error:
        failed = True
        manifest["interruption"] = type(error).__name__
        print(f"El piloto se interrumpió: {error or type(error).__name__}", file=sys.stderr)
    finally:
        try:
            compose("down", "--remove-orphans")
        except (OSError, subprocess.SubprocessError) as error:
            failed = True
            manifest["cleanup_error"] = type(error).__name__
            print(f"No se pudo detener el proyecto {project}.", file=sys.stderr)
        if "interruption" in manifest:
            manifest["status"] = "interrupted"
        else:
            manifest["status"] = "completed_with_incidents" if failed else "completed"
        manifest["finished_utc"] = utc_now()
        manifest["outputs_sha256"] = {path.name: digest_file(path) for path in sorted(args.output.glob("*.csv"))}
        (args.output / "manifiesto.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"Datos guardados en {args.output.resolve()}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
