"""Local GUI for editing tgwatch config."""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import webbrowser

from .config import (
    ConfigError,
    MAX_CONTROL_GROUPS,
    MAX_TARGET_GROUPS,
    MAX_USERS_PER_TARGET,
    load_config,
)

try:  # pragma: no cover - Python 3.11+ always hits first branch
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

logger = logging.getLogger(__name__)

KEEP_SECRET = "********"

_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>tgwatch GUI</title>
    <link rel="stylesheet" href="/app.css" />
  </head>
  <body>
    <div id="app"></div>
    <script src="/app.js"></script>
  </body>
</html>
"""

_CSS = """
:root {
  color-scheme: light;
  --bg: #f7f3ef;
  --panel: #ffffff;
  --ink: #1e1b16;
  --muted: #6b6158;
  --accent: #1b6f5a;
  --accent-2: #b4682d;
  --danger: #b83c3c;
  --border: #e4dcd2;
  --shadow: 0 20px 45px rgba(42, 32, 20, 0.12);
  --radius: 18px;
  --mono: "SF Mono", "JetBrains Mono", "Fira Code", monospace;
  --sans: "Avenir Next", "Avenir", "Helvetica Neue", "Segoe UI", sans-serif;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: var(--sans);
  background: radial-gradient(circle at 20% 20%, #fef7ef 0%, #f6efe7 40%, #efe6db 100%);
  color: var(--ink);
}

@keyframes rise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

#app {
  max-width: 1100px;
  margin: 48px auto 80px;
  padding: 0 24px;
}

.header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 32px;
  animation: rise 0.6s ease both;
}

.header h1 {
  font-size: 28px;
  margin: 0;
  letter-spacing: -0.02em;
}

.header p {
  margin: 4px 0 0;
  color: var(--muted);
}

.hero {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--accent);
  font-weight: 600;
}

.actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.button {
  background: var(--accent);
  color: #fff;
  border: none;
  padding: 12px 18px;
  border-radius: 999px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(27, 111, 90, 0.25);
}

.button.secondary {
  background: #fff;
  color: var(--accent);
  border: 1px solid var(--border);
  box-shadow: none;
}

.button.danger {
  background: var(--danger);
  color: #fff;
}

.button[disabled] {
  opacity: 0.5;
  cursor: not-allowed;
}

.section {
  background: var(--panel);
  border-radius: var(--radius);
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  animation: rise 0.6s ease both;
}

.section h2 {
  margin: 0 0 12px;
  font-size: 20px;
}

.section p {
  margin: 0 0 16px;
  color: var(--muted);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
}

.field input,
.field select {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  font-size: 14px;
}

.field small {
  color: var(--muted);
}

.card-list {
  display: grid;
  gap: 16px;
}

.card {
  border-radius: 16px;
  border: 1px solid var(--border);
  padding: 16px;
  background: #fffaf4;
}

.card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.card header h3 {
  margin: 0;
  font-size: 16px;
}

.inline-actions {
  display: flex;
  gap: 8px;
}

.list {
  display: grid;
  gap: 10px;
}

.list-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 8px;
  align-items: center;
}

.list-row input {
  width: 100%;
}

.list-row .button {
  padding: 8px 12px;
  font-size: 12px;
}

.notice {
  padding: 12px 14px;
  border-radius: 12px;
  background: #fef1e9;
  color: var(--accent-2);
  border: 1px dashed rgba(180, 104, 45, 0.3);
  margin-bottom: 16px;
}

.error {
  padding: 12px 14px;
  border-radius: 12px;
  background: #fdecea;
  color: var(--danger);
  border: 1px solid rgba(184, 60, 60, 0.2);
  margin-bottom: 16px;
}

.status {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--muted);
}

@media (max-width: 720px) {
  .list-row {
    grid-template-columns: 1fr;
  }
  .inline-actions {
    flex-direction: column;
    align-items: flex-start;
  }
}
"""

_JS = """
const state = { data: null, errors: [], status: "" };
const keepSecret = "********";

const limitText = (limits) => `Limits: ${limits.maxTargets} groups, ${limits.maxUsersPerTarget} users per group, ${limits.maxControlGroups} control groups.`;

const blankTarget = () => ({
  name: "",
  target_chat_id: "",
  summary_interval_minutes: "",
  control_group: "",
  tracked_users: [{ id: "", alias: "" }]
});

