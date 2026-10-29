#!/usr/bin/env python3
"""Genera workflows/*.json a partir de src/ y prompts/. No lleva secretos.

    python3 scripts/build_workflows.py          # escribe los seis JSON
    python3 scripts/build_workflows.py --check  # falla si los JSON no están al día
"""

import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = uuid.UUID("6f0c1a2e-3b4d-4e5f-8a9b-0c1d2e3f4a5b")

# Las credenciales van por nombre, sin id. Si en n8n ya existe una credencial
# con ese nombre y ese tipo, n8n la asigna sola al importar. Si no, el nodo
# queda pidiendo credencial, como antes.
CREDENTIALS = {
    "pg": ("postgres", "PostgreSQL"),
    "mail": ("httpHeaderAuth", "Mail API Key"),
    "rag": ("httpHeaderAuth", "RAG API Key"),
    "llm": ("httpHeaderAuth", "LLM API"),
    "github": ("httpHeaderAuth", "GitHub Issues"),
    "telegram": ("telegramApi", "Telegram"),
    "imap": ("imap", "IMAP"),
}


def nid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def cred(key):
    type_, name = CREDENTIALS[key]
    return {type_: {"id": None, "name": name}}


def src(*names: str) -> str:
    chunks = []
    for name in names:
        text = (ROOT / "src" / name).read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if not line.startswith("module.exports")]
        chunks.append("\n".join(lines).strip())
    return "\n\n".join(chunks)


def node(name, type_, version, x, y, parameters, notes="", extra=None, credentials=None):
    item = {
        "parameters": parameters,
        "id": nid(name + type_),
        "name": name,
        "type": type_,
        "typeVersion": version,
        "position": [x, y],
    }
    if credentials:
        item["credentials"] = cred(credentials)
    if notes:
        item["notes"] = notes
    if extra:
        item.update(extra)
    return item


def code(name, x, y, body, files=(), each=True, notes="", extra=None):
    prefix = src(*files)
    script = f"{prefix}\n\n{body.strip()}\n" if prefix else body.strip() + "\n"
    parameters = {"jsCode": script}
    if each:
        parameters["mode"] = "runOnceForEachItem"
    return node(name, "n8n-nodes-base.code", 2, x, y, parameters, notes, extra)


def py_code(name, x, y, body, notes=""):
    """Code node de Python (runner nativo). Lleva src/send_mail.py delante."""
    prefix = (ROOT / "src" / "send_mail.py").read_text(encoding="utf-8").strip()
    return node(
        name,
        "n8n-nodes-base.code",
        2,
        x,
        y,
        {"mode": "runOnceForEachItem", "language": "pythonNative", "pythonCode": f"{prefix}\n\n\n{body.strip()}\n"},
        notes,
        # Si el runner no deja importar smtplib (falta runners/n8n-task-runners.json),
        # el nodo falla antes de ejecutar: esa salida de error también se trata.
        {"onError": "continueErrorOutput"},
    )


def postgres(name, x, y, query, replacement, notes="", extra=None):
    # Ojo: con retryOnFail, n8n reintenta el nodo si un item de salida trae la
    # clave "error". Ninguna consulta devuelve una columna con ese nombre.
    if re.search(r"\bas\s+\"?error\"?\b", query, re.IGNORECASE):
        raise SystemExit(f"{name}: no devuelvas una columna 'error' (n8n reintenta el nodo)")
    options = {"queryBatching": "independently"}
    if replacement:
        options["queryReplacement"] = replacement
    settings = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000}
    if extra:
        settings.update(extra)
    return node(
        name,
        "n8n-nodes-base.postgres",
        2.5,
        x,
        y,
        {"operation": "executeQuery", "query": query, "options": options},
        notes,
        settings,
        "pg",
    )


def http_json(name, x, y, url, body_expr, credential, notes="", text=False, headers=None, timeout=120000, tries=3):
    response = {"response": {"responseFormat": "text", "outputPropertyName": "rag_raw"}} if text else {"response": {"responseFormat": "json"}}
    parameters = {
        "method": "POST",
        "url": url,
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": body_expr,
        "options": {"timeout": timeout, "response": response},
    }
    if headers:
        parameters["sendHeaders"] = True
        parameters["headerParameters"] = {"parameters": [{"name": key, "value": value} for key, value in headers]}
    return node(
        name,
        "n8n-nodes-base.httpRequest",
        4.2,
        x,
        y,
        parameters,
        notes,
        {"retryOnFail": True, "maxTries": tries, "waitBetweenTries": 2000, "onError": "continueErrorOutput"},
        credential,
    )


def keyboard(*buttons):
    return {"rows": [{"row": {"buttons": [{"text": text, "additionalFields": {"callback_data": data}} for text, data in buttons]}}]}


def telegram(name, x, y, chat_expr, text_expr, notes="", buttons=None, force_reply=False, reply_to=None, on_error="continueErrorOutput"):
    """sendMessage siempre en HTML (el texto ya va escapado). Sin HTML, n8n usa
    Markdown y un guion bajo del correo rompe el mensaje."""
    additional = {"parse_mode": "HTML", "appendAttribution": False, "disable_web_page_preview": True}
    if reply_to:
        additional["reply_to_message_id"] = reply_to
    parameters = {
        "resource": "message",
        "operation": "sendMessage",
        "chatId": chat_expr,
        "text": text_expr,
        "replyMarkup": "none",
        "additionalFields": additional,
    }
    if buttons:
        parameters["replyMarkup"] = "inlineKeyboard"
        parameters["inlineKeyboard"] = keyboard(*buttons)
    if force_reply:
        parameters["replyMarkup"] = "forceReply"
        parameters["forceReply"] = {"force_reply": True}
    return node(name, "n8n-nodes-base.telegram", 1.2, x, y, parameters, notes, {"onError": on_error}, "telegram")


def switch_if(name, x, y, left, right, notes=""):
    return node(
        name,
        "n8n-nodes-base.if",
        2.2,
        x,
        y,
        {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                "conditions": [{
                    "leftValue": left,
                    "rightValue": right,
                    "operator": {"type": "string", "operation": "equals"},
                }],
                "combinator": "and",
            },
            "options": {},
        },
        notes,
    )


def bool_if(name, x, y, left, notes=""):
    return node(
        name,
        "n8n-nodes-base.if",
        2.2,
        x,
        y,
        {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                "conditions": [{
                    "leftValue": left,
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }],
                "combinator": "and",
            },
            "options": {},
        },
        notes,
    )


def sticky(name, x, y, content, width=560, height=240):
    return node(
        name,
        "n8n-nodes-base.stickyNote",
        1,
        x,
        y,
        {"content": content, "height": height, "width": width, "color": 5},
    )


PROMPT = (ROOT / "prompts" / "clasificador.md").read_text(encoding="utf-8").strip()

FIELDS = {
    "support_address": ("soporte@tudominio.com", "string"),
    "confidence_threshold": (0.75, "number"),
    "min_rag_score": (0.45, "number"),
    "approval_hours": (24, "number"),
    "retention_days": (90, "number"),
    "sensitive_topics": ("precio,precios,plazo,plazos,contrato,legal,devolución,devolucion,reembolso,dni,iban,tarjeta", "string"),
    "llm_base_url": ("https://api.deepseek.com", "string"),
    "llm_model": ("deepseek-v4-flash", "string"),
    # n8n se llama a sí mismo: localhost:5678 es el propio contenedor de n8n.
    "rag_url": ("http://localhost:5678/webhook/rag-search", "string"),
    "n8n_url": ("http://localhost:5678", "string"),
    "telegram_chat_id": ("cambia-esto", "string"),
    "telegram_user_ids": ("", "string"),
    "github_repo": ("tu-usuario/email-agent-sandbox", "string"),
    "github_api_url": ("https://api.github.com", "string"),
    "prompt": (PROMPT, "string"),
}


def config_node(x, y, keys):
    assignments = []
    for key in keys:
        value, typ = FIELDS[key]
        assignments.append({"id": nid("cfg-" + key), "name": key, "value": value, "type": typ})
    return node(
        "Configuración",
        "n8n-nodes-base.set",
        3.4,
        x,
        y,
        {
            "mode": "manual",
            "duplicateItem": False,
            "includeOtherFields": True,
            "assignments": {"assignments": assignments},
            "options": {},
        },
        "Valores que se ven en cámara. El .env no entra aquí: Coolify bloquea $env.",
    )


def webhook(name, path, x, y, notes):
    return node(
        name,
        "n8n-nodes-base.webhook",
        2.1,
        x,
        y,
        {
            "httpMethod": "POST",
            "path": path,
            "authentication": "headerAuth",
            "responseMode": "onReceived",
            "options": {},
        },
        notes,
        {"webhookId": nid("wh-" + path)},
        "mail",
    )


