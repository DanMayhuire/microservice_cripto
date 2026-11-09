ARG PYTHON_BASE=python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
FROM ${PYTHON_BASE} AS ascon
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY instrumentos/vendor/ascon/ /src/ascon/
RUN sh /src/ascon/build.sh /tmp/libascon.so

FROM ${PYTHON_BASE}
WORKDIR /app
ENV PYTHONPATH=/app/instrumentos S05_ASCON_LIB=/usr/local/lib/libascon.so
COPY instrumentos/requirements-s05.txt .
RUN pip install --no-cache-dir -r requirements-s05.txt
COPY --from=ascon /tmp/libascon.so /usr/local/lib/libascon.so
COPY experimentos/microservicios/app.py .
COPY experimentos/microservicios/templates/index.html templates/
COPY experimentos/microservicios/static/ static/
COPY instrumentos/aead.py instrumentos/receptor.py /app/instrumentos/
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "4", "--threads", "8", "app:app"]
