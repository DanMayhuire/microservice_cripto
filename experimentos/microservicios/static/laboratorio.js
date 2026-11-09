"use strict";

const labels = {
  "aes-128-gcm": "AES-128-GCM",
  "ascon-aead128": "Ascon-AEAD128",
  "chacha20-poly1305": "ChaCha20-Poly1305",
  "sin-cifrado": "Sin cifrado",
};
const maxBytes = 65536;
const historyKey = "upeu-laboratorio-aead-intercambios-v1";
const number = new Intl.NumberFormat("es-PE");
const time = new Intl.DateTimeFormat("es-PE", {
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});
const precision = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 3 });
const encoder = new TextEncoder();
const hex = Array.from({ length: 256 }, (_, byte) => byte.toString(16).padStart(2, "0"));
const byId = (id) => document.getElementById(id);
const form = byId("message-form");
const sizeInput = byId("payload-size");
const textInput = byId("payload-text");
const sendButton = byId("send-button");
const presets = [...form.querySelectorAll("[data-size]")];
const metrics = ["total", "encrypt", "decrypt", "size"].map((key) => byId(`metric-${key}`));
let activeMode = null;
let pending = false;
let history = loadHistory();

function loadHistory() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(historyKey) || "[]");
    return Array.isArray(saved) ? saved.filter((entry) =>
      entry && Number.isFinite(entry.at) && Number.isInteger(entry.bytes) &&
      (entry.ns === null || Number.isFinite(entry.ns)) &&
      Object.hasOwn(labels, entry.mode) &&
      ["verified", "error"].includes(entry.outcome)).slice(0, 8) : [];
  } catch {
    return [];
  }
}

function duration(ns) {
  if (ns === null) return "—";
  if (ns < 1000) return `${number.format(ns)} ns`;
  if (ns < 1000000) return `${precision.format(ns / 1000)} µs`;
  return `${precision.format(ns / 1000000)} ms`;
}

function renderHistory() {
  byId("history-count").textContent = `${history.length} ${history.length === 1 ? "prueba" : "pruebas"}`;
  byId("history-empty").hidden = history.length > 0;
  byId("history-scroll").hidden = history.length === 0;
  const rows = history.map((entry) => {
    const row = document.createElement("tr");
    for (const text of [
      time.format(entry.at),
      labels[entry.mode],
      `${number.format(entry.bytes)} B`,
      duration(entry.ns),
      entry.outcome === "verified" ? "Verificado" : "Falló",
    ]) {
      row.insertCell().textContent = text;
    }
    row.lastElementChild.dataset.outcome = entry.outcome;
    return row;
  });
  byId("history-rows").replaceChildren(...rows);
}

function record(entry) {
  history = [entry, ...history].slice(0, 8);
  try {
    sessionStorage.setItem(historyKey, JSON.stringify(history));
  } catch {
    // La tabla puede funcionar en memoria cuando el navegador bloquea el almacenamiento.
  }
  renderHistory();
}

function setConnection(state, text) {
  byId("connection").dataset.state = state;
  byId("connection-label").textContent = text;
}

async function checkConnection() {
  try {
    const response = await fetch("/salud", { cache: "no-store", signal: AbortSignal.timeout(5000) });
    const data = await response.json();
    if (!response.ok || !data.ready || !Object.hasOwn(labels, data.algorithm)) throw new Error();
    activeMode = data.algorithm;
    byId("active-algorithm").textContent = labels[activeMode];
    setConnection("ready", "Emisor disponible");
  } catch {
    byId("active-algorithm").textContent = "Sin confirmar";
    setConnection("error", "Emisor no disponible");
  }
}

function updatePresets() {
  for (const button of presets) {
    button.setAttribute("aria-pressed", String(Number(button.dataset.size) === sizeInput.valueAsNumber));
  }
}

function updateTextSize() {
  const bytes = encoder.encode(textInput.value).length;
  const help = byId("text-size");
  help.textContent = `${number.format(bytes)} / ${number.format(maxBytes)} bytes en UTF-8`;
  help.dataset.state = bytes > maxBytes ? "error" : "idle";
  textInput.setCustomValidity(bytes > maxBytes ? "El mensaje supera el límite de 65 536 bytes." : "");
}

function updateEntry() {
  const useText = form.elements.entry.value === "text";
  byId("size-fields").hidden = useText;
  byId("text-fields").hidden = !useText;
  sizeInput.disabled = useText;
  textInput.disabled = !useText;
}

