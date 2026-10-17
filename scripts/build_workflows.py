#!/usr/bin/env python3
"""Genera workflows/*.json a partir de src/ y prompts/. No lleva secretos."""

import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = uuid.UUID("6f0c1a2e-3b4d-4e5f-8a9b-0c1d2e3f4a5b")


def nid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def src(*names: str) -> str:
    chunks = []
    for name in names:
        text = (ROOT / "src" / name).read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if not line.startswith("module.exports")]
        chunks.append("\n".join(lines).strip())
    return "\n\n".join(chunks)


def node(name, type_, version, x, y, parameters, notes="", extra=None):
    item = {
        "parameters": parameters,
        "id": nid(name + type_),
        "name": name,
        "type": type_,
        "typeVersion": version,
        "position": [x, y],
    }
    if notes:
        item["notes"] = notes
    if extra:
        item.update(extra)
    return item


def code(name, x, y, body, files=(), each=True, notes=""):
    prefix = src(*files)
    script = f"{prefix}\n\n{body.strip()}\n" if prefix else body.strip() + "\n"
    parameters = {"jsCode": script}
    if each:
        parameters["mode"] = "runOnceForEachItem"
    return node(name, "n8n-nodes-base.code", 2, x, y, parameters, notes)


def postgres(name, x, y, query, replacement, notes=""):
    options = {"queryBatching": "independently"}
    if replacement:
        options["queryReplacement"] = replacement
    return node(
        name,
        "n8n-nodes-base.postgres",
        2.5,
        x,
        y,
        {"operation": "executeQuery", "query": query, "options": options},
        notes,
        {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000},
    )


def http_json(name, x, y, url, body_expr, notes="", text=False):
    response = {"response": {"responseFormat": "text", "outputPropertyName": "rag_raw"}} if text else {"response": {"responseFormat": "json"}}
    return node(
        name,
        "n8n-nodes-base.httpRequest",
        4.2,
        x,
        y,
        {
            "method": "POST",
            "url": url,
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body_expr,
            "options": {"timeout": 120000, "response": response},
        },
        notes,
        {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000, "onError": "continueErrorOutput"},
    )


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


def sticky(name, x, y, content, width=560, height=220):
    return node(
        name,
        "n8n-nodes-base.stickyNote",
        1,
        x,
        y,
        {"content": content, "height": height, "width": width, "color": 5},
    )


def config_node(x, y, fields):
    assignments = []
    for key, value, typ in fields:
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
    )


def link(connections, source, target, output=0, input_index=0):
    connections.setdefault(source, {"main": []})
    while len(connections[source]["main"]) <= output:
        connections[source]["main"].append([])
    connections[source]["main"][output].append({"node": target, "type": "main", "index": input_index})


def pack(name, nodes, connections):
    names = {item["name"] for item in nodes}
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


PROMPT = (ROOT / "prompts" / "clasificador.md").read_text(encoding="utf-8").strip()

BASE_FIELDS = [
    ("support_address", "soporte@tudominio.com", "string"),
    ("company_name", "Taller Norte", "string"),
    ("confidence_threshold", 0.75, "number"),
    ("min_rag_score", 0.45, "number"),
    ("approval_hours", 24, "number"),
    ("retention_days", 90, "number"),
    ("sensitive_topics", "precio,precios,plazo,plazos,contrato,legal,devolución,devolucion,reembolso,dni,iban,tarjeta", "string"),
    ("llm_base_url", "https://api.deepseek.com", "string"),
    ("llm_model", "deepseek-v4-flash", "string"),
    ("rag_url", "https://tu-n8n.example.com/webhook/rag-search", "string"),
    ("n8n_url", "https://tu-n8n.example.com", "string"),
    ("telegram_chat_id", "cambia-esto", "string"),
    ("github_repo", "tu-usuario/email-agent-sandbox", "string"),
    ("prompt", PROMPT, "string"),
]