const blankControlGroup = () => ({
  key: "",
  control_chat_id: "",
  is_forum: false,
  topic_routing_enabled: false,
  topic_user_map: [{ user_id: "", topic_id: "" }]
});

function setByPath(obj, path, value) {
  const parts = path.split(".");
  let cursor = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    cursor = cursor[key];
  }
  cursor[parts[parts.length - 1]] = value;
}

function render() {
  const app = document.getElementById("app");
  if (!state.data) {
    app.innerHTML = `<div class="section"><h2>Loading...</h2></div>`;
    return;
  }
  const data = state.data;
  const limits = data.limits;
  const targets = data.targets;
  const controlGroups = data.control_groups;

  const errorBlock = state.errors.length
    ? `<div class="error"><strong>Validation issues</strong><ul>${state.errors.map(e => `<li>${e}</li>`).join("")}</ul></div>`
    : "";

  const statusBlock = state.status ? `<div class="notice">${state.status}</div>` : "";

  const controlOptions = controlGroups
    .map((group, idx) => `<option value="${group.key}">${group.key || `control-${idx + 1}`}</option>`)
    .join("");

  app.innerHTML = `
    <div class="header">
      <div class="hero">
        <span class="badge">Local Configurator</span>
        <h1>tgwatch GUI</h1>
        <p>Configure multi-group monitoring and control routing without editing files.</p>
        <div class="status">${limitText(limits)}</div>
      </div>
      <div class="actions">
        <button class="button" data-action="save">Save Config</button>
        <button class="button secondary" data-action="reload">Reload</button>
      </div>
    </div>
    ${statusBlock}
    ${errorBlock}

    <section class="section">
      <h2>Telegram Credentials</h2>
      <p>Local-only. API hash is masked and kept on disk.</p>
      <div class="grid">
        <div class="field">
          <label>API ID</label>
          <input data-field="telegram.api_id" value="${data.telegram.api_id}" placeholder="123456" />
        </div>
        <div class="field">
          <label>API Hash</label>
          <input type="password" data-field="telegram.api_hash" value="${data.telegram.api_hash}" placeholder="${keepSecret}" />
        </div>
        <div class="field">
          <label>Session File</label>
          <input data-field="telegram.session_file" value="${data.telegram.session_file}" placeholder="data/tgwatch.session" />
        </div>
      </div>
      <div class="field" style="margin-top:16px;">
        <label><input type="checkbox" data-field="sender.enabled" ${data.sender.enabled ? "checked" : ""}/> Enable sender account (optional)</label>
      </div>
      ${data.sender.enabled ? `
      <div class="grid" style="margin-top:12px;">
        <div class="field">
          <label>Sender Session File</label>
          <input data-field="sender.session_file" value="${data.sender.session_file}" placeholder="data/tgwatch_sender.session" />
        </div>
      </div>` : ""}
    </section>

    <section class="section">
      <h2>Targets</h2>
      <p>Each target represents one monitored group or channel.</p>
      <div class="card-list">
        ${targets.map((target, idx) => `
        <div class="card">
          <header>
            <h3>Group ${idx + 1}</h3>
            <div class="inline-actions">
              <button class="button secondary" data-action="add-user" data-target-index="${idx}" ${target.tracked_users.length >= limits.maxUsersPerTarget ? "disabled" : ""}>Add User</button>
              <button class="button danger" data-action="remove-target" data-target-index="${idx}">Remove Group</button>
            </div>
          </header>
          <div class="grid">
            <div class="field">
              <label>Name</label>
              <input data-field="targets.${idx}.name" value="${target.name}" placeholder="group-${idx + 1}" />
            </div>
            <div class="field">
              <label>Target Chat ID</label>
              <input data-field="targets.${idx}.target_chat_id" value="${target.target_chat_id}" placeholder="-100..." />
            </div>
            <div class="field">
              <label>Report Interval (min)</label>
              <input data-field="targets.${idx}.summary_interval_minutes" value="${target.summary_interval_minutes}" placeholder="optional" />
            </div>
            <div class="field">
              <label>Control Group</label>
              <select data-field="targets.${idx}.control_group">
                <option value="">${controlGroups.length === 1 ? "(default)" : "Select"}</option>
                ${controlOptions}
              </select>
            </div>
          </div>
          <div class="list" style="margin-top:16px;">
            ${target.tracked_users.map((user, uidx) => `
            <div class="list-row">
              <input data-field="targets.${idx}.tracked_users.${uidx}.id" value="${user.id}" placeholder="User ID" />
              <input data-field="targets.${idx}.tracked_users.${uidx}.alias" value="${user.alias}" placeholder="Alias (optional)" />
              <button class="button secondary" data-action="remove-user" data-target-index="${idx}" data-user-index="${uidx}">Remove</button>
            </div>`).join("")}
          </div>
        </div>`).join("")}
      </div>
      <div style="margin-top:16px;">
        <button class="button secondary" data-action="add-target" ${targets.length >= limits.maxTargets ? "disabled" : ""}>Add Group</button>
      </div>
    </section>

    <section class="section">
      <h2>Control Groups</h2>
      <p>Where summaries and commands are delivered.</p>
      <div class="card-list">
        ${controlGroups.map((group, idx) => `
        <div class="card">
          <header>
            <h3>Control ${idx + 1}</h3>
            <div class="inline-actions">
              <button class="button danger" data-action="remove-control" data-control-index="${idx}">Remove</button>
            </div>
          </header>
          <div class="grid">
            <div class="field">
              <label>Key</label>
              <input data-field="control_groups.${idx}.key" value="${group.key}" placeholder="main" />
            </div>
            <div class="field">
              <label>Control Chat ID</label>
              <input data-field="control_groups.${idx}.control_chat_id" value="${group.control_chat_id}" placeholder="-100..." />
            </div>
            <div class="field">
              <label>Forum Mode</label>
              <select data-field="control_groups.${idx}.is_forum">
                <option value="false" ${group.is_forum ? "" : "selected"}>false</option>
                <option value="true" ${group.is_forum ? "selected" : ""}>true</option>
              </select>
            </div>
            <div class="field">
              <label>Topic Routing</label>
              <select data-field="control_groups.${idx}.topic_routing_enabled">
                <option value="false" ${group.topic_routing_enabled ? "" : "selected"}>false</option>
                <option value="true" ${group.topic_routing_enabled ? "selected" : ""}>true</option>
              </select>
            </div>
          </div>
          ${group.topic_routing_enabled ? `
          <div class="list" style="margin-top:16px;">
            ${group.topic_user_map.map((entry, eidx) => `
            <div class="list-row">
              <input data-field="control_groups.${idx}.topic_user_map.${eidx}.user_id" value="${entry.user_id}" placeholder="User ID" />
              <input data-field="control_groups.${idx}.topic_user_map.${eidx}.topic_id" value="${entry.topic_id}" placeholder="Topic ID" />
              <button class="button secondary" data-action="remove-topic" data-control-index="${idx}" data-topic-index="${eidx}">Remove</button>
            </div>`).join("")}
          </div>
          <div style="margin-top:12px;">
            <button class="button secondary" data-action="add-topic" data-control-index="${idx}">Add Topic Mapping</button>
          </div>` : ""}
        </div>`).join("")}
      </div>
      <div style="margin-top:16px;">
        <button class="button secondary" data-action="add-control" ${controlGroups.length >= limits.maxControlGroups ? "disabled" : ""}>Add Control Group</button>
      </div>
    </section>

    <section class="section">
      <h2>Storage & Reporting</h2>
      <div class="grid">
        <div class="field">
          <label>DB Path</label>
          <input data-field="storage.db_path" value="${data.storage.db_path}" />
        </div>
        <div class="field">
          <label>Media Dir</label>
          <input data-field="storage.media_dir" value="${data.storage.media_dir}" />
        </div>
        <div class="field">
          <label>Reports Dir</label>
          <input data-field="reporting.reports_dir" value="${data.reporting.reports_dir}" />
        </div>
        <div class="field">
          <label>Default Summary Interval</label>
          <input data-field="reporting.summary_interval_minutes" value="${data.reporting.summary_interval_minutes}" />
        </div>
        <div class="field">
          <label>Timezone</label>
          <input data-field="reporting.timezone" value="${data.reporting.timezone}" />
        </div>
        <div class="field">
          <label>Retention Days</label>
          <input data-field="reporting.retention_days" value="${data.reporting.retention_days}" />
        </div>
      </div>
    </section>

    <section class="section">
      <h2>Display & Notifications</h2>
      <div class="grid">
        <div class="field">
          <label>Show IDs</label>
          <select data-field="display.show_ids">
            <option value="true" ${data.display.show_ids ? "selected" : ""}>true</option>
            <option value="false" ${data.display.show_ids ? "" : "selected"}>false</option>
          </select>
        </div>
        <div class="field">
          <label>Time Format</label>
          <input data-field="display.time_format" value="${data.display.time_format}" />
        </div>
        <div class="field">
          <label>Bark Key</label>
          <input data-field="notifications.bark_key" value="${data.notifications.bark_key}" placeholder="optional" />
        </div>
      </div>
    </section>
  `;

  document.querySelectorAll("select[data-field]").forEach((select) => {
    const field = select.dataset.field;
    const value = getByPath(state.data, field);
    select.value = String(value);
  });
}