function setResult(state, badge, message) {
  byId("result").setAttribute("aria-busy", String(state === "pending"));
  byId("result-badge").dataset.state = state;
  byId("result-badge").textContent = badge;
  byId("result-message").textContent = message;
  byId("route").dataset.state = state;
}

function checkResult(data, expectedBytes) {
  const received = data?.receiver;
  return Object.hasOwn(labels, data?.algorithm) &&
    data.payload_bytes === expectedBytes && received?.plaintext_bytes === expectedBytes &&
    /^[a-f0-9]{64}$/.test(data.sha256) && received.sha256 === data.sha256 &&
    [data.elapsed_ns, data.encrypt_ns, received.decrypt_ns].every((ns) => Number.isFinite(ns) && ns >= 0);
}

for (const button of presets) {
  button.addEventListener("click", () => {
    sizeInput.value = button.dataset.size;
    updatePresets();
  });
}
sizeInput.addEventListener("input", updatePresets);
textInput.addEventListener("input", updateTextSize);
form.addEventListener("change", (event) => {
  if (event.target.name === "entry") updateEntry();
});
byId("load-example").addEventListener("click", () => {
  textInput.value = JSON.stringify({ evento: "matricula.solicitada", referencia: "DEMO-004" }, null, 2);
  updateTextSize();
  textInput.focus();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (pending) return;

  const useText = form.elements.entry.value === "text";
  const textBytes = useText ? encoder.encode(textInput.value) : null;
  const bytes = textBytes?.length ?? sizeInput.valueAsNumber;
  const body = useText
    ? { payload_hex: Array.from(textBytes, (byte) => hex[byte]).join("") }
    : { payload_bytes: bytes };

  pending = true;
  sendButton.disabled = true;
  byId("send-label").textContent = "Enviando…";
  byId("digest").hidden = true;
  byId("digest").open = false;
  for (const metric of metrics) metric.textContent = "—";
  setResult("pending", "En curso", "Esperando la respuesta del receptor.");

  try {
    const response = await fetch("/enviar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(8000),
    });
    const data = await response.json();
    if (!response.ok) {
      if (data.error === "respuesta_inconsistente") throw new Error("La respuesta del receptor no coincide con el mensaje enviado.");
      if (response.status === 502) throw new Error("El receptor no respondió correctamente. Revisa el contenedor receptor e inténtalo otra vez.");
      throw new Error(`El emisor devolvió HTTP ${response.status}. Revisa el mensaje y vuelve a intentarlo.`);
    }
    if (!checkResult(data, bytes)) throw new Error("La respuesta no contiene una verificación válida.");

    activeMode = data.algorithm;
    byId("active-algorithm").textContent = labels[activeMode];
    setConnection("ready", "Emisor disponible");
    const baseline = activeMode === "sin-cifrado";
    metrics[0].textContent = duration(data.elapsed_ns);
    metrics[1].textContent = duration(baseline ? null : data.encrypt_ns);
    metrics[2].textContent = duration(baseline ? null : data.receiver.decrypt_ns);
    metrics[3].textContent = `${number.format(data.receiver.plaintext_bytes)} B`;
    byId("sender-digest").textContent = data.sha256;
    byId("receiver-digest").textContent = data.receiver.sha256;
    byId("digest").hidden = false;
    setResult("verified", "Verificado", baseline
      ? "El tamaño y las huellas coinciden. Esta prueba se ejecutó sin cifrado."
      : "El receptor recuperó el mensaje. El tamaño y las huellas coinciden.");
    record({ at: Date.now(), mode: activeMode, bytes, ns: data.elapsed_ns, outcome: "verified" });
  } catch (error) {
    let message = error.message;
    if (error.name === "TimeoutError") message = "Se agotó el tiempo de espera. Comprueba los contenedores y vuelve a intentar.";
    if (error instanceof TypeError) {
      message = "No se pudo conectar con el emisor. Comprueba que el contenedor esté activo.";
      setConnection("error", "Emisor no disponible");
    } else if (error instanceof SyntaxError) {
      message = "El emisor devolvió una respuesta inesperada. Revisa el servicio y vuelve a intentar.";
    }
    setResult("error", "Falló el envío", message);
    if (activeMode) record({ at: Date.now(), mode: activeMode, bytes, ns: null, outcome: "error" });
  } finally {
    pending = false;
    sendButton.disabled = false;
    byId("send-label").textContent = "Enviar mensaje";
  }
});

updateEntry();
updatePresets();
updateTextSize();
renderHistory();
sendButton.disabled = false;
void checkConnection();