def link(connections, source, target, output=0, input_index=0):
    connections.setdefault(source, {"main": []})
    while len(connections[source]["main"]) <= output:
        connections[source]["main"].append([])
    connections[source]["main"][output].append({"node": target, "type": "main", "index": input_index})


def pack(name, nodes, connections):
    names = [item["name"] for item in nodes]
    if len(names) != len(set(names)):
        raise SystemExit(f"{name}: nombres de nodo repetidos")
    for source, outputs in connections.items():
        if source not in names:
            raise SystemExit(f"{name}: origen desconocido {source}")
        for branch in outputs["main"]:
            for edge in branch:
                if edge["node"] not in names:
                    raise SystemExit(f"{name}: destino desconocido {edge['node']}")
    return {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": {"executionOrder": "v1"},
        "pinData": {},
    }


def uuid_guard(fields):
    """Cuerpo JS común: valida mail_id antes de tocar la base."""
    return f"""
const body = $json.body || $json;
const mailId = String(body.mail_id || '');
const valid = /^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$/i.test(mailId);
return {{ json: {{ mail_id: mailId, {fields}, valid }} }};
"""


IGNORED_REQUEST = """INSERT INTO mail_actions (mail_id, action, detail)
SELECT id, 'peticion_ignorada', jsonb_build_object('flujo', $2::text, 'estado', status)
FROM mail_messages WHERE id = $1::uuid
RETURNING id"""