function getByPath(obj, path) {
  return path.split(".").reduce((acc, key) => acc[key], obj);
}

function bindEvents() {
  document.addEventListener("input", (event) => {
    const target = event.target;
    if (!target.dataset.field) return;
    const field = target.dataset.field;
    let value = target.type === "checkbox" ? target.checked : target.value;
    if (target.tagName === "SELECT") {
      value = target.value === "true" ? true : target.value === "false" ? false : target.value;
    }
    setByPath(state.data, field, value);
  });

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!target.dataset.field) return;
    const field = target.dataset.field;
    if (
      field === "sender.enabled" ||
      field.endsWith(".key") ||
      field.endsWith(".topic_routing_enabled") ||
      field.endsWith(".is_forum")
    ) {
      render();
    }
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    const action = target.dataset.action;
    if (!action) return;

    if (action === "add-target") {
      state.data.targets.push(blankTarget());
      render();
      return;
    }
    if (action === "remove-target") {
      const index = Number(target.dataset.targetIndex);
      state.data.targets.splice(index, 1);
      render();
      return;
    }
    if (action === "add-user") {
      const index = Number(target.dataset.targetIndex);
      state.data.targets[index].tracked_users.push({ id: "", alias: "" });
      render();
      return;
    }
    if (action === "remove-user") {
      const tIndex = Number(target.dataset.targetIndex);
      const uIndex = Number(target.dataset.userIndex);
      state.data.targets[tIndex].tracked_users.splice(uIndex, 1);
      render();
      return;
    }
    if (action === "add-control") {
      state.data.control_groups.push(blankControlGroup());
      render();
      return;
    }
    if (action === "remove-control") {
      const index = Number(target.dataset.controlIndex);
      state.data.control_groups.splice(index, 1);
      render();
      return;
    }
    if (action === "add-topic") {
      const index = Number(target.dataset.controlIndex);
      state.data.control_groups[index].topic_user_map.push({ user_id: "", topic_id: "" });
      render();
      return;
    }
    if (action === "remove-topic") {
      const cIndex = Number(target.dataset.controlIndex);
      const tIndex = Number(target.dataset.topicIndex);
      state.data.control_groups[cIndex].topic_user_map.splice(tIndex, 1);
      render();
      return;
    }
    if (action === "save") {
      saveConfig();
      return;
    }
    if (action === "reload") {
      loadConfig();
    }
  });
}