def flow_ingest():
    nodes = [
        sticky("Notas ingesta", 80, 40, "### 01 Ingesta\n\nIMAP es el disparador real. El webhook `mail-ingest` hace el mismo camino para pruebas, con la cabecera X-MAIL-API-Key.\n\nEl estado queda en Postgres. Aquí no se espera a nadie."),
        node("Correo IMAP", "n8n-nodes-base.emailReadImap", 2.1, 220, 300, {
            "mailbox": "INBOX",
            "postProcessAction": "read",
            "format": "simple",
            "downloadAttachments": False,
            "options": {},
        }, "Bandeja. Formato simple: texto, HTML y cabeceras. Sin adjuntos."),
        webhook("Probar correo", "mail-ingest", 220, 520, "POST /webhook/mail-ingest con el mismo JSON que normaliza el flujo. Solo pruebas."),
        config_node(480, 400, BASE_FIELDS),
        code("Normalizar", 740, 400, """
const mail = normalizeEmail($json);
if (!mail.message_id) {
  const text = [mail.from_address, mail.subject, mail.body].join('|');
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) hash = Math.imul(31, hash) + text.charCodeAt(i) | 0;
  mail.message_id = 'generado-' + (hash >>> 0).toString(16);
}
return { json: mail };
""", ("normalize.js",), notes="Quita HTML, rastreadores, firma y respuestas citadas."),
        code("Filtros", 960, 400, """
const config = $('Configuración').first().json;
const verdict = inspectMail($json, config.support_address);
return { json: { ...$json, ...verdict } };
""", ("security.js",), notes="Autorespuestas, listas y no-reply. Marca inyección, no la obedece."),
        bool_if("¿Ignorar?", 1180, 400, "={{ $json.ignore }}", "Sí: se registra y se acaba. No: sigue."),
        postgres(
            "Guardar ignorado",
            1400,
            560,
            """INSERT INTO mail_messages
  (message_id, from_address, from_name, to_address, subject, body_normalized, status, reasoning, received_at)
VALUES ($1, $2, $3, $4, $5, $6, 'ignorado_autorespuesta', $7, NULLIF($8::text, '')::timestamptz)
ON CONFLICT (message_id) DO NOTHING
RETURNING id""",
            "={{ [$json.message_id, $json.from_address, $json.from_name, $json.to_address, $json.subject, $json.body, $json.ignore_reason, $json.received_at] }}",
            "La autorespuesta queda escrita y no se contesta.",
        ),
        postgres(
            "¿Ya existe?",
            1400,
            280,
            "SELECT EXISTS(SELECT 1 FROM mail_messages WHERE message_id = $1) AS duplicate, $1::text AS message_id",
            "={{ [$json.message_id] }}",
            "La clave es el Message-ID. Un reenvío del mismo id no sigue.",
        ),
        bool_if("¿Duplicado?", 1620, 280, "={{ $json.duplicate }}"),
        postgres(
            "Anotar duplicado",
            1840,
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
            1840,
            400,
            "={{ $('Configuración').first().json.rag_url }}",
            "={{ JSON.stringify({ query: ($json.subject + '\\n' + $json.body).slice(0, 1200), limit: 5, source_type: 'all' }) }}",
            "La respuesta tiene que salir de la base del episodio 2.",
            text=True,
        ),
        code("Unir fuentes", 2080, 400, """
const email = $('Filtros').item.json;
let parsed = [];
const raw = $json.rag_raw || $json.data || '';
if (!$json.error && raw) {
  try { parsed = JSON.parse(raw); } catch (error) { parsed = []; }
}
if (parsed && parsed.error) parsed = [];
if (!Array.isArray(parsed)) parsed = [];
const sources = parsed.slice(0, 5).map((row) => ({
  document_id: row.document_id || null,
  title: row.title || '',
  canonical_url: row.canonical_url || '',
  score: Number(row.score || 0),
  content: String(row.content || '').slice(0, 700),
  source_type: row.source_type || '',
  chunk_index: row.chunk_index,
})).sort((a, b) => b.score - a.score);
return { json: { ...email, sources, source_ids: sources.map((row) => row.document_id).filter(Boolean).join(',') } };
""", notes="Junta los fragmentos. Si el RAG falla, la lista queda vacía y el correo sigue."),
        bool_if("¿Hay ids?", 2300, 400, "={{ $json.source_ids !== '' }}"),
        postgres(
            "Fechas",
            2520,
            280,
            """SELECT COALESCE(string_agg(id::text || '|' || to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD'), ','), '') AS pairs
FROM knowledge_documents
WHERE id = ANY(string_to_array($1, ',')::uuid[])""",
            "={{ [$json.source_ids] }}",
            "El webhook del episodio 2 no trae la fecha. Se lee de knowledge_documents.",
        ),
        code("Mezclar fechas", 2740, 280, """
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
        code("Preparar bloque", 2960, 400, """
const email = $json.sources ? $json : $('Unir fuentes').item.json;
const sources = email.sources || [];
const packed = sources.map((source, index) => (
  '[' + (index + 1) + '] ' + source.title + ' | ' + (source.updated_at || 'sin fecha') + ' | ' + source.canonical_url + '\\n' + source.content
)).join('\\n\\n');
const userBlock = [
  '<correo_no_confiable>',
  'asunto: ' + email.subject,
  'de: ' + email.from_address,
  'cuerpo:',
  email.body,
  '</correo_no_confiable>',
  '<fuentes_rag>',
  packed || '(sin fragmentos)',
  '</fuentes_rag>',
].join('\\n');
return { json: { ...email, user_block: userBlock } };
""", notes="Instrucciones y datos van separados. El correo entra como dato."),
        http_json(
            "Clasificar",
            3180,
            400,
            "={{ $('Configuración').first().json.llm_base_url.replace(/\\/$/, '') + '/chat/completions' }}",
            "={{ JSON.stringify({ model: $('Configuración').first().json.llm_model, temperature: 0, response_format: { type: 'json_object' }, messages: [ { role: 'system', content: $('Configuración').first().json.prompt }, { role: 'user', content: $json.user_block } ] }) }}",
            "JSON estricto. Si no parsea, el correo no se responde solo.",
        ),
        code("Decidir", 3400, 400, """
const base = $('Preparar bloque').item.json;
const config = $('Configuración').first().json;
let raw = '';
let parsed = null;
if (!$json.error) {
  raw = llmPayload($json.rag_raw ? $json.rag_raw : $json);
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
""", ("decide.js",), notes="Capa de salida: inyección, temas sensibles y JSON roto no se envían solos."),
        postgres(
            "Guardar",
            3620,
            400,
            """INSERT INTO mail_messages (
  message_id, from_address, from_name, to_address, subject, body_normalized,
  in_reply_to, references_header, category, confidence, draft_reply, reasoning,
  rag_sources, status, injection_flag, sensitive_flag, received_at
) VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, 'pendiente', $14, $15, NULLIF($16::text, '')::timestamptz
)
ON CONFLICT (message_id) DO NOTHING
RETURNING id::text AS id, message_id""",
            "={{ [$json.message_id, $json.from_address, $json.from_name, $json.to_address, $json.subject, $json.body, $json.in_reply_to, $json.references_header, $json.category, $json.confidence, $json.draft_reply, $json.reasoning, JSON.stringify($json.sources || []), $json.injection, $json.sensitive, $json.received_at] }}",
            "Si el Message-ID ya existe, no devuelve fila y el flujo se para.",
        ),
        code("Con id", 3840, 400, """
const decision = $('Decidir').item.json;
if (!$json.id) return { json: { ...decision, skipped: true } };
return { json: { ...decision, id: $json.id, skipped: false } };
"""),
        bool_if("¿Guardado?", 4060, 400, "={{ !$json.skipped }}"),
        switch_if("¿Auto?", 4280, 400, "={{ $json.route }}", "auto"),
        switch_if("¿Aprobar?", 4500, 520, "={{ $json.route }}", "approval"),
        http_json(
            "Pedir respuesta",
            4720,
            280,
            "={{ $('Configuración').first().json.n8n_url.replace(/\\/$/, '') + '/webhook/mail-reply' }}",
            "={{ JSON.stringify({ mail_id: $json.id, route: 'auto', mode: 'auto' }) }}",
            "Dispara el flujo 02. No envía desde aquí.",
        ),
        http_json(
            "Pedir aprobación",
            4720,
            460,
            "={{ $('Configuración').first().json.n8n_url.replace(/\\/$/, '') + '/webhook/mail-approval' }}",
            "={{ JSON.stringify({ mail_id: $json.id, route: 'approval' }) }}",
            "Dispara el flujo 03a y se acaba. No hay nodo Wait.",
        ),
        http_json(
            "Pedir acción",
            4720,
            660,
            "={{ $('Configuración').first().json.n8n_url.replace(/\\/$/, '') + '/webhook/mail-action' }}",
            "={{ JSON.stringify({ mail_id: $json.id, route: $json.route }) }}",
            "Bug, urgente, lead o spam. El flujo 04 decide.",
        ),
    ]
    c = {}
    link(c, "Correo IMAP", "Configuración")
    link(c, "Probar correo", "Configuración")
    link(c, "Configuración", "Normalizar")
    link(c, "Normalizar", "Filtros")
    link(c, "Filtros", "¿Ignorar?")
    link(c, "¿Ignorar?", "Guardar ignorado", 0)
    link(c, "¿Ignorar?", "¿Ya existe?", 1)
    link(c, "¿Ya existe?", "¿Duplicado?")
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
    return pack("01 - Ingesta", nodes, c)


def flow_reply():
    nodes = [
        sticky("Notas respuesta", 80, 40, "### 02 Respuesta\n\nSolo envía si el flujo 01 lo pide.\n\nEl nodo SMTP de n8n 2.10.2 no acepta In-Reply-To ni References. El asunto sale como Re: y Reply-To apunta al buzón. El hilo estricto de cabeceras no está resuelto en esta versión."),
        webhook("Webhook respuesta", "mail-reply", 220, 300, "POST /webhook/mail-reply. Cabecera X-MAIL-API-Key."),
        config_node(460, 300, BASE_FIELDS),
        code("Leer petición", 700, 300, """
const body = $json.body || $json;
return { json: { mail_id: body.mail_id, mode: body.mode || 'auto' } };
"""),
        postgres(
            "Cargar",
            920,
            300,
            """SELECT id::text, message_id, from_address, subject, draft_reply, final_reply, status,
       in_reply_to, references_header
FROM mail_messages WHERE id = $1::uuid""",
            "={{ [$json.mail_id] }}",
        ),
        code("Preparar envío", 1140, 300, """
const request = $('Leer petición').item.json;
const text = $json.final_reply || $json.draft_reply || '';
return { json: { ...$json, mode: request.mode, outgoing_body: text, reply_subject: replySubject($json.subject) } };
""", ("format.js",)),
        postgres(
            "¿Enviado hace poco?",
            1360,
            300,
            """SELECT count(*)::int AS recent
FROM mail_messages
WHERE from_address = $1
  AND status = 'respondido_auto'
  AND auto_replied_at > now() - interval '1 hour'
  AND id <> $2::uuid""",
            "={{ [$json.from_address, $json.id] }}",
            "No se responde solo dos veces a la misma dirección en una hora.",
        ),
        code("Juntar", 1580, 300, """
const mail = $('Preparar envío').item.json;
return { json: { ...mail, recent: Number($json.recent || 0) } };
"""),
        bool_if("¿Bloquear?", 1800, 300, "={{ $json.mode === 'auto' && $json.recent > 0 }}"),
        postgres(
            "Retener",
            2020,
            160,
            """UPDATE mail_messages SET status = 'retenido_bucle' WHERE id = $1::uuid RETURNING id;
INSERT INTO mail_actions (mail_id, action, detail)
VALUES ($1::uuid, 'retenido_bucle', '{}'::jsonb)""",
            "={{ [$json.id] }}",
            "Dos sentencias: n8n las manda juntas. Si falla, no se envía.",
        ),
        node("Enviar", "n8n-nodes-base.emailSend", 2.1, 2020, 420, {
            "resource": "email",
            "operation": "send",
            "fromEmail": "={{ $('Configuración').first().json.support_address }}",
            "toEmail": "={{ $json.from_address }}",
            "subject": "={{ $json.reply_subject }}",
            "emailFormat": "text",
            "text": "={{ $json.outgoing_body }}",
            "options": {
                "appendAttribution": False,
                "replyTo": "={{ $('Configuración').first().json.support_address }}",
            },
        }, "SMTP. Sin la firma de n8n. Reply-To es el buzón de soporte."),
        code("Tras enviar", 2260, 420, """
const mail = $('Juntar').item.json;
return { json: mail };
"""),
        postgres(
            "Marcar enviado",
            2480,
            420,
            """UPDATE mail_messages
SET status = $2,
    final_reply = $3,
    auto_replied_at = CASE WHEN $2 = 'respondido_auto' THEN now() ELSE auto_replied_at END
WHERE id = $1::uuid
RETURNING id::text""",
            "={{ [$json.id, $json.mode === 'auto' ? 'respondido_auto' : 'respondido_manual', $json.outgoing_body] }}",
        ),
        postgres(
            "Apuntar envío",
            2700,
            420,
            "INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, $2, jsonb_build_object('to', $3::text)) RETURNING id",
            "={{ [$('Tras enviar').item.json.id, $('Tras enviar').item.json.mode === 'auto' ? 'enviado_auto' : 'enviado_manual', $('Tras enviar').item.json.from_address] }}",
        ),
    ]
    # The Retener query with two statements may not return cleanly. Split is safer.
    # Replace Retener with a single update; the action insert is a second node.
    nodes = [item for item in nodes if item["name"] != "Retener"]
    nodes.append(postgres(
        "Retener",
        2020,
        160,
        "UPDATE mail_messages SET status = 'retenido_bucle', reasoning = 'Ya hubo respuesta automática a esta dirección en la última hora.' WHERE id = $1::uuid RETURNING id::text",
        "={{ [$json.id] }}",
    ))
    nodes.append(postgres(
        "Apuntar retén",
        2240,
        160,
        "INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'retenido_bucle', '{}'::jsonb) RETURNING id",
        "={{ [$json.id] }}",
    ))
    c = {}
    link(c, "Webhook respuesta", "Configuración")
    link(c, "Configuración", "Leer petición")
    link(c, "Leer petición", "Cargar")
    link(c, "Cargar", "Preparar envío")
    link(c, "Preparar envío", "¿Enviado hace poco?")
    link(c, "¿Enviado hace poco?", "Juntar")
    link(c, "Juntar", "¿Bloquear?")
    link(c, "¿Bloquear?", "Retener", 0)
    link(c, "Retener", "Apuntar retén")
    link(c, "¿Bloquear?", "Enviar", 1)
    link(c, "Enviar", "Tras enviar")
    link(c, "Tras enviar", "Marcar enviado")
    link(c, "Marcar enviado", "Apuntar envío")
    return pack("02 - Respuesta", nodes, c)


def flow_ask():
    nodes = [
        sticky("Notas aprobación", 80, 40, "### 03a Pedir aprobación\n\nManda el borrador a Telegram y guarda el message_id. Aquí termina.\n\nSi nadie pulsa, el flujo 05 marca la fila como vencida cuando pasa approval_hours. No se envía sola."),
        webhook("Webhook aprobación", "mail-approval", 220, 300, "POST /webhook/mail-approval."),
        config_node(460, 300, BASE_FIELDS),
        code("Leer id", 700, 300, """
const body = $json.body || $json;
return { json: { mail_id: body.mail_id } };
"""),
        postgres(
            "Cargar",
            920,
            300,
            """SELECT id::text, from_address, from_name, subject, category, confidence,
       draft_reply, rag_sources, injection_flag, sensitive_flag
FROM mail_messages WHERE id = $1::uuid""",
            "={{ [$json.mail_id] }}",
        ),
        code("Texto Telegram", 1140, 300, """
const sources = typeof $json.rag_sources === 'string' ? JSON.parse($json.rag_sources) : ($json.rag_sources || []);
const text = approvalMessage({
  from_address: $json.from_address,
  from_name: $json.from_name,
  subject: $json.subject,
  category: $json.category,
  confidence: $json.confidence,
  draft_reply: $json.draft_reply,
  sources,
  injection: $json.injection_flag,
  sensitive: $json.sensitive_flag,
});
return { json: { ...$json, telegram_text: text, chat_id: $('Configuración').first().json.telegram_chat_id } };
""", ("format.js",), notes="Remitente, asunto, categoría, confianza, borrador y fuentes. Cabe en el móvil."),
        node("Avisar", "n8n-nodes-base.telegram", 1.2, 1380, 300, {
            "resource": "message",
            "operation": "sendMessage",
            "chatId": "={{ $json.chat_id }}",
            "text": "={{ $json.telegram_text }}",
            "replyMarkup": "inlineKeyboard",
            "inlineKeyboard": {
                "rows": [{
                    "row": {
                        "buttons": [
                            {"text": "Aprobar", "additionalFields": {"callback_data": "approve"}},
                            {"text": "Rechazar", "additionalFields": {"callback_data": "reject"}},
                            {"text": "Editar", "additionalFields": {"callback_data": "edit"}},
                        ]
                    }
                }]
            },
            "additionalFields": {"parse_mode": "HTML", "appendAttribution": False},
        }, "Botones en una fila. El callback_data es corto a propósito."),
        code("Id de Telegram", 1620, 300, """
const mail = $('Texto Telegram').item.json;
const messageId = $json.result && $json.result.message_id ? String($json.result.message_id) : String($json.message_id || '');
return { json: { id: mail.id, chat_id: String(mail.chat_id), telegram_message_id: messageId, hours: $('Configuración').first().json.approval_hours } };
"""),
        postgres(
            "Guardar botón",
            1840,
            300,
            """UPDATE mail_messages
SET status = 'esperando_aprobacion',
    telegram_chat_id = $2,
    telegram_message_id = $3,
    approval_due_at = now() + make_interval(hours => $4::int)
WHERE id = $1::uuid
RETURNING id::text""",
            "={{ [$json.id, $json.chat_id, $json.telegram_message_id, $json.hours] }}",
        ),
        postgres(
            "Apuntar",
            2060,
            300,
            "INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'pedido_aprobacion', jsonb_build_object('telegram_message_id', $2::text)) RETURNING id",
            "={{ [$json.id, $('Id de Telegram').item.json.telegram_message_id] }}",
        ),
    ]
    c = {}
    for a, b in [
        ("Webhook aprobación", "Configuración"),
        ("Configuración", "Leer id"),
        ("Leer id", "Cargar"),
        ("Cargar", "Texto Telegram"),
        ("Texto Telegram", "Avisar"),
        ("Avisar", "Id de Telegram"),
        ("Id de Telegram", "Guardar botón"),
        ("Guardar botón", "Apuntar"),
    ]:
        link(c, a, b)
    return pack("03a - Pedir aprobación", nodes, c)


def flow_callback():
    nodes = [
        sticky("Notas botones", 80, 40, "### 03b Botones\n\nTrigger de Telegram, no un Wait. Busca la fila por el message_id guardado en 03a.\n\nEditar pide un texto nuevo. Ese texto llega como otro update, y este mismo flujo lo envía."),
        node("Telegram", "n8n-nodes-base.telegramTrigger", 1.2, 220, 300, {
            "updates": ["callback_query", "message"],
            "additionalFields": {},
        }, "Un solo bot. Telegram no deja dos triggers del mismo bot."),
        config_node(460, 300, BASE_FIELDS),
        code("Leer update", 700, 300, """
const update = $json;
if (update.callback_query) {
  const query = update.callback_query;
  return { json: {
    kind: 'callback',
    data: query.data,
    callback_id: query.id,
    chat_id: String(query.message.chat.id),
    message_id: String(query.message.message_id),
    text: '',
    reply_to: '',
  } };
}
const message = update.message || {};
if (!message.text) return { json: { kind: 'ignore' } };
return { json: {
  kind: 'text',
  data: '',
  callback_id: '',
  chat_id: String(message.chat.id),
  message_id: String(message.message_id),
  text: String(message.text).slice(0, 4000),
  reply_to: message.reply_to_message ? String(message.reply_to_message.message_id) : '',
} };
"""),
        switch_if("¿Callback?", 920, 300, "={{ $json.kind }}", "callback"),
        switch_if("¿Texto?", 920, 520, "={{ $json.kind }}", "text"),
        node("Quitar reloj", "n8n-nodes-base.telegram", 1.2, 1140, 180, {
            "resource": "callback",
            "operation": "answerQuery",
            "queryId": "={{ $json.callback_id }}",
            "additionalFields": {},
        }, "Para que el botón deje de girar."),
        postgres(
            "Buscar botón",
            1360,
            300,
            """SELECT id::text, draft_reply, status
FROM mail_messages
WHERE telegram_chat_id = $1 AND telegram_message_id = $2
LIMIT 1""",
            "={{ [$('Leer update').item.json.chat_id, $('Leer update').item.json.message_id] }}",
        ),
        code("Unir callback", 1580, 300, """
const update = $('Leer update').item.json;
if (!$json.id) return { json: { ...update, found: false } };
return { json: { ...update, id: $json.id, draft_reply: $json.draft_reply, found: true, status: $json.status } };
"""),
        bool_if("¿Fila?", 1800, 300, "={{ $json.found }}"),
        switch_if("¿Aprobar?", 2020, 220, "={{ $json.data }}", "approve"),
        switch_if("¿Rechazar?", 2240, 360, "={{ $json.data }}", "reject"),
        postgres(
            "Rechazar",
            2460,
            480,
            "UPDATE mail_messages SET status = 'rechazado' WHERE id = $1::uuid RETURNING id::text",
            "={{ [$json.id] }}",
        ),
        postgres(
            "Apuntar rechazo",
            2680,
            480,
            "INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'rechazado', '{}'::jsonb) RETURNING id",
            "={{ [$json.id] }}",
        ),
        node("Pedir texto", "n8n-nodes-base.telegram", 1.2, 2460, 640, {
            "resource": "message",
            "operation": "sendMessage",
            "chatId": "={{ $json.chat_id }}",
            "text": "Responde a este mensaje con el texto corregido. Eso es lo que se enviará.",
            "replyMarkup": "none",
            "additionalFields": {"appendAttribution": False, "reply_to_message_id": "={{ $json.message_id }}"},
        }, "No espera. El siguiente mensaje lo coge este mismo flujo."),
        code("Id edición", 2680, 640, """
const row = $('Unir callback').item.json;
const messageId = $json.result && $json.result.message_id ? String($json.result.message_id) : '';
return { json: { id: row.id, edit_id: messageId } };
"""),
        postgres(
            "Guardar edición",
            2900,
            640,
            "UPDATE mail_messages SET status = 'esperando_edicion', telegram_edit_id = $2 WHERE id = $1::uuid RETURNING id::text",
            "={{ [$json.id, $json.edit_id] }}",
        ),
        http_json(
            "Enviar aprobado",
            2240,
            120,
            "={{ $('Configuración').first().json.n8n_url.replace(/\\/$/, '') + '/webhook/mail-reply' }}",
            "={{ JSON.stringify({ mail_id: $json.id, mode: 'manual' }) }}",
            "El flujo 02 manda el borrador.",
        ),
        postgres(
            "Buscar edición",
            1140,
            640,
            """SELECT id::text
FROM mail_messages
WHERE telegram_chat_id = $1
  AND status = 'esperando_edicion'
  AND ($2 = '' OR telegram_edit_id = $2)
ORDER BY updated_at DESC
LIMIT 1""",
            "={{ [$json.chat_id, $json.reply_to] }}",
        ),
        code("Unir texto", 1360, 640, """
const update = $('Leer update').item.json;
if (!$json.id) return { json: { found: false } };
return { json: { id: $json.id, text: update.text, found: true } };
"""),
        bool_if("¿Edición?", 1580, 640, "={{ $json.found }}"),
        postgres(
            "Guardar texto",
            1800,
            640,
            "UPDATE mail_messages SET final_reply = $2 WHERE id = $1::uuid RETURNING id::text",
            "={{ [$json.id, $json.text] }}",
        ),
        http_json(
            "Enviar editado",
            2020,
            640,
            "={{ $('Configuración').first().json.n8n_url.replace(/\\/$/, '') + '/webhook/mail-reply' }}",
            "={{ JSON.stringify({ mail_id: $json.id, mode: 'manual' }) }}",
        ),
    ]
    c = {}
    link(c, "Telegram", "Configuración")
    link(c, "Configuración", "Leer update")
    link(c, "Leer update", "¿Callback?")
    link(c, "¿Callback?", "Quitar reloj", 0)
    link(c, "¿Callback?", "¿Texto?", 1)
    link(c, "Quitar reloj", "Buscar botón")
    link(c, "Buscar botón", "Unir callback")
    link(c, "Unir callback", "¿Fila?")
    link(c, "¿Fila?", "¿Aprobar?", 0)
    link(c, "¿Aprobar?", "Enviar aprobado", 0)
    link(c, "¿Aprobar?", "¿Rechazar?", 1)
    link(c, "¿Rechazar?", "Rechazar", 0)
    link(c, "Rechazar", "Apuntar rechazo")
    link(c, "¿Rechazar?", "Pedir texto", 1)
    link(c, "Pedir texto", "Id edición")
    link(c, "Id edición", "Guardar edición")
    link(c, "¿Texto?", "Buscar edición", 0)
    link(c, "Buscar edición", "Unir texto")
    link(c, "Unir texto", "¿Edición?")
    link(c, "¿Edición?", "Guardar texto", 0)
    link(c, "Guardar texto", "Enviar editado")
    return pack("03b - Botones", nodes, c)


def flow_actions():
    nodes = [
        sticky("Notas acciones", 80, 40, "### 04 Acciones\n\nBug: acuse + issue en el repo de pruebas.\nUrgente: Telegram al momento y acuse.\nLead: se guarda el contacto y el borrador de seguimiento. No se envía solo.\nSpam: se descarta y se apunta."),
        webhook("Webhook acción", "mail-action", 220, 300, "POST /webhook/mail-action."),
        config_node(460, 300, BASE_FIELDS),
        code("Leer ruta", 700, 300, """
const body = $json.body || $json;
return { json: { mail_id: body.mail_id, route: body.route } };
"""),
        postgres(
            "Cargar",
            920,
            300,
            """SELECT id::text, message_id, from_address, from_name, subject, body_normalized, draft_reply
FROM mail_messages WHERE id = $1::uuid""",
            "={{ [$json.mail_id] }}",
        ),
        code("Unir ruta", 1140, 300, """
const request = $('Leer ruta').item.json;
return { json: { ...$json, route: request.route } };
"""),
        switch_if("¿Spam?", 1360, 300, "={{ $json.route }}", "spam"),
        switch_if("¿Lead?", 1580, 460, "={{ $json.route }}", "lead"),
        switch_if("¿Urgente?", 1800, 620, "={{ $json.route }}", "urgent"),
        postgres(
            "Descartar",
            1580,
            180,
            "UPDATE mail_messages SET status = 'descartado' WHERE id = $1::uuid RETURNING id::text",
            "={{ [$json.id] }}",
        ),
        postgres(
            "Apuntar spam",
            1800,
            180,
            "INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'descartado', '{}'::jsonb) RETURNING id",
            "={{ [$json.id] }}",
        ),
        postgres(
            "Registrar lead",
            1800,
            400,
            "UPDATE mail_messages SET status = 'lead_registrado' WHERE id = $1::uuid RETURNING id::text",
            "={{ [$json.id] }}",
        ),
        postgres(
            "Apuntar lead",
            2020,
            400,
            "INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'lead', jsonb_build_object('from', $2::text)) RETURNING id",
            "={{ [$json.id, $('Unir ruta').item.json.from_address] }}",
        ),
        node("Avisar urgente", "n8n-nodes-base.telegram", 1.2, 2020, 620, {
            "resource": "message",
            "operation": "sendMessage",
            "chatId": "={{ $('Configuración').first().json.telegram_chat_id }}",
            "text": "={{ 'Urgente de ' + $json.from_address + '\\n' + $json.subject + '\\n\\n' + String($json.body_normalized || '').slice(0, 800) }}",
            "additionalFields": {"appendAttribution": False},
        }, "Sale ya. No espera al resumen."),
        code("Acuse urgente", 2260, 620, """
const row = $('Unir ruta').item.json;
return { json: { ...row, outgoing_body: 'Hemos recibido el aviso y lo estamos mirando ahora.', reply_subject: replySubject(row.subject) } };
""", ("format.js",)),
        node("Enviar acuse urgente", "n8n-nodes-base.emailSend", 2.1, 2500, 620, {
            "resource": "email",
            "operation": "send",
            "fromEmail": "={{ $('Configuración').first().json.support_address }}",
            "toEmail": "={{ $json.from_address }}",
            "subject": "={{ $json.reply_subject }}",
            "emailFormat": "text",
            "text": "={{ $json.outgoing_body }}",
            "options": {"appendAttribution": False, "replyTo": "={{ $('Configuración').first().json.support_address }}"},
        }),
        postgres(
            "Cerrar urgente",
            2740,
            620,
            "UPDATE mail_messages SET status = 'urgente_avisado', final_reply = $2 WHERE id = $1::uuid RETURNING id::text",
            "={{ [$('Acuse urgente').item.json.id, $('Acuse urgente').item.json.outgoing_body] }}",
        ),
        code("Issue", 2020, 820, """
const row = $json;
const repo = $('Configuración').first().json.github_repo;
const subject = 'Re: ' + (row.subject || '(sin asunto)');
const mailto = 'mailto:' + row.from_address + '?subject=' + encodeURIComponent(subject);
const payload = {
  title: ('[soporte] ' + (row.subject || 'sin asunto')).slice(0, 100),
  body: [
    'Remitente: ' + (row.from_name || '') + ' <' + row.from_address + '>',
    'Asunto: ' + (row.subject || ''),
    'Message-ID: ' + row.message_id,
    'Referencia: ' + row.id,
    '',
    row.body_normalized || '',
    '',
    'Enlace de vuelta: ' + mailto,
  ].join('\\n'),
};
return { json: { ...row, repo, payload } };
"""),
        node("Crear issue", "n8n-nodes-base.httpRequest", 4.2, 2260, 820, {
            "method": "POST",
            "url": "={{ 'https://api.github.com/repos/' + $json.repo + '/issues' }}",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json.payload) }}",
            "sendHeaders": True,
            "headerParameters": {"parameters": [
                {"name": "Accept", "value": "application/vnd.github+json"},
                {"name": "X-GitHub-Api-Version", "value": "2022-11-28"},
                {"name": "User-Agent", "value": "email-agent-n8n"},
            ]},
            "options": {"timeout": 30000},
        }, "Token fine-grained, solo issues, repo de pruebas.", {"retryOnFail": True, "maxTries": 2, "waitBetweenTries": 2000}),
        code("Acuse bug", 2500, 820, """
const row = $('Issue').item.json;
const number = $json.number;
const url = $json.html_url;
const text = 'Hemos registrado el problema. Incidencia #' + number + '.\\n' + url;
return { json: { ...row, issue_number: number, issue_url: url, outgoing_body: text, reply_subject: replySubject(row.subject) } };
""", ("format.js",)),
        node("Enviar acuse bug", "n8n-nodes-base.emailSend", 2.1, 2740, 820, {
            "resource": "email",
            "operation": "send",
            "fromEmail": "={{ $('Configuración').first().json.support_address }}",
            "toEmail": "={{ $json.from_address }}",
            "subject": "={{ $json.reply_subject }}",
            "emailFormat": "text",
            "text": "={{ $json.outgoing_body }}",
            "options": {"appendAttribution": False, "replyTo": "={{ $('Configuración').first().json.support_address }}"},
        }),
        postgres(
            "Cerrar bug",
            2980,
            820,
            """UPDATE mail_messages
SET status = 'issue_creada', github_issue_number = $2, github_issue_url = $3, final_reply = $4
WHERE id = $1::uuid
RETURNING id::text""",
            "={{ [$('Acuse bug').item.json.id, $('Acuse bug').item.json.issue_number, $('Acuse bug').item.json.issue_url, $('Acuse bug').item.json.outgoing_body] }}",
        ),
        postgres(
            "Apuntar bug",
            3200,
            820,
            "INSERT INTO mail_actions (mail_id, action, detail) VALUES ($1::uuid, 'issue', jsonb_build_object('url', $2::text)) RETURNING id",
            "={{ [$('Acuse bug').item.json.id, $('Acuse bug').item.json.issue_url] }}",
        ),
    ]
    c = {}
    link(c, "Webhook acción", "Configuración")
    link(c, "Configuración", "Leer ruta")
    link(c, "Leer ruta", "Cargar")
    link(c, "Cargar", "Unir ruta")
    link(c, "Unir ruta", "¿Spam?")
    link(c, "¿Spam?", "Descartar", 0)
    link(c, "Descartar", "Apuntar spam")
    link(c, "¿Spam?", "¿Lead?", 1)
    link(c, "¿Lead?", "Registrar lead", 0)
    link(c, "Registrar lead", "Apuntar lead")
    link(c, "¿Lead?", "¿Urgente?", 1)
    link(c, "¿Urgente?", "Avisar urgente", 0)
    link(c, "Avisar urgente", "Acuse urgente")
    link(c, "Acuse urgente", "Enviar acuse urgente")
    link(c, "Enviar acuse urgente", "Cerrar urgente")
    link(c, "¿Urgente?", "Issue", 1)
    link(c, "Issue", "Crear issue")
    link(c, "Crear issue", "Acuse bug")
    link(c, "Acuse bug", "Enviar acuse bug")
    link(c, "Enviar acuse bug", "Cerrar bug")
    link(c, "Cerrar bug", "Apuntar bug")
    return pack("04 - Acciones", nodes, c)


def flow_summary():
    fields = [field for field in BASE_FIELDS if field[0] in {"telegram_chat_id", "retention_days", "n8n_url"}]
    nodes = [
        sticky("Notas resumen", 80, 40, "### 05 Resumen\n\nA las 06:00 UTC (08:00 en Madrid en horario de verano; la instancia del episodio 2 está en UTC).\n\nTambién se puede lanzar con el botón. Vence aprobaciones, borra correos viejos y manda números, no un volcado."),
        node("Cada mañana", "n8n-nodes-base.scheduleTrigger", 1.3, 220, 260, {
            "rule": {"interval": [{"field": "days", "daysInterval": 1, "triggerAtHour": 6, "triggerAtMinute": 0}]},
        }, "06:00 UTC."),
        node("Resumen ahora", "n8n-nodes-base.manualTrigger", 1, 220, 460, {}, "Para enseñarlo en cámara sin esperar a mañana."),
        config_node(460, 360, fields),
        postgres(
            "Vencer",
            700,
            360,
            """WITH expired AS (
  UPDATE mail_messages
  SET status = 'aprobacion_vencida'
  WHERE status = 'esperando_aprobacion' AND approval_due_at < now()
  RETURNING 1
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
  WHERE created_at < now() - make_interval(days => $1::int)
  RETURNING 1
)
SELECT count(*)::int AS purged FROM purged""",
            "={{ [$('Configuración').first().json.retention_days] }}",
            "Borra el correo y, en cascada, su log. El plazo está en Configuración.",
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
  count(*) FILTER (WHERE status = 'esperando_aprobacion')::int AS waiting
FROM mail_messages""",
            "",
        ),
        code("Redactar", 1420, 360, """
const text = summaryMessage({
  ...$json,
  expired: $('Vencer').first().json.expired,
  purged: $('Purgar').first().json.purged,
});
return { json: { text, chat_id: $('Configuración').first().json.telegram_chat_id } };
""", ("format.js",), each=False),
        node("Mandar resumen", "n8n-nodes-base.telegram", 1.2, 1660, 360, {
            "resource": "message",
            "operation": "sendMessage",
            "chatId": "={{ $json.chat_id }}",
            "text": "={{ $json.text }}",
            "additionalFields": {"parse_mode": "HTML", "appendAttribution": False},
        }, "Números en líneas cortas."),
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


def main():
    flows = {
        "01-ingesta.json": flow_ingest(),
        "02-respuesta.json": flow_reply(),
        "03a-aprobacion.json": flow_ask(),
        "03b-botones.json": flow_callback(),
        "04-acciones.json": flow_actions(),
        "05-resumen.json": flow_summary(),
    }
    folder = ROOT / "workflows"
    folder.mkdir(exist_ok=True)
    for name, payload in flows.items():
        (folder / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(name, len(payload["nodes"]))


if __name__ == "__main__":
    main()