def flow_ingest():
    cfg = "$('Configuración').first().json"
    nodes = [
        sticky("Notas ingesta", 80, 40, "### 01 Ingesta\n\nIMAP es el disparador real. El webhook `mail-ingest` hace el mismo camino para pruebas, con la cabecera X-MAIL-API-Key.\n\nPrimero se reserva el Message-ID en Postgres (`procesando`). Si ya estaba, es un duplicado y no se llama al modelo.\n\nSi no se puede pasar el correo al 02, 03a o 04, la fila queda en `error_interno` y llega un aviso a Telegram."),
        node("Correo IMAP", "n8n-nodes-base.emailReadImap", 2.1, 220, 300, {
            "mailbox": "INBOX",
            "postProcessAction": "read",
            "format": "simple",
            "downloadAttachments": False,
            "options": {},
        }, "Formato simple: textPlain, textHtml y todas las cabeceras en metadata (Message-ID, Auto-Submitted, List-Id...). Sin adjuntos.", credentials="imap"),
        webhook("Probar correo", "mail-ingest", 220, 520, "POST /webhook/mail-ingest con el mismo JSON que normaliza el flujo. Solo pruebas."),
        config_node(480, 400, ["support_address", "confidence_threshold", "min_rag_score", "sensitive_topics", "llm_base_url", "llm_model", "rag_url", "n8n_url", "telegram_chat_id", "prompt"]),
        code("Normalizar", 740, 400, """
return { json: normalizeEmail($json) };
""", ("normalize.js",), notes="Quita HTML, rastreadores, firma y respuestas citadas. Sin Message-ID, calcula uno estable (generado-...)."),
        code("Filtros", 960, 400, """
const config = $('Configuración').first().json;
const verdict = inspectMail($json, config.support_address);
return { json: { ...$json, ...verdict } };
""", ("security.js",), notes="Autorespuestas, listas, no-reply y remitentes raros. Marca inyección, no la obedece."),
        bool_if("¿Ignorar?", 1180, 400, "={{ $json.ignore }}", "Sí: se registra y se acaba. No: sigue."),
        postgres(
            "Guardar ignorado",
            1400,
            580,
            """WITH ins AS (
  INSERT INTO mail_messages
    (message_id, from_address, from_name, to_address, subject, body_normalized, status, reasoning, received_at)
  VALUES ($1, $2, $3, $4, $5, $6, 'ignorado_autorespuesta', $7, NULLIF($8::text, '')::timestamptz)
  ON CONFLICT (message_id) DO NOTHING
  RETURNING id
)
SELECT (SELECT id::text FROM ins) AS id""",
            "={{ [$json.message_id, $json.from_address, $json.from_name, $json.to_address, $json.subject, $json.body, $json.ignore_reason, $json.received_at || ''] }}",
            "La autorespuesta queda escrita y no se contesta.",
        ),
        postgres(
            "Reservar",
            1400,
            300,
            """WITH ins AS (
  INSERT INTO mail_messages
    (message_id, from_address, from_name, to_address, subject, body_normalized,
     in_reply_to, references_header, status, injection_flag, received_at)
  VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'procesando', $9::boolean, NULLIF($10::text, '')::timestamptz)
  ON CONFLICT (message_id) DO NOTHING
  RETURNING id
)
SELECT (SELECT id::text FROM ins) AS id""",
            "={{ [$json.message_id, $json.from_address, $json.from_name, $json.to_address, $json.subject, $json.body, $json.in_reply_to, $json.references_header, $json.injection, $json.received_at || ''] }}",
            "La clave es el Message-ID. Dos ejecuciones a la vez: solo una consigue la fila.",
        ),
        code("Con reserva", 1620, 300, """
const mail = $('Filtros').item.json;
return { json: { ...mail, id: $json.id || null, duplicate: !$json.id } };
"""),
        bool_if("¿Duplicado?", 1840, 300, "={{ $json.duplicate }}"),
        postgres(
            "Anotar duplicado",
            2060,
            160,
            """INSERT INTO mail_actions (mail_id, action, detail)
SELECT id, 'duplicado', jsonb_build_object('message_id', $1::text)
FROM mail_messages WHERE message_id = $1
RETURNING id""",
            "={{ [$json.message_id] }}",
            "Auditoría del segundo intento. No llama al modelo.",
        ),
        http_json(
            "Buscar RAG",
            2060,
            400,
            f"={{{{ {cfg}.rag_url }}}}",
            "={{ JSON.stringify({ query: ($json.subject + '\\n' + $json.body).slice(0, 1200), limit: 5, source_type: 'all' }) }}",
            "rag",
            "La respuesta tiene que salir de la base del episodio 2.",
            text=True,
        ),
        code("Unir fuentes", 2300, 400, """
const email = $('Con reserva').item.json;
let parsed = [];
const raw = $json.rag_raw || $json.data || '';
if (!$json.error && raw) {
  try { parsed = JSON.parse(raw); } catch (error) { parsed = []; }
}
if (parsed && parsed.error) parsed = [];
if (!Array.isArray(parsed)) parsed = [];
const sources = parsed.slice(0, 5).map((row) => ({
  document_id: row.document_id || null,
  title: String(row.title || '').slice(0, 300),
  canonical_url: String(row.canonical_url || '').slice(0, 500),
  score: Number(row.score || 0),
  content: String(row.content || '').slice(0, 700),
  source_type: row.source_type || '',
  chunk_index: row.chunk_index,
})).sort((a, b) => b.score - a.score);
const ids = sources.map((row) => row.document_id).filter((id) => /^[0-9a-f-]{36}$/i.test(String(id)));
return { json: { ...email, sources, source_ids: ids.join(',') } };
""", notes="Junta los fragmentos. Si el RAG falla, la lista queda vacía y el correo va a una persona."),
        bool_if("¿Hay ids?", 2520, 400, "={{ $json.source_ids !== '' }}"),
        postgres(
            "Fechas",
            2740,
            280,
            """SELECT COALESCE(string_agg(id::text || '|' || to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD'), ','), '') AS pairs
FROM knowledge_documents
WHERE id = ANY(string_to_array($1, ',')::uuid[])""",
            "={{ [$json.source_ids] }}",
            "El webhook del episodio 2 no trae la fecha. Se lee de knowledge_documents.",
        ),
        code("Mezclar fechas", 2960, 280, """
const email = $('Unir fuentes').item.json;
const pairs = String($json.pairs || '').split(',').filter(Boolean);
const dates = {};
for (const pair of pairs) {
  const cut = pair.indexOf('|');
  if (cut > 0) dates[pair.slice(0, cut)] = pair.slice(cut + 1);
}
const sources = (email.sources || []).map((source) => ({ ...source, updated_at: dates[source.document_id] || null }));
return { json: { ...email, sources } };
"""),
        code("Preparar bloque", 3180, 400, """
const email = $json.sources ? $json : $('Unir fuentes').item.json;
return { json: { ...email, user_block: buildUserBlock(email, email.sources || []) } };
""", ("prompt.js",), notes="Instrucciones y datos van separados. El correo entra como dato y no puede cerrar su marca."),
        http_json(
            "Clasificar",
            3400,
            400,
            f"={{{{ {cfg}.llm_base_url.replace(/\\/$/, '') + '/chat/completions' }}}}",
            f"={{{{ JSON.stringify({{ model: {cfg}.llm_model, temperature: 0, max_tokens: 1200, response_format: {{ type: 'json_object' }}, messages: [ {{ role: 'system', content: {cfg}.prompt }}, {{ role: 'user', content: $json.user_block }} ] }}) }}}}",
            "llm",
            "JSON estricto. Si no parsea, el correo no se responde solo.",
        ),
        code("Decidir", 3620, 400, """
const base = $('Preparar bloque').item.json;
const config = $('Configuración').first().json;
let raw = '';
let parsed = null;
if (!$json.error) {
  raw = llmPayload($json);
  parsed = extractJson(raw);
}
const decision = decide({
  subject: base.subject,
  body: base.body,
  injection: base.injection,
  sources: base.sources || [],
  parsed,
}, config);
return { json: { ...base, ...decision, model_raw: String(raw).slice(0, 2000) } };
""", ("decide.js",), notes="Capa de salida: inyección, temas sensibles, borrador vacío y JSON roto no se envían solos."),
        postgres(
            "Guardar",
            3840,
            400,
            """WITH upd AS (
  UPDATE mail_messages
  SET category = $2, confidence = $3::numeric, draft_reply = $4, reasoning = $5,
      rag_sources = $6::jsonb, injection_flag = $7::boolean, sensitive_flag = $8::boolean,
      route = $9, status = 'pendiente'
  WHERE id = $1::uuid AND status = 'procesando'
  RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$json.id, $json.category, $json.confidence, $json.draft_reply, $json.reasoning, JSON.stringify($json.sources || []), $json.injection, $json.sensitive, $json.route] }}",
            "Guarda la decisión y la ruta. La fila pasa a pendiente: el 02, 03a o 04 la recoge.",
        ),
        code("Con id", 4060, 400, """
const decision = $('Decidir').item.json;
if (!$json.id) return { json: { ...decision, skipped: true } };
return { json: { ...decision, id: $json.id, skipped: false } };
"""),
        bool_if("¿Guardado?", 4280, 400, "={{ !$json.skipped }}"),
        switch_if("¿Auto?", 4500, 400, "={{ $json.route }}", "auto"),
        switch_if("¿Aprobar?", 4720, 520, "={{ $json.route }}", "approval"),
        http_json(
            "Pedir respuesta",
            4940,
            280,
            f"={{{{ {cfg}.n8n_url.replace(/\\/$/, '') + '/webhook/mail-reply' }}}}",
            "={{ JSON.stringify({ mail_id: $json.id, mode: 'auto' }) }}",
            "mail",
            "Dispara el flujo 02. No envía desde aquí.",
        ),
        http_json(
            "Pedir aprobación",
            4940,
            460,
            f"={{{{ {cfg}.n8n_url.replace(/\\/$/, '') + '/webhook/mail-approval' }}}}",
            "={{ JSON.stringify({ mail_id: $json.id }) }}",
            "mail",
            "Dispara el flujo 03a y se acaba. No hay nodo Wait.",
        ),
        http_json(
            "Pedir acción",
            4940,
            660,
            f"={{{{ {cfg}.n8n_url.replace(/\\/$/, '') + '/webhook/mail-action' }}}}",
            "={{ JSON.stringify({ mail_id: $json.id, route: $json.route }) }}",
            "mail",
            "Bug, urgente, lead o spam. El flujo 04 decide.",
        ),
        code("Fallo interno", 5180, 840, """
const mail = $('Con id').item.json;
const config = $('Configuración').first().json;
const raw = $json.error;
const error = String(typeof raw === 'string' ? raw : (raw && (raw.message || raw.description)) || JSON.stringify(raw || 'sin detalle')).slice(0, 400);
const target = mail.route === 'auto' ? 'el flujo 02 (mail-reply)' : mail.route === 'approval' ? 'el flujo 03a (mail-approval)' : 'el flujo 04 (mail-action)';
const hint = '¿Está activo ' + target + '? ¿n8n_url y la credencial Mail API Key son las mismas en los dos flujos? La fila queda en error_interno.';
return { json: { id: mail.id, target, fallo: error, chat_id: config.telegram_chat_id, text: failureMessage('no se pudo pasar el correo a ' + target, { ...mail, hint }, error) } };
""", ("format.js",), notes="Las salidas de error de los tres HTTP llegan aquí. No se falla en silencio."),
        postgres(
            "Marcar error interno",
            5400,
            840,
            """WITH upd AS (
  UPDATE mail_messages SET status = 'error_interno'
  WHERE id = $1::uuid AND status = 'pendiente'
  RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  VALUES ($1::uuid, 'error_interno', jsonb_build_object('destino', $2::text, 'error', $3::text))
  RETURNING id
)
SELECT (SELECT count(*) FROM upd)::int AS updated""",
            "={{ [$json.id, $json.target, $json.fallo] }}",
        ),
        telegram(
            "Avisar fallo",
            5620,
            840,
            "={{ $('Fallo interno').item.json.chat_id }}",
            "={{ $('Fallo interno').item.json.text }}",
            "Si Telegram también falla, queda el rastro en la base.",
            on_error="continueRegularOutput",
        ),
    ]
    c = {}
    link(c, "Correo IMAP", "Configuración")
    link(c, "Probar correo", "Configuración")
    link(c, "Configuración", "Normalizar")
    link(c, "Normalizar", "Filtros")
    link(c, "Filtros", "¿Ignorar?")
    link(c, "¿Ignorar?", "Guardar ignorado", 0)
    link(c, "¿Ignorar?", "Reservar", 1)
    link(c, "Reservar", "Con reserva")
    link(c, "Con reserva", "¿Duplicado?")
    link(c, "¿Duplicado?", "Anotar duplicado", 0)
    link(c, "¿Duplicado?", "Buscar RAG", 1)
    link(c, "Buscar RAG", "Unir fuentes", 0)
    link(c, "Buscar RAG", "Unir fuentes", 1)
    link(c, "Unir fuentes", "¿Hay ids?")
    link(c, "¿Hay ids?", "Fechas", 0)
    link(c, "¿Hay ids?", "Preparar bloque", 1)
    link(c, "Fechas", "Mezclar fechas")
    link(c, "Mezclar fechas", "Preparar bloque")
    link(c, "Preparar bloque", "Clasificar")
    link(c, "Clasificar", "Decidir", 0)
    link(c, "Clasificar", "Decidir", 1)
    link(c, "Decidir", "Guardar")
    link(c, "Guardar", "Con id")
    link(c, "Con id", "¿Guardado?")
    link(c, "¿Guardado?", "¿Auto?", 0)
    link(c, "¿Auto?", "Pedir respuesta", 0)
    link(c, "¿Auto?", "¿Aprobar?", 1)
    link(c, "¿Aprobar?", "Pedir aprobación", 0)
    link(c, "¿Aprobar?", "Pedir acción", 1)
    for caller in ("Pedir respuesta", "Pedir aprobación", "Pedir acción"):
        link(c, caller, "Fallo interno", 1)
    link(c, "Fallo interno", "Marcar error interno")
    link(c, "Marcar error interno", "Avisar fallo")
    return pack("01 - Ingesta", nodes, c)


def flow_reply():
    cfg = "$('Configuración').first().json"
    nodes = [
        sticky("Notas respuesta", 80, 40, "### 02 Respuesta\n\nSolo envía si la fila está lista: `pendiente` con ruta auto, o `aprobado` desde Telegram. El UPDATE que la pasa a `enviando` es atómico: un doble toque no manda dos correos.\n\nEnvía un Code node de Python con smtplib, porque el nodo Send Email de n8n 2.10.2 no deja poner In-Reply-To ni References. El SMTP sale de las variables SMTP_* del contenedor de task runners.\n\nSi el envío falla: `error_envio` y aviso a Telegram con Reintentar."),
        webhook("Webhook respuesta", "mail-reply", 220, 300, "POST /webhook/mail-reply. Cabecera X-MAIL-API-Key."),
        config_node(460, 300, ["support_address", "approval_hours", "telegram_chat_id"]),
        code("Leer petición", 700, 300, uuid_guard("mode: ['auto', 'manual'].includes(body.mode) ? body.mode : ''") .replace("valid }", "valid: valid && ['auto', 'manual'].includes(body.mode) }")),
        bool_if("¿Válida?", 920, 300, "={{ $json.valid }}"),
        postgres(
            "Reclamar",
            1140,
            300,
            """WITH claimed AS (
  UPDATE mail_messages
  SET status = 'enviando'
  WHERE id = $1::uuid
    AND (
      ($2::text = 'auto' AND status = 'pendiente' AND route = 'auto' AND NOT injection_flag)
      OR ($2::text = 'manual' AND status = 'aprobado')
    )
  RETURNING id, message_id, from_address, subject, draft_reply, final_reply, injection_flag, references_header
)
SELECT c.id::text AS id, c.message_id, c.from_address, c.subject, c.draft_reply, c.final_reply,
       COALESCE(c.injection_flag, false) AS injection_flag, c.references_header,
       (SELECT status FROM mail_messages WHERE id = $1::uuid) AS previous_status,
       (SELECT count(*) FROM mail_messages m
         WHERE c.id IS NOT NULL AND m.from_address = c.from_address AND m.status = 'respondido_auto'
           AND m.auto_replied_at > now() - interval '1 hour' AND m.id <> c.id)::int AS recent
FROM (SELECT 1) AS one LEFT JOIN claimed c ON true""",
            "={{ [$json.mail_id, $json.mode] }}",
            "pendiente/aprobado -> enviando en una sola sentencia. Si otra ejecución ya la cogió, no devuelve id.",
        ),
        bool_if("¿Reclamada?", 1360, 300, "={{ !!$json.id }}"),
        postgres(
            "Anotar ignorada",
            1580,
            120,
            IGNORED_REQUEST,
            "={{ [$('Leer petición').item.json.mail_id, '02 ' + $('Leer petición').item.json.mode] }}",
            "Ya enviada, rechazada, vencida o en curso. No se envía otra vez.",
        ),
        code("Preparar envío", 1580, 300, """
const request = $('Leer petición').item.json;
const config = $('Configuración').first().json;
const blocked = Boolean($json.injection_flag);
// Un correo bloqueado solo sale con el texto que escribió una persona (Editar).
const text = request.mode === 'manual'
  ? ($json.final_reply || (blocked ? '' : $json.draft_reply) || '')
  : (blocked ? '' : ($json.draft_reply || ''));
return { json: {
  ...$json,
  mode: request.mode,
  automatic: request.mode === 'auto',
  outgoing_body: String(text).trim(),
  reply_subject: replySubject($json.subject),
  to_address: $json.from_address,
  support_address: config.support_address,
  recent: Number($json.recent || 0),
} };
""", ("format.js",)),
        bool_if("¿Bloquear?", 1800, 300, "={{ $json.mode === 'auto' && $json.recent > 0 }}", "Ya hubo respuesta automática a esta dirección en la última hora."),
        postgres(
            "Retener",
            2020,
            140,
            """WITH upd AS (
  UPDATE mail_messages SET status = 'retenido_bucle'
  WHERE id = $1::uuid AND status = 'enviando'
  RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  VALUES ($1::uuid, 'retenido_bucle', jsonb_build_object('motivo', 'respuesta automática a la misma dirección en la última hora'))
  RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$json.id] }}",
        ),
        py_code("Enviar", 2020, 380, """
import os

item = _item["json"]
result = send_reply(
    {
        "to": item.get("to_address"),
        "subject": item.get("reply_subject"),
        "body": item.get("outgoing_body"),
        "message_id": item.get("message_id"),
        "references": item.get("references_header"),
    },
    item.get("support_address"),
    item.get("automatic") is True,
    os.environ,
)
return {"json": {**item, **result}}
""", "SMTP con In-Reply-To y References. Lee SMTP_HOST, SMTP_PORT, SMTP_SECURITY, SMTP_USER y SMTP_PASSWORD del contenedor de runners."),
        bool_if("¿Enviado?", 2260, 380, "={{ $json.sent === true }}"),
        postgres(
            "Marcar enviado",
            2480,
            300,
            """WITH upd AS (
  UPDATE mail_messages
  SET status = $2::text,
      final_reply = $3,
      reply_message_id = NULLIF($4::text, ''),
      auto_replied_at = CASE WHEN $2::text = 'respondido_auto' THEN now() ELSE auto_replied_at END
  WHERE id = $1::uuid AND status = 'enviando'
  RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  VALUES ($1::uuid, $5::text, jsonb_build_object('reply_message_id', $4::text))
  RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$json.id, $json.mode === 'auto' ? 'respondido_auto' : 'respondido_manual', $json.outgoing_body, $json.reply_message_id, $json.mode === 'auto' ? 'enviado_auto' : 'enviado_manual'] }}",
        ),
        code("Error de envío", 2480, 520, """
const mail = $('Preparar envío').item.json;
const config = $('Configuración').first().json;
// Si el nodo de Python no llega a ejecutarse (runner caído, fichero de runners sin
// montar), n8n pasa el item tal cual por la salida de error, sin mensaje.
const error = String($json.smtp_error || 'el nodo Enviar (Python) no se ejecutó: mira esa ejecución. Suele ser el contenedor task-runners sin conexión (reinícialo) o sin runners/n8n-task-runners.json montado').slice(0, 500);
const hint = 'Queda en error_envio. Reintentar lo manda otra vez (tu texto si lo editaste). Si nadie pulsa, vence como una aprobación.';
return { json: { ...mail, smtp_error: error, chat_id: config.telegram_chat_id, hours: config.approval_hours, text: failureMessage('no se pudo enviar la respuesta', { ...mail, hint }, error) } };
""", ("format.js",), notes="Llega aquí si smtplib falla o si el runner no deja ejecutar el nodo."),
        postgres(
            "Marcar error",
            2700,
            520,
            """WITH upd AS (
  UPDATE mail_messages
  SET status = 'error_envio', approval_due_at = now() + make_interval(hours => $3::int)
  WHERE id = $1::uuid AND status = 'enviando'
  RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  VALUES ($1::uuid, 'error_envio', jsonb_build_object('error', $2::text))
  RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$json.id, $json.smtp_error, $json.hours] }}",
        ),
        telegram(
            "Avisar fallo",
            2920,
            520,
            "={{ $('Error de envío').item.json.chat_id }}",
            "={{ $('Error de envío').item.json.text }}",
            "Con botones: Reintentar es Aprobar en el 03b.",
            buttons=[("Reintentar", "approve"), ("Rechazar", "reject"), ("Editar", "edit")],
            on_error="continueRegularOutput",
        ),
        postgres(
            "Guardar aviso",
            3140,
            520,
            """UPDATE mail_messages
SET telegram_chat_id = $2, telegram_message_id = $3
WHERE id = $1::uuid AND status = 'error_envio' AND $3::text <> ''
RETURNING id::text""",
            "={{ [$('Error de envío').item.json.id, String($('Error de envío').item.json.chat_id), $json.result && $json.result.message_id ? String($json.result.message_id) : ''] }}",
            "Los botones del aviso apuntan a esta fila.",
        ),
    ]
    c = {}
    link(c, "Webhook respuesta", "Configuración")
    link(c, "Configuración", "Leer petición")
    link(c, "Leer petición", "¿Válida?")
    link(c, "¿Válida?", "Reclamar", 0)
    link(c, "Reclamar", "¿Reclamada?")
    link(c, "¿Reclamada?", "Preparar envío", 0)
    link(c, "¿Reclamada?", "Anotar ignorada", 1)
    link(c, "Preparar envío", "¿Bloquear?")
    link(c, "¿Bloquear?", "Retener", 0)
    link(c, "¿Bloquear?", "Enviar", 1)
    link(c, "Enviar", "¿Enviado?", 0)
    link(c, "Enviar", "Error de envío", 1)
    link(c, "¿Enviado?", "Marcar enviado", 0)
    link(c, "¿Enviado?", "Error de envío", 1)
    link(c, "Error de envío", "Marcar error")
    link(c, "Marcar error", "Avisar fallo")
    link(c, "Avisar fallo", "Guardar aviso")
    return pack("02 - Respuesta", nodes, c)