async function loadConfig() {
  const res = await fetch("/api/config");
  const payload = await res.json();
  state.data = payload.data;
  state.errors = payload.errors || [];
  state.status = payload.status || "";
  render();
}

async function saveConfig() {
  const res = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.data)
  });
  const payload = await res.json();
  state.errors = payload.errors || [];
  state.status = payload.status || "";
  if (payload.data) {
    state.data = payload.data;
  }
  render();
}

bindEvents();
loadConfig();
"""


def run_gui(config_path: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the local GUI server."""
    config_path = config_path.expanduser().resolve()
    server = _GuiServer((host, port), _GuiHandler, config_path=config_path)
    url = f"http://{host}:{port}"
    logger.info("GUI running at %s", url)
    print(f"GUI running at {url}")
    print("Press Ctrl+C to stop.")
    try:
        webbrowser.open(url, new=2)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Failed to open browser: %s", exc)
    server.serve_forever()


class _GuiServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_cls, *, config_path: Path):
        super().__init__(server_address, handler_cls)
        self.config_path = config_path


class _GuiHandler(BaseHTTPRequestHandler):
    server_version = "tgwatch-gui/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send_response(HTTPStatus.OK, _HTML, "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self._send_response(HTTPStatus.OK, _CSS, "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._send_response(HTTPStatus.OK, _JS, "text/javascript; charset=utf-8")
            return
        if path == "/api/config":
            self._handle_get_config()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/config":
            self._handle_post_config()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        logger.info("GUI %s - %s", self.address_string(), format % args)

    def _handle_get_config(self) -> None:
        raw = _load_raw_config(self.server.config_path)
        data = _normalize_config(raw)
        errors = []
        if self.server.config_path.exists():
            try:
                load_config(self.server.config_path)
            except ConfigError as exc:
                errors.append(str(exc))
        payload = {
            "data": data,
            "errors": errors,
            "status": "",
        }
        self._send_json(HTTPStatus.OK, payload)

    def _handle_post_config(self) -> None:
        try:
            payload = self._read_json()
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"errors": ["Invalid JSON"]})
            return
        raw_existing = _load_raw_config(self.server.config_path)
        errors, normalized = _validate_payload(payload, raw_existing)
        if errors:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"errors": errors, "data": _normalize_config(raw_existing)},
            )
            return
        toml_text = _render_toml(normalized, raw_existing)
        tmp_path = self.server.config_path.with_suffix(".tmp")
        tmp_path.write_text(toml_text, encoding="utf-8")
        try:
            load_config(tmp_path)
        except ConfigError as exc:
            tmp_path.unlink(missing_ok=True)
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"errors": [str(exc)], "data": _normalize_config(raw_existing)},
            )
            return
        tmp_path.replace(self.server.config_path)
        data = _normalize_config(_load_raw_config(self.server.config_path))
        self._send_json(HTTPStatus.OK, {"errors": [], "status": "Saved.", "data": data})

    def _send_response(self, status: HTTPStatus, body: str, content_type: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))