def flow_ask():
    nodes = [
        sticky("Notas aprobación", 80, 40, "### 03a Pedir aprobación\n\nManda el borrador a Telegram y guarda el message_id. Aquí termina.\n\nUn correo bloqueado (inyección o promesa de dinero) llega sin borrador y sin botón Aprobar: solo Rechazar o Editar.\n\nSi nadie pulsa, el flujo 05 marca la fila como vencida cuando pasa approval_hours. No se envía sola."),
        webhook("Webhook aprobación", "mail-approval", 220, 300, "POST /webhook/mail-approval."),
        config_node(460, 300, ["approval_hours", "telegram_chat_id"]),
        code("Leer id", 700, 300, uuid_guard("flow: '03a'")),
        bool_if("¿Válida?", 920, 300, "={{ $json.valid }}"),
        postgres(
            "Reclamar",
            1140,
            300,
            """WITH claimed AS (
  UPDATE mail_messages SET status = 'avisando'
  WHERE id = $1::uuid AND status = 'pendiente' AND route = 'approval'
  RETURNING id, from_address, from_name, subject, category, confidence, draft_reply, reasoning,
            rag_sources, injection_flag, sensitive_flag
)
SELECT c.id::text AS id, c.from_address, c.from_name, c.subject, c.category, c.confidence,
       c.draft_reply, c.reasoning, c.rag_sources, c.injection_flag, c.sensitive_flag
FROM (SELECT 1) AS one LEFT JOIN claimed c ON true""",
            "={{ [$json.mail_id] }}",
            "pendiente -> avisando. Si llega dos veces, la segunda no manda otro Telegram.",
        ),
        bool_if("¿Reclamada?", 1360, 300, "={{ !!$json.id }}"),
        postgres(
            "Anotar ignorada",
            1580,
            120,
            IGNORED_REQUEST,
            "={{ [$('Leer id').item.json.mail_id, '03a'] }}",
        ),
        code("Texto Telegram", 1580, 300, """
const sources = typeof $json.rag_sources === 'string' ? JSON.parse($json.rag_sources) : ($json.rag_sources || []);
const text = approvalMessage({
  from_address: $json.from_address,
  from_name: $json.from_name,
  subject: $json.subject,
  category: $json.category,
  confidence: $json.confidence,
  draft_reply: $json.draft_reply,
  reasoning: $json.reasoning,
  sources,
  injection: $json.injection_flag,
  sensitive: $json.sensitive_flag,
});
return { json: { ...$json, blocked: $json.injection_flag === true, telegram_text: text, chat_id: String($('Configuración').first().json.telegram_chat_id) } };
""", ("format.js",), notes="Remitente, asunto, categoría, confianza, motivo, borrador y fuentes. Cabe en el móvil."),
        bool_if("¿Bloqueado?", 1800, 300, "={{ $json.blocked }}"),
        telegram(
            "Avisar",
            2020,
            400,
            "={{ $json.chat_id }}",
            "={{ $json.telegram_text }}",
            "Botones en una fila. El callback_data es corto a propósito.",
            buttons=[("Aprobar", "approve"), ("Rechazar", "reject"), ("Editar", "edit")],
        ),
        telegram(
            "Avisar sin aprobar",
            2020,
            200,
            "={{ $json.chat_id }}",
            "={{ $json.telegram_text }}",
            "Correo bloqueado: no hay botón Aprobar.",
            buttons=[("Rechazar", "reject"), ("Editar", "edit")],
        ),
        code("Id de Telegram", 2260, 300, """
const mail = $('Texto Telegram').item.json;
const messageId = $json.result && $json.result.message_id ? String($json.result.message_id) : '';
return { json: { id: mail.id, chat_id: mail.chat_id, telegram_message_id: messageId, hours: $('Configuración').first().json.approval_hours } };
"""),
        postgres(
            "Guardar botón",
            2480,
            300,
            """WITH upd AS (
  UPDATE mail_messages
  SET status = 'esperando_aprobacion',
      telegram_chat_id = $2,
      telegram_message_id = $3,
      approval_due_at = now() + make_interval(hours => $4::int)
  WHERE id = $1::uuid AND status = 'avisando' AND $3::text <> ''
  RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  VALUES ($1::uuid, 'pedido_aprobacion', jsonb_build_object('telegram_message_id', $3::text))
  RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$json.id, $json.chat_id, $json.telegram_message_id, $json.hours] }}",
        ),
        postgres(
            "Fallo aviso",
            2260,
            560,
            """WITH upd AS (
  UPDATE mail_messages SET status = 'error_aviso'
  WHERE id = $1::uuid AND status = 'avisando'
  RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  VALUES ($1::uuid, 'error_aviso', jsonb_build_object('error', $2::text))
  RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$('Texto Telegram').item.json.id, String(($json.error && ($json.error.message || $json.error.description)) || $json.error || 'Telegram no respondió').slice(0, 400)] }}",
            "Telegram no aceptó el mensaje (token, chat id). La fila queda en error_aviso y sale en el resumen.",
        ),
    ]
    c = {}
    for a, b in [
        ("Webhook aprobación", "Configuración"),
        ("Configuración", "Leer id"),
        ("Leer id", "¿Válida?"),
    ]:
        link(c, a, b)
    link(c, "¿Válida?", "Reclamar", 0)
    link(c, "Reclamar", "¿Reclamada?")
    link(c, "¿Reclamada?", "Texto Telegram", 0)
    link(c, "¿Reclamada?", "Anotar ignorada", 1)
    link(c, "Texto Telegram", "¿Bloqueado?")
    link(c, "¿Bloqueado?", "Avisar sin aprobar", 0)
    link(c, "¿Bloqueado?", "Avisar", 1)
    link(c, "Avisar", "Id de Telegram", 0)
    link(c, "Avisar", "Fallo aviso", 1)
    link(c, "Avisar sin aprobar", "Id de Telegram", 0)
    link(c, "Avisar sin aprobar", "Fallo aviso", 1)
    link(c, "Id de Telegram", "Guardar botón")
    return pack("03a - Pedir aprobación", nodes, c)