def _load_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    telegram = raw.get("telegram", {})
    sender_raw = raw.get("sender", {}) if isinstance(raw.get("sender"), dict) else {}
    reporting = raw.get("reporting", {})
    storage = raw.get("storage", {})
    display = raw.get("display", {})
    notifications = raw.get("notifications", {})

    api_hash = telegram.get("api_hash")
    data = {
        "limits": {
            "maxTargets": MAX_TARGET_GROUPS,
            "maxUsersPerTarget": MAX_USERS_PER_TARGET,
            "maxControlGroups": MAX_CONTROL_GROUPS,
        },
        "telegram": {
            "api_id": telegram.get("api_id", ""),
            "api_hash": KEEP_SECRET if api_hash else "",
            "session_file": telegram.get("session_file", "data/tgwatch.session"),
        },
        "sender": {
            "enabled": bool(sender_raw),
            "session_file": sender_raw.get("session_file", "data/tgwatch_sender.session"),
        },
        "storage": {
            "db_path": storage.get("db_path", "data/tgwatch.sqlite3"),
            "media_dir": storage.get("media_dir", "data/media"),
        },
        "reporting": {
            "reports_dir": reporting.get("reports_dir", "reports"),
            "summary_interval_minutes": reporting.get("summary_interval_minutes", 120),
            "timezone": reporting.get("timezone", "UTC"),
            "retention_days": reporting.get("retention_days", 30),
        },
        "display": {
            "show_ids": display.get("show_ids", True),
            "time_format": display.get("time_format", "%Y.%m.%d %H:%M:%S (%Z)"),
        },
        "notifications": {
            "bark_key": notifications.get("bark_key", ""),
        },
    }

    targets_raw = []
    if "targets" in raw:
        targets_raw = raw.get("targets", []) or []
    elif "target" in raw:
        targets_raw = [raw.get("target", {})]
    targets: list[dict[str, Any]] = []
    for idx, target in enumerate(targets_raw, start=1):
        if not isinstance(target, dict):
            continue
        aliases = target.get("tracked_user_aliases", {}) or {}
        tracked_users = []
        for user_id in target.get("tracked_user_ids", []) or []:
            alias = aliases.get(user_id) or aliases.get(str(user_id)) or ""
            tracked_users.append({"id": str(user_id), "alias": alias})
        if not tracked_users:
            tracked_users = [{"id": "", "alias": ""}]
        targets.append(
            {
                "name": target.get("name", f"group-{idx}"),
                "target_chat_id": target.get("target_chat_id", ""),
                "summary_interval_minutes": target.get("summary_interval_minutes", ""),
                "control_group": target.get("control_group", ""),
                "tracked_users": tracked_users,
            }
        )
    if not targets:
        targets = [blank_target()]
    data["targets"] = targets

    control_groups_raw: dict[str, Any] = {}
    if "control_groups" in raw:
        control_groups_raw = raw.get("control_groups", {}) or {}
    elif "control" in raw:
        control_groups_raw = {"default": raw.get("control", {})}
    control_groups: list[dict[str, Any]] = []
    for key, group in control_groups_raw.items():
        if not isinstance(group, dict):
            continue
        topic_map = []
        for user_id, topic_id in (group.get("topic_user_map", {}) or {}).items():
            topic_map.append({"user_id": str(user_id), "topic_id": str(topic_id)})
        if not topic_map:
            topic_map = [{"user_id": "", "topic_id": ""}]
        control_groups.append(
            {
                "key": str(key),
                "control_chat_id": group.get("control_chat_id", ""),
                "is_forum": bool(group.get("is_forum", False)),
                "topic_routing_enabled": bool(group.get("topic_routing_enabled", False)),
                "topic_user_map": topic_map,
            }
        )
    if not control_groups:
        control_groups = [blank_control_group()]
    data["control_groups"] = control_groups
    return data


def blank_target() -> dict[str, Any]:
    return {
        "name": "",
        "target_chat_id": "",
        "summary_interval_minutes": "",
        "control_group": "",
        "tracked_users": [{"id": "", "alias": ""}],
    }


def blank_control_group() -> dict[str, Any]:
    return {
        "key": "",
        "control_chat_id": "",
        "is_forum": False,
        "topic_routing_enabled": False,
        "topic_user_map": [{"user_id": "", "topic_id": ""}],
    }


def _validate_payload(payload: dict[str, Any], raw_existing: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []

    telegram = payload.get("telegram", {}) or {}
    api_id_raw = str(telegram.get("api_id", "")).strip()
    api_hash_raw = str(telegram.get("api_hash", "")).strip()
    session_file = str(telegram.get("session_file", "data/tgwatch.session")).strip()

    if not api_id_raw:
        errors.append("telegram.api_id is required")
    if api_hash_raw in {"", KEEP_SECRET}:
        api_hash_raw = str(raw_existing.get("telegram", {}).get("api_hash", "")).strip()
    if not api_hash_raw:
        errors.append("telegram.api_hash is required")

    sender = payload.get("sender", {}) or {}
    sender_enabled = bool(sender.get("enabled", False))
    sender_session = str(sender.get("session_file", "")).strip()
    if sender_enabled and not sender_session:
        errors.append("sender.session_file is required when sender is enabled")
    if sender_enabled and sender_session and sender_session == session_file:
        errors.append("sender.session_file must differ from telegram.session_file")

    targets_raw = payload.get("targets", []) or []
    control_raw = payload.get("control_groups", []) or []

    if not targets_raw:
        errors.append("At least one target group is required")
    if len(targets_raw) > MAX_TARGET_GROUPS:
        errors.append(f"Targets cannot exceed {MAX_TARGET_GROUPS}")
    if not control_raw:
        errors.append("At least one control group is required")
    if len(control_raw) > MAX_CONTROL_GROUPS:
        errors.append(f"Control groups cannot exceed {MAX_CONTROL_GROUPS}")

    control_groups: list[dict[str, Any]] = []
    control_keys: list[str] = []
    for idx, raw in enumerate(control_raw, start=1):
        key = str(raw.get("key", "")).strip()
        if not key:
            errors.append(f"Control group #{idx} requires a key")
        if key in control_keys:
            errors.append(f"Duplicate control group key: {key}")
        control_keys.append(key)
        chat_id = _coerce_int(raw.get("control_chat_id"), f"control_groups[{key}].control_chat_id", errors)
        is_forum = bool(raw.get("is_forum", False))
        topic_enabled = bool(raw.get("topic_routing_enabled", False))
        topic_map_entries = raw.get("topic_user_map", []) or []
        topic_map = []
        for entry in topic_map_entries:
            user_id = _coerce_int(entry.get("user_id"), f"control_groups[{key}].topic_user_map.user_id", errors)
            topic_id = _coerce_int(entry.get("topic_id"), f"control_groups[{key}].topic_user_map.topic_id", errors)
            if user_id is not None and topic_id is not None:
                topic_map.append({"user_id": user_id, "topic_id": topic_id})
        if topic_enabled and not is_forum:
            errors.append(f"control_groups[{key}] topic routing requires forum mode")
        if topic_enabled and not topic_map:
            errors.append(f"control_groups[{key}] topic routing requires at least one mapping")
        control_groups.append(
            {
                "key": key,
                "control_chat_id": chat_id,
                "is_forum": is_forum,
                "topic_routing_enabled": topic_enabled,
                "topic_user_map": topic_map,
            }
        )

    default_control = control_keys[0] if len(control_keys) == 1 else None

    targets: list[dict[str, Any]] = []
    mapped_users: dict[str, set[int]] = {key: set() for key in control_keys}
    for idx, raw in enumerate(targets_raw, start=1):
        name = str(raw.get("name", "")).strip()
        if not name:
            errors.append(f"targets[{idx}].name is required")
        chat_id = _coerce_int(raw.get("target_chat_id"), f"targets[{idx}].target_chat_id", errors)
        interval_raw = str(raw.get("summary_interval_minutes", "")).strip()
        interval = None
        if interval_raw:
            interval = _coerce_int(interval_raw, f"targets[{idx}].summary_interval_minutes", errors)
            if interval is not None and interval <= 0:
                errors.append(f"targets[{idx}].summary_interval_minutes must be > 0")
        control_group = str(raw.get("control_group", "")).strip() or default_control
        if not control_group:
            errors.append(f"targets[{idx}] must map to a control_group")
        if control_group and control_group not in control_keys:
            errors.append(f"targets[{idx}] references unknown control_group '{control_group}'")
        tracked_users_raw = raw.get("tracked_users", []) or []
        if not tracked_users_raw:
            errors.append(f"targets[{idx}].tracked_users cannot be empty")
        if len(tracked_users_raw) > MAX_USERS_PER_TARGET:
            errors.append(f"targets[{idx}] cannot exceed {MAX_USERS_PER_TARGET} users")
        tracked_ids: list[int] = []
        aliases: dict[int, str] = {}
        for uidx, entry in enumerate(tracked_users_raw, start=1):
            user_id = _coerce_int(entry.get("id"), f"targets[{idx}].tracked_users[{uidx}].id", errors)
            if user_id is None:
                continue
            if user_id in tracked_ids:
                errors.append(f"targets[{idx}] has duplicate user_id {user_id}")
                continue
            tracked_ids.append(user_id)
            alias = str(entry.get("alias", "")).strip()
            if alias:
                aliases[user_id] = alias
            if control_group:
                mapped_users.setdefault(control_group, set()).add(user_id)
        targets.append(
            {
                "name": name,
                "target_chat_id": chat_id,
                "tracked_user_ids": tracked_ids,
                "tracked_user_aliases": aliases,
                "summary_interval_minutes": interval,
                "control_group": control_group,
            }
        )

    for group in control_groups:
        if not group["topic_routing_enabled"]:
            continue
        allowed = mapped_users.get(group["key"], set())
        unknown = {entry["user_id"] for entry in group["topic_user_map"]} - allowed
        if unknown:
            formatted = ", ".join(str(uid) for uid in sorted(unknown))
            errors.append(
                f"control_groups[{group['key']}] topic map includes unknown users: {formatted}"
            )

    reporting = payload.get("reporting", {}) or {}
    storage = payload.get("storage", {}) or {}
    display = payload.get("display", {}) or {}
    notifications = payload.get("notifications", {}) or {}

    normalized = {
        "telegram": {
            "api_id": _coerce_int(api_id_raw, "telegram.api_id", errors) or 0,
            "api_hash": api_hash_raw,
            "session_file": session_file or "data/tgwatch.session",
        },
        "sender": {
            "enabled": sender_enabled,
            "session_file": sender_session,
        },
        "targets": targets,
        "control_groups": control_groups,
        "storage": {
            "db_path": str(storage.get("db_path", "data/tgwatch.sqlite3")).strip(),
            "media_dir": str(storage.get("media_dir", "data/media")).strip(),
        },
        "reporting": {
            "reports_dir": str(reporting.get("reports_dir", "reports")).strip(),
            "summary_interval_minutes": _coerce_int(
                reporting.get("summary_interval_minutes", 120),
                "reporting.summary_interval_minutes",
                errors,
            )
            or 120,
            "timezone": str(reporting.get("timezone", "UTC")).strip() or "UTC",
            "retention_days": _coerce_int(
                reporting.get("retention_days", 30),
                "reporting.retention_days",
                errors,
            )
            or 30,
        },
        "display": {
            "show_ids": bool(display.get("show_ids", True)),
            "time_format": str(display.get("time_format", "%Y.%m.%d %H:%M:%S (%Z)")).strip()
            or "%Y.%m.%d %H:%M:%S (%Z)",
        },
        "notifications": {
            "bark_key": str(notifications.get("bark_key", "")).strip(),
        },
    }

    return errors, normalized


def _coerce_int(value: Any, label: str, errors: list[str]) -> int | None:
    if value is None:
        errors.append(f"{label} is required")
        return None
    if isinstance(value, str):
        value = value.strip()
    if value == "":
        errors.append(f"{label} is required")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be an integer")
        return None


def _render_toml(config: dict[str, Any], raw_existing: dict[str, Any]) -> str:
    lines: list[str] = []
    telegram = config["telegram"]
    api_hash = telegram["api_hash"]
    if api_hash in {"", KEEP_SECRET}:
        api_hash = str(raw_existing.get("telegram", {}).get("api_hash", ""))
    lines.extend(
        [
            "[telegram]",
            f"api_id = {telegram['api_id']}",
            f"api_hash = {toml_string(api_hash)}",
            f"session_file = {toml_string(telegram['session_file'])}",
        ]
    )

    sender = config["sender"]
    if sender.get("enabled"):
        lines.extend(
            [
                "",
                "[sender]",
                f"session_file = {toml_string(sender.get('session_file', ''))}",
            ]
        )

    for target in config["targets"]:
        lines.extend(
            [
                "",
                "[[targets]]",
                f"name = {toml_string(target['name'])}",
                f"target_chat_id = {target['target_chat_id']}",
                f"tracked_user_ids = {toml_list(target['tracked_user_ids'])}",
            ]
        )
        if target.get("summary_interval_minutes"):
            lines.append(f"summary_interval_minutes = {target['summary_interval_minutes']}")
        if target.get("control_group"):
            lines.append(f"control_group = {toml_string(target['control_group'])}")
        aliases = target.get("tracked_user_aliases", {})
        if aliases:
            lines.append("")
            lines.append("[targets.tracked_user_aliases]")
            for user_id, alias in aliases.items():
                lines.append(f"{user_id} = {toml_string(alias)}")

    for group in config["control_groups"]:
        key = group["key"]
        lines.extend(
            [
                "",
                f"[control_groups.{key}]",
                f"control_chat_id = {group['control_chat_id']}",
                f"is_forum = {toml_bool(group['is_forum'])}",
                f"topic_routing_enabled = {toml_bool(group['topic_routing_enabled'])}",
            ]
        )
        topic_map = group.get("topic_user_map", [])
        if topic_map:
            lines.append("")
            lines.append(f"[control_groups.{key}.topic_user_map]")
            for entry in topic_map:
                lines.append(f"{entry['user_id']} = {entry['topic_id']}")

    storage = config["storage"]
    reporting = config["reporting"]
    display = config["display"]
    notifications = config["notifications"]

    lines.extend(
        [
            "",
            "[storage]",
            f"db_path = {toml_string(storage['db_path'])}",
            f"media_dir = {toml_string(storage['media_dir'])}",
            "",
            "[reporting]",
            f"reports_dir = {toml_string(reporting['reports_dir'])}",
            f"summary_interval_minutes = {reporting['summary_interval_minutes']}",
            f"timezone = {toml_string(reporting['timezone'])}",
            f"retention_days = {reporting['retention_days']}",
            "",
            "[display]",
            f"show_ids = {toml_bool(display['show_ids'])}",
            f"time_format = {toml_string(display['time_format'])}",
            "",
            "[notifications]",
            f"bark_key = {toml_string(notifications.get('bark_key', ''))}",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def toml_string(value: str) -> str:
    value = value.replace("\\", "\\\\").replace('"', "\\\"")
    return f'"{value}"'


def toml_bool(value: bool) -> str:
    return "true" if value else "false"


def toml_list(values: list[int]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"