def flow_callback():
    cfg = "$('Configuración').first().json"
    nodes = [
        sticky("Notas botones", 80, 40, "### 03b Botones\n\nTrigger de Telegram, no un Wait. Busca la fila por el message_id guardado en 03a.\n\nSolo vale el chat de `telegram_chat_id` (y, si lo rellenas, las personas de `telegram_user_ids`). Un botón o un texto de otro chat no hace nada y queda apuntado como `telegram_ajeno`.\n\nCada botón es un UPDATE ... WHERE status = 'esperando_aprobacion' (o edición, o error de envío): aprobar dos veces, aprobar tras rechazar o tras vencer no envía nada y el botón lo dice.\n\nEditar pide un texto. Hay que responder a ese mensaje: un texto suelto no se envía a nadie."),
        node("Telegram", "n8n-nodes-base.telegramTrigger", 1.2, 220, 300, {
            "updates": ["callback_query", "message"],
            "additionalFields": {},
        }, "Un solo bot. Sin 'Restrict to Chat IDs': en 2.10.2 descarta los botones. El filtro está en el nodo siguiente.", {"webhookId": nid("wh-telegram-03b")}, "telegram"),
        config_node(460, 300, ["telegram_chat_id", "telegram_user_ids", "n8n_url"]),
        code("Leer update", 700, 300, """
return { json: parseUpdate($json, $('Configuración').first().json) };
""", ("telegram.js",), notes="Comprueba chat.id (y from.id si hay lista) contra la Configuración."),
        bool_if("¿Autorizado?", 920, 300, "={{ $json.authorized }}"),
        bool_if("¿Ajeno?", 1140, 520, "={{ $json.kind !== 'ignore' || $json.chat_id !== String($('Configuración').first().json.telegram_chat_id) }}", "Un mensaje sin texto del dueño (una foto) no se apunta."),
        postgres(
            "Registrar ajeno",
            1360,
            520,
            """INSERT INTO mail_actions (mail_id, action, detail)
VALUES (NULL, 'telegram_ajeno', jsonb_build_object('tipo', $1::text, 'chat_id', $2::text, 'from_id', $3::text, 'boton', $4::text))
RETURNING id""",
            "={{ [$json.kind, $json.chat_id, $json.from_id, $json.data] }}",
            "No se contesta ni se toca ninguna fila. Solo queda apuntado.",
        ),
        switch_if("¿Callback?", 1140, 300, "={{ $json.kind }}", "callback"),
        postgres(
            "Resolver botón",
            1360,
            180,
            """WITH target AS (
  SELECT id, status, injection_flag, COALESCE(final_reply, '') <> '' AS has_final_reply,
         (approval_due_at IS NOT NULL AND approval_due_at <= now()) AS expired
  FROM mail_messages
  WHERE telegram_chat_id = $1 AND telegram_message_id = $2
), expire AS (
  UPDATE mail_messages m SET status = 'aprobacion_vencida'
  FROM target t
  WHERE m.id = t.id AND t.expired AND m.status IN ('esperando_aprobacion', 'esperando_edicion')
  RETURNING m.id
), claimed AS (
  UPDATE mail_messages m
  SET status = CASE $3::text WHEN 'approve' THEN 'aprobado' WHEN 'reject' THEN 'rechazado' ELSE 'esperando_edicion' END
  FROM target t
  WHERE m.id = t.id
    AND $3::text IN ('approve', 'reject', 'edit')
    AND NOT t.expired
    AND m.status IN ('esperando_aprobacion', 'esperando_edicion', 'error_envio')
    AND NOT ($3::text = 'approve' AND m.injection_flag AND COALESCE(m.final_reply, '') = '')
  RETURNING m.id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  SELECT id, 'boton', jsonb_build_object('boton', $3::text, 'aplicado', (SELECT count(*) FROM claimed) > 0, 'estado_previo', status)
  FROM target
  RETURNING id
)
SELECT t.id::text AS id, t.status AS previous_status, COALESCE(t.injection_flag, false) AS injection_flag,
       COALESCE(t.has_final_reply, false) AS has_final_reply, COALESCE(t.expired, false) AS expired,
       (SELECT count(*) FROM claimed)::int AS claimed
FROM (SELECT 1) AS one LEFT JOIN target t ON true""",
            "={{ [$json.chat_id, $json.message_id, $json.data] }}",
            "Transición atómica. Si la fila ya no está en un estado que admita el botón, claimed = 0 y no se hace nada.",
        ),
        code("Qué hacer", 1580, 180, """
const update = $('Leer update').item.json;
const outcome = callbackOutcome($json, update.data);
return { json: { ...update, id: $json.id || null, ...outcome } };
""", ("telegram.js",)),
        node("Responder botón", "n8n-nodes-base.telegram", 1.2, 1800, 180, {
            "resource": "callback",
            "operation": "answerQuery",
            "queryId": "={{ $json.callback_id }}",
            "additionalFields": {"text": "={{ $json.notice }}", "show_alert": "={{ $json.next === 'none' }}"},
        }, "Quita el reloj del botón y dice qué ha pasado. Si ya no hay nada que hacer, sale como alerta.", {"onError": "continueRegularOutput"}, "telegram"),
        switch_if("¿Enviar?", 2020, 180, "={{ $('Qué hacer').item.json.next }}", "send"),
        http_json(
            "Enviar aprobado",
            2240,
            60,
            f"={{{{ {cfg}.n8n_url.replace(/\\/$/, '') + '/webhook/mail-reply' }}}}",
            "={{ JSON.stringify({ mail_id: $('Qué hacer').item.json.id, mode: 'manual' }) }}",
            "mail",
            "El flujo 02 manda el borrador (o tu texto, si lo editaste).",
        ),
        code("Fallo aprobado", 2480, 60, """
const row = $('Qué hacer').item.json;
const raw = $json.error;
return { json: { id: row.id, fallo: String(typeof raw === 'string' ? raw : (raw && raw.message) || 'sin detalle').slice(0, 400) } };
"""),
        switch_if("¿Rechazar?", 2240, 260, "={{ $('Qué hacer').item.json.next }}", "reject"),
        postgres(
            "Apuntar rechazo",
            2480,
            260,
            "INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'rechazado', '{}'::jsonb) RETURNING id",
            "={{ [$('Qué hacer').item.json.id] }}",
        ),
        switch_if("¿Editar?", 2480, 400, "={{ $('Qué hacer').item.json.next }}", "edit"),
        telegram(
            "Pedir texto",
            2700,
            400,
            "={{ $('Qué hacer').item.json.chat_id }}",
            "Responde a este mensaje con el texto corregido. Eso es lo que se enviará.",
            "No espera. La respuesta la coge este mismo flujo, como otro update.",
            force_reply=True,
            reply_to="={{ $('Qué hacer').item.json.message_id }}",
            on_error="continueRegularOutput",
        ),
        postgres(
            "Guardar edición",
            2920,
            400,
            "UPDATE mail_messages SET telegram_edit_id = $2 WHERE id = $1::uuid AND status = 'esperando_edicion' AND $2::text <> '' RETURNING id::text",
            "={{ [$('Qué hacer').item.json.id, $json.result && $json.result.message_id ? String($json.result.message_id) : ''] }}",
        ),
        switch_if("¿Texto?", 1360, 400, "={{ $json.kind }}", "text"),
        postgres(
            "Guardar texto",
            1580,
            640,
            """WITH target AS (
  SELECT id FROM mail_messages
  WHERE telegram_chat_id = $1 AND telegram_edit_id = $2 AND $2::text <> ''
    AND status = 'esperando_edicion'
    AND (approval_due_at IS NULL OR approval_due_at > now())
), upd AS (
  UPDATE mail_messages m SET final_reply = $3, status = 'aprobado'
  FROM target t
  WHERE m.id = t.id AND m.status = 'esperando_edicion'
  RETURNING m.id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  SELECT id, 'editado', '{}'::jsonb FROM upd
  RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$json.chat_id, $json.reply_to, $json.text] }}",
            "Solo vale un texto que responde al mensaje 'Responde a este mensaje...'. esperando_edicion -> aprobado.",
        ),
        bool_if("¿Edición?", 1800, 640, "={{ !!$json.id }}"),
        http_json(
            "Enviar editado",
            2020,
            640,
            f"={{{{ {cfg}.n8n_url.replace(/\\/$/, '') + '/webhook/mail-reply' }}}}",
            "={{ JSON.stringify({ mail_id: $json.id, mode: 'manual' }) }}",
            "mail",
        ),
        code("Fallo editado", 2240, 640, """
const row = $('Guardar texto').item.json;
const raw = $json.error;
return { json: { id: row.id, fallo: String(typeof raw === 'string' ? raw : (raw && raw.message) || 'sin detalle').slice(0, 400) } };
"""),
        telegram(
            "Pista",
            2020,
            820,
            "={{ $('Leer update').item.json.chat_id }}",
            "Ese texto no responde a ninguna edición pendiente y no se envía a nadie. Para corregir un borrador, pulsa Editar y contesta al mensaje que te mando.",
            on_error="continueRegularOutput",
        ),
        postgres(
            "Deshacer aprobación",
            2700,
            60,
            """WITH upd AS (
  UPDATE mail_messages SET status = 'esperando_aprobacion'
  WHERE id = $1::uuid AND status = 'aprobado'
  RETURNING id, from_address, subject
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  VALUES ($1::uuid, 'error_llamada_02', jsonb_build_object('error', $2::text))
  RETURNING id
)
SELECT u.id::text AS id, u.from_address, u.subject, $2::text AS fallo
FROM (SELECT 1) AS one LEFT JOIN upd u ON true""",
            "={{ [$json.id, $json.fallo] }}",
            "El 02 no recibió la petición: la fila vuelve a esperar y se puede pulsar otra vez.",
        ),
        code("Texto fallo", 2920, 60, """
const config = $('Configuración').first().json;
const hint = 'No se ha enviado. ¿Está activo el flujo 02? ¿n8n_url y Mail API Key cuadran? Cuando esté, pulsa Aprobar otra vez: si editaste, sale tu texto.';
return { json: { chat_id: config.telegram_chat_id, text: failureMessage('el flujo 02 no recibió el envío', { ...$json, hint }, $json.fallo) } };
""", ("format.js",)),
        telegram(
            "Avisar fallo",
            3140,
            60,
            "={{ $json.chat_id }}",
            "={{ $json.text }}",
            on_error="continueRegularOutput",
        ),
    ]
    c = {}
    link(c, "Telegram", "Configuración")
    link(c, "Configuración", "Leer update")
    link(c, "Leer update", "¿Autorizado?")
    link(c, "¿Autorizado?", "¿Callback?", 0)
    link(c, "¿Autorizado?", "¿Ajeno?", 1)
    link(c, "¿Ajeno?", "Registrar ajeno", 0)
    link(c, "¿Callback?", "Resolver botón", 0)
    link(c, "¿Callback?", "¿Texto?", 1)
    link(c, "Resolver botón", "Qué hacer")
    link(c, "Qué hacer", "Responder botón")
    link(c, "Responder botón", "¿Enviar?")
    link(c, "¿Enviar?", "Enviar aprobado", 0)
    link(c, "¿Enviar?", "¿Rechazar?", 1)
    link(c, "Enviar aprobado", "Fallo aprobado", 1)
    link(c, "Fallo aprobado", "Deshacer aprobación")
    link(c, "¿Rechazar?", "Apuntar rechazo", 0)
    link(c, "¿Rechazar?", "¿Editar?", 1)
    link(c, "¿Editar?", "Pedir texto", 0)
    link(c, "Pedir texto", "Guardar edición")
    link(c, "¿Texto?", "Guardar texto", 0)
    link(c, "Guardar texto", "¿Edición?")
    link(c, "¿Edición?", "Enviar editado", 0)
    link(c, "¿Edición?", "Pista", 1)
    link(c, "Enviar editado", "Fallo editado", 1)
    link(c, "Fallo editado", "Deshacer aprobación")
    link(c, "Deshacer aprobación", "Texto fallo")
    link(c, "Texto fallo", "Avisar fallo")
    return pack("03b - Botones", nodes, c)


def flow_actions():
    cfg = "$('Configuración').first().json"
    nodes = [
        sticky("Notas acciones", 80, 40, "### 04 Acciones\n\nBug: issue en el repo de pruebas (sin datos de contacto) y acuse en el hilo.\nUrgente: Telegram al momento y acuse.\nLead: se guarda el contacto y el borrador de seguimiento. No se envía solo.\nSpam: se descarta y se apunta.\n\nSi GitHub falla: `error_accion` y aviso a Telegram."),
        webhook("Webhook acción", "mail-action", 220, 300, "POST /webhook/mail-action."),
        config_node(460, 300, ["support_address", "telegram_chat_id", "github_repo", "github_api_url"]),
        code("Leer ruta", 700, 300, uuid_guard("route: String(body.route || '')").replace("valid }", "valid: valid && ['spam', 'lead', 'urgent', 'bug'].includes(String(body.route)) }")),
        bool_if("¿Válida?", 920, 300, "={{ $json.valid }}"),
        postgres(
            "Reclamar",
            1140,
            300,
            """WITH claimed AS (
  UPDATE mail_messages SET status = 'procesando_accion'
  WHERE id = $1::uuid AND status = 'pendiente' AND route = $2::text
  RETURNING id, message_id, from_address, from_name, subject, body_normalized, draft_reply,
            references_header, route, created_at
)
SELECT c.id::text AS id, c.message_id, c.from_address, c.from_name, c.subject, c.body_normalized,
       c.draft_reply, c.references_header, c.route, c.created_at
FROM (SELECT 1) AS one LEFT JOIN claimed c ON true""",
            "={{ [$json.mail_id, $json.route] }}",
            "pendiente -> procesando_accion. Dos llamadas no abren dos issues.",
        ),
        bool_if("¿Reclamada?", 1360, 300, "={{ !!$json.id }}"),
        postgres(
            "Anotar ignorada",
            1580,
            120,
            IGNORED_REQUEST,
            "={{ [$('Leer ruta').item.json.mail_id, '04 ' + $('Leer ruta').item.json.route] }}",
        ),
        switch_if("¿Spam?", 1580, 300, "={{ $json.route }}", "spam"),
        switch_if("¿Lead?", 1800, 460, "={{ $json.route }}", "lead"),
        switch_if("¿Urgente?", 2020, 620, "={{ $json.route }}", "urgent"),
        postgres(
            "Descartar",
            1800,
            200,
            """WITH upd AS (
  UPDATE mail_messages SET status = 'descartado' WHERE id = $1::uuid AND status = 'procesando_accion' RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'descartado', '{}'::jsonb) RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$json.id] }}",
        ),
        postgres(
            "Registrar lead",
            2020,
            400,
            """WITH upd AS (
  UPDATE mail_messages SET status = 'lead_registrado' WHERE id = $1::uuid AND status = 'procesando_accion' RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'lead', '{}'::jsonb) RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$json.id] }}",
            "El contacto está en la fila. El borrador de seguimiento no se envía solo.",
        ),
        code("Texto urgente", 2240, 620, """
const row = $json;
const text = [
  '<b>Urgente</b>',
  'De: ' + escapeHtml(row.from_address),
  'Asunto: ' + escapeHtml(String(row.subject || '').slice(0, 200)),
  '',
  escapeHtml(String(row.body_normalized || '').slice(0, 800)),
].join('\\n');
return { json: { ...row, telegram_text: text, chat_id: $('Configuración').first().json.telegram_chat_id } };
""", ("format.js",)),
        telegram(
            "Avisar urgente",
            2460,
            620,
            "={{ $json.chat_id }}",
            "={{ $json.telegram_text }}",
            "Sale ya. No espera al resumen. Si falla, el acuse sale igual y queda apuntado.",
        ),
        code("Acuse urgente", 2700, 620, """
const row = $('Texto urgente').item.json;
const config = $('Configuración').first().json;
const telegramOk = !$json.error;
return { json: { ...row, telegram_ok: telegramOk, automatic: true, to_address: row.from_address, support_address: config.support_address, outgoing_body: 'Hemos recibido el aviso y lo estamos mirando ahora.', reply_subject: replySubject(row.subject) } };
""", ("format.js",)),
        py_code("Enviar acuse urgente", 2920, 620, """
import os

item = _item["json"]
result = send_reply(
    {
        "to": item.get("to_address"),
        "subject": item.get("reply_subject"),
        "body": item.get("outgoing_body"),
        "message_id": item.get("message_id"),
        "references": item.get("references_header"),
    },
    item.get("support_address"),
    True,
    os.environ,
)
return {"json": {**item, **result}}
""", "Acuse en el mismo hilo."),
        postgres(
            "Cerrar urgente",
            3140,
            620,
            """WITH upd AS (
  UPDATE mail_messages
  SET status = 'urgente_avisado',
      final_reply = CASE WHEN $3::boolean THEN $2 ELSE final_reply END,
      reply_message_id = NULLIF($4::text, '')
  WHERE id = $1::uuid AND status = 'procesando_accion'
  RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  VALUES ($1::uuid, 'urgente', jsonb_build_object('telegram', $5::boolean, 'acuse', $3::boolean))
  RETURNING id
), err AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  SELECT $1::uuid, 'error_acuse', jsonb_build_object('error', $6::text, 'telegram', $5::boolean)
  WHERE NOT $3::boolean OR NOT $5::boolean
  RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$('Acuse urgente').item.json.id, $('Acuse urgente').item.json.outgoing_body, $json.sent === true, $json.reply_message_id || '', $('Acuse urgente').item.json.telegram_ok, String($json.smtp_error || ($json.error && $json.error.message) || $json.error || '').slice(0, 400)] }}",
        ),
        code("Issue", 2240, 820, """
const repo = $('Configuración').first().json.github_repo;
return { json: { ...$json, repo, payload: issuePayload($json) } };
""", ("issue.js",), notes="Título y cuerpo con los datos de contacto tapados. Ni remitente ni mailto: el repo puede ser público."),
        http_json(
            "Crear issue",
            2460,
            820,
            f"={{{{ {cfg}.github_api_url.replace(/\\/$/, '') + '/repos/' + $json.repo + '/issues' }}}}",
            "={{ JSON.stringify($json.payload) }}",
            "github",
            "Token fine-grained, solo issues, repo de pruebas.",
            headers=[("Accept", "application/vnd.github+json"), ("X-GitHub-Api-Version", "2022-11-28"), ("User-Agent", "email-agent-n8n")],
            timeout=30000,
            tries=2,
        ),
        code("Acuse bug", 2700, 820, """
const row = $('Issue').item.json;
const config = $('Configuración').first().json;
const number = $json.number;
const url = $json.html_url;
const text = 'Hemos registrado el problema. Incidencia #' + number + '.\\n' + url;
return { json: { ...row, issue_number: number, issue_url: url, automatic: true, to_address: row.from_address, support_address: config.support_address, outgoing_body: text, reply_subject: replySubject(row.subject) } };
""", ("format.js",)),
        py_code("Enviar acuse bug", 2920, 820, """
import os

item = _item["json"]
result = send_reply(
    {
        "to": item.get("to_address"),
        "subject": item.get("reply_subject"),
        "body": item.get("outgoing_body"),
        "message_id": item.get("message_id"),
        "references": item.get("references_header"),
    },
    item.get("support_address"),
    True,
    os.environ,
)
return {"json": {**item, **result}}
""", "Acuse con el número de la issue, en el mismo hilo."),
        postgres(
            "Cerrar bug",
            3140,
            820,
            """WITH upd AS (
  UPDATE mail_messages
  SET status = 'issue_creada', github_issue_number = $2::int, github_issue_url = $3,
      final_reply = CASE WHEN $5::boolean THEN $4 ELSE final_reply END,
      reply_message_id = NULLIF($6::text, '')
  WHERE id = $1::uuid AND status = 'procesando_accion'
  RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  VALUES ($1::uuid, 'issue', jsonb_build_object('url', $3::text, 'acuse', $5::boolean))
  RETURNING id
), err AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  SELECT $1::uuid, 'error_acuse', jsonb_build_object('error', $7::text)
  WHERE NOT $5::boolean
  RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$('Acuse bug').item.json.id, $('Acuse bug').item.json.issue_number, $('Acuse bug').item.json.issue_url, $('Acuse bug').item.json.outgoing_body, $json.sent === true, $json.reply_message_id || '', String($json.smtp_error || ($json.error && $json.error.message) || $json.error || '').slice(0, 400)] }}",
        ),
        code("Fallo issue", 2700, 1020, """
const row = $('Issue').item.json;
const config = $('Configuración').first().json;
const raw = $json.error;
const error = String(typeof raw === 'string' ? raw : (raw && (raw.message || raw.description)) || 'sin detalle').slice(0, 400);
const hint = 'No se abrió la issue ni se mandó el acuse. Mira el token (permiso Issues) y github_repo. La fila queda en error_accion.';
return { json: { id: row.id, fallo: error, chat_id: config.telegram_chat_id, text: failureMessage('no se pudo crear la issue', { ...row, hint }, error) } };
""", ("format.js",)),
        postgres(
            "Marcar error acción",
            2920,
            1020,
            """WITH upd AS (
  UPDATE mail_messages SET status = 'error_accion' WHERE id = $1::uuid AND status = 'procesando_accion' RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'error_accion', jsonb_build_object('error', $2::text)) RETURNING id
)
SELECT (SELECT id::text FROM upd) AS id""",
            "={{ [$json.id, $json.fallo] }}",
        ),
        telegram(
            "Avisar fallo",
            3140,
            1020,
            "={{ $('Fallo issue').item.json.chat_id }}",
            "={{ $('Fallo issue').item.json.text }}",
            on_error="continueRegularOutput",
        ),
    ]
    c = {}
    link(c, "Webhook acción", "Configuración")
    link(c, "Configuración", "Leer ruta")
    link(c, "Leer ruta", "¿Válida?")
    link(c, "¿Válida?", "Reclamar", 0)
    link(c, "Reclamar", "¿Reclamada?")
    link(c, "¿Reclamada?", "¿Spam?", 0)
    link(c, "¿Reclamada?", "Anotar ignorada", 1)
    link(c, "¿Spam?", "Descartar", 0)
    link(c, "¿Spam?", "¿Lead?", 1)
    link(c, "¿Lead?", "Registrar lead", 0)
    link(c, "¿Lead?", "¿Urgente?", 1)
    link(c, "¿Urgente?", "Texto urgente", 0)
    link(c, "Texto urgente", "Avisar urgente")
    link(c, "Avisar urgente", "Acuse urgente", 0)
    link(c, "Avisar urgente", "Acuse urgente", 1)
    link(c, "Acuse urgente", "Enviar acuse urgente")
    link(c, "Enviar acuse urgente", "Cerrar urgente", 0)
    link(c, "Enviar acuse urgente", "Cerrar urgente", 1)
    link(c, "¿Urgente?", "Issue", 1)
    link(c, "Issue", "Crear issue")
    link(c, "Crear issue", "Acuse bug", 0)
    link(c, "Crear issue", "Fallo issue", 1)
    link(c, "Acuse bug", "Enviar acuse bug")
    link(c, "Enviar acuse bug", "Cerrar bug", 0)
    link(c, "Enviar acuse bug", "Cerrar bug", 1)
    link(c, "Fallo issue", "Marcar error acción")
    link(c, "Marcar error acción", "Avisar fallo")
    return pack("04 - Acciones", nodes, c)


def flow_summary():
    nodes = [
        sticky("Notas resumen", 80, 40, "### 05 Resumen\n\nA las 06:00 UTC (08:00 en Madrid en horario de verano; la instancia del episodio 2 está en UTC).\n\nTambién se puede lanzar con el botón. Vence aprobaciones y ediciones, borra correos viejos (y el log de botones ajenos) y manda números, no un volcado."),
        node("Cada mañana", "n8n-nodes-base.scheduleTrigger", 1.3, 220, 260, {
            "rule": {"interval": [{"field": "days", "daysInterval": 1, "triggerAtHour": 6, "triggerAtMinute": 0}]},
        }, "06:00 UTC."),
        node("Resumen ahora", "n8n-nodes-base.manualTrigger", 1, 220, 460, {}, "Para enseñarlo en cámara sin esperar a mañana."),
        config_node(460, 360, ["retention_days", "telegram_chat_id"]),
        postgres(
            "Vencer",
            700,
            360,
            """WITH expired AS (
  UPDATE mail_messages
  SET status = 'aprobacion_vencida'
  WHERE status IN ('esperando_aprobacion', 'esperando_edicion') AND approval_due_at < now()
  RETURNING id
), log AS (
  INSERT INTO mail_actions (mail_id, action, detail)
  SELECT id, 'vencido', '{}'::jsonb FROM expired
  RETURNING id
)
SELECT count(*)::int AS expired FROM expired""",
            "",
            "Pasado el plazo no se envía. Se marca vencida.",
        ),
        postgres(
            "Purgar",
            940,
            360,
            """WITH purged AS (
  DELETE FROM mail_messages
  WHERE created_at < now() - make_interval(days => GREATEST($1::int, 1))
  RETURNING 1
), orphans AS (
  DELETE FROM mail_actions
  WHERE mail_id IS NULL AND created_at < now() - make_interval(days => GREATEST($1::int, 1))
  RETURNING 1
)
SELECT (SELECT count(*) FROM purged)::int AS purged, (SELECT count(*) FROM orphans)::int AS purged_log""",
            f"={{{{ [$('Configuración').first().json.retention_days] }}}}",
            "Borra el correo y, en cascada, su log. También los botones ajenos viejos. El plazo está en Configuración.",
        ),
        postgres(
            "Contar",
            1180,
            360,
            """SELECT
  count(*) FILTER (WHERE created_at > now() - interval '1 day')::int AS received,
  count(*) FILTER (WHERE status = 'respondido_auto' AND auto_replied_at > now() - interval '1 day')::int AS auto_replied,
  count(*) FILTER (WHERE status = 'respondido_manual' AND updated_at > now() - interval '1 day')::int AS approved,
  count(*) FILTER (WHERE status = 'rechazado' AND updated_at > now() - interval '1 day')::int AS rejected,
  count(*) FILTER (WHERE status = 'lead_registrado' AND updated_at > now() - interval '1 day')::int AS leads,
  count(*) FILTER (WHERE status = 'issue_creada' AND updated_at > now() - interval '1 day')::int AS issues,
  count(*) FILTER (WHERE status = 'descartado' AND updated_at > now() - interval '1 day')::int AS spam,
  count(*) FILTER (WHERE status = 'urgente_avisado' AND updated_at > now() - interval '1 day')::int AS urgent,
  count(*) FILTER (WHERE status = 'ignorado_autorespuesta' AND created_at > now() - interval '1 day')::int AS ignored,
  count(*) FILTER (WHERE status = 'retenido_bucle' AND updated_at > now() - interval '1 day')::int AS held,
  count(*) FILTER (WHERE status IN ('esperando_aprobacion', 'esperando_edicion'))::int AS waiting,
  count(*) FILTER (WHERE status = 'aprobacion_vencida' AND updated_at > now() - interval '1 day')::int AS expired,
  count(*) FILTER (WHERE status IN ('error_interno', 'error_envio', 'error_aviso', 'error_accion'))::int AS errors,
  count(*) FILTER (WHERE status IN ('procesando', 'enviando', 'avisando', 'aprobado', 'procesando_accion')
                   AND updated_at < now() - interval '1 hour')::int AS stuck
FROM mail_messages""",
            "",
            "Errores = filas que siguen en un estado de error. Atascados = a medio camino más de una hora.",
        ),
        code("Redactar", 1420, 360, """
const text = summaryMessage({
  ...$input.first().json,
  purged: $('Purgar').first().json.purged,
});
return { json: { text, chat_id: $('Configuración').first().json.telegram_chat_id } };
""", ("format.js",), each=False),
        telegram("Mandar resumen", 1660, 360, "={{ $json.chat_id }}", "={{ $json.text }}", "Números en líneas cortas.", on_error="stopWorkflow"),
    ]
    c = {}
    link(c, "Cada mañana", "Configuración")
    link(c, "Resumen ahora", "Configuración")
    link(c, "Configuración", "Vencer")
    link(c, "Vencer", "Purgar")
    link(c, "Purgar", "Contar")
    link(c, "Contar", "Redactar")
    link(c, "Redactar", "Mandar resumen")
    return pack("05 - Resumen", nodes, c)


def build():
    return {
        "01-ingesta.json": flow_ingest(),
        "02-respuesta.json": flow_reply(),
        "03a-aprobacion.json": flow_ask(),
        "03b-botones.json": flow_callback(),
        "04-acciones.json": flow_actions(),
        "05-resumen.json": flow_summary(),
    }


def render(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main():
    check = "--check" in sys.argv[1:]
    folder = ROOT / "workflows"
    stale = []
    for name, payload in build().items():
        path = folder / name
        text = render(payload)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
            continue
        folder.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(name, len(payload["nodes"]))
    if check:
        if stale:
            raise SystemExit("JSON desactualizados (ejecuta python3 scripts/build_workflows.py): " + ", ".join(stale))
        print("workflows al día")


if __name__ == "__main__":
    main()
