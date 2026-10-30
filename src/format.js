'use strict';

// Textos que salen a Telegram y asuntos de respuesta. Todo lo que viene del
// correo se escapa: el mensaje va con parse_mode HTML.
// Forma de todos los avisos: emoji y título en negrita, campos "Etiqueta: valor"
// uno por línea, bloques separados por una línea en blanco.

// Telegram corta en 4096. Los avisos se quedan en 3600 para que quepa la línea
// de resultado que se añade al pulsar un botón (withResult).
const TELEGRAM_MAX = 4096;
const MESSAGE_MAX = 3600;

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/"/g, '&quot;');
}

// Recorta sin dejar medio emoji (un surrogate suelto lo rechaza Telegram).
function cut(value, max) {
  const text = String(value ?? '');
  if (text.length <= max) return text;
  let end = Math.max(0, max);
  const code = text.charCodeAt(end - 1);
  if (code >= 0xD800 && code <= 0xDBFF) end -= 1;
  return text.slice(0, end);
}

function quote(text) {
  return `<blockquote>${text}</blockquote>`;
}

// parts: líneas ya escapadas y, como mucho, un bloque largo
// { raw, limit, render(textoEscapado, recortado) }. Si no cabe, se recorta solo
// ese bloque (el cuerpo o el borrador). Cabecera y pie salen siempre enteros.
function fit(parts, max = MESSAGE_MAX) {
  const long = parts.find((part) => typeof part !== 'string');
  const render = (raw, trimmed) => parts
    .map((part) => (typeof part === 'string' ? part : part.render(escapeHtml(raw), trimmed)))
    .join('\n');
  if (!long) return render('', false);
  let raw = String(long.raw ?? '');
  let trimmed = false;
  if (long.limit && raw.length > long.limit) {
    raw = cut(raw, long.limit).trimEnd() + ' […]';
    trimmed = true;
  }
  const full = render(raw, trimmed);
  if (full.length <= max) return full;
  let keep = raw.length - (full.length - max) - 20;
  while (keep > 0) {
    const out = render(cut(raw, keep).trimEnd() + ' […]', true);
    if (out.length <= max) return out;
    keep -= Math.max(10, out.length - max);
  }
  return render('[…]', true);
}

// En Telegram un asunto vacío se lee mejor así. El correo que sale no lo lleva.
function shownSubject(subject) {
  return String(subject || '').trim() || '(sin asunto)';
}

function fromLine(row) {
  const name = cut(String(row.from_name || '').trim(), 120);
  return `De: ${name ? escapeHtml(name) + ' ' : ''}&lt;${escapeHtml(cut(String(row.from_address || ''), 200))}&gt;`;
}

function subjectLine(row) {
  return `Asunto: ${escapeHtml(cut(shownSubject(row.subject), 200))}`;
}

const CATEGORY_LABELS = {
  consulta_frecuente: 'consulta frecuente',
  revision: 'revisión',
  bug: 'bug',
  incidencia_urgente: 'incidencia urgente',
  lead: 'lead',
  spam: 'spam',
};

function categoryLabel(category) {
  return CATEGORY_LABELS[category] || String(category || 'sin categoría');
}

function formatSources(sources) {
  const list = Array.isArray(sources) ? sources.slice(0, 3) : [];
  if (!list.length) return 'Sin fragmentos en la base de conocimiento.';
  return list.map((source) => {
    const title = cut(String(source.title || 'Documento'), 120);
    const when = source.updated_at ? ` (${String(source.updated_at).slice(0, 10)})` : '';
    const url = cut(String(source.canonical_url || source.url || ''), 200);
    return `• ${title}${when}${url ? `\n  ${url}` : ''}`;
  }).join('\n');
}

const LOOP_HOLD_TEXT = 'Retenido por el freno anti-bucles: a esta dirección ya se le contestó automáticamente hace menos de una hora. Revísalo antes de enviar.';
const SENSITIVE_TEXT = 'Tema sensible: habla de precio, plazo, devolución o datos personales. Hace falta una persona.';

// El título dice por qué está bloqueado. decide.js empieza el razonamiento así.
function blockedTitle(reasoning) {
  const text = String(reasoning || '');
  if (/^El borrador prometía una devolución/.test(text)) return 'Bloqueado: el borrador prometía dinero';
  if (/^El borrador repetía instrucciones internas/.test(text)) return 'Bloqueado: el borrador repetía instrucciones internas';
  return 'Bloqueado: intenta dar órdenes';
}

// Fila de mail_messages -> campos de approvalMessage. La usan el 03a al mandar
// el aviso y el 02/03b al rehacerlo para quitarle los botones: sale igual.
function approvalFromRow(row) {
  let sources = row.rag_sources;
  if (typeof sources === 'string') {
    try { sources = JSON.parse(sources); } catch { sources = []; }
  }
  return {
    from_address: row.from_address,
    from_name: row.from_name,
    subject: row.subject,
    category: row.category,
    confidence: row.confidence,
    draft_reply: row.draft_reply,
    reasoning: row.reasoning,
    sources: Array.isArray(sources) ? sources : [],
    injection: row.injection_flag === true,
    sensitive: row.sensitive_flag === true,
    loop_hold: row.loop_hold === true,
  };
}

function approvalMessage(row) {
  const blocked = Boolean(row.injection);
  const parts = blocked
    ? [`🛑 <b>${blockedTitle(row.reasoning)}</b>`, fromLine(row), subjectLine(row)]
    : [
      '📝 <b>Borrador para aprobar</b>',
      fromLine(row),
      subjectLine(row),
      `Categoría: ${escapeHtml(categoryLabel(row.category))} · confianza ${Math.round(Number(row.confidence || 0) * 100)} %`,
    ];
  const warnings = [];
  // El 02 no lo mandó solo: esa dirección ya recibió una respuesta automática hace poco.
  if (row.loop_hold) warnings.push('🔁 ' + LOOP_HOLD_TEXT);
  if (row.sensitive) warnings.push('⚠️ ' + SENSITIVE_TEXT);
  if (warnings.length) parts.push('', ...warnings);
  if (row.reasoning) parts.push('', `Por qué: ${escapeHtml(cut(String(row.reasoning).trim(), 300))}`);
  if (!blocked) {
    const draft = String(row.draft_reply || '').trim();
    parts.push('', '<b>Borrador</b>');
    parts.push(draft
      ? { raw: draft, render: (text, trimmed) => quote(text) + (trimmed ? '\n<i>Recortado para Telegram. El correo sale entero.</i>' : '') }
      : '(vacío: escribe tú la respuesta con Editar)');
  }
  parts.push('', '<b>Fuentes</b>', escapeHtml(formatSources(row.sources)));
  // Bloqueado = sin borrador. Lo que vea el remitente lo escribe una persona.
  if (blocked) parts.push('', 'Sin borrador y sin botón Aprobar: escribe tú la respuesta con Editar, o Rechazar.');
  return fit(parts);
}

// Aviso cuando algo falla. Corto y sin el cuerpo del correo.
function failureMessage(what, row, error) {
  const parts = [`⚠️ <b>Fallo: ${escapeHtml(cut(String(what), 200))}</b>`];
  if (row && row.from_address) parts.push(`De: ${escapeHtml(cut(String(row.from_address), 200))}`);
  if (row && row.subject) parts.push(`Asunto: ${escapeHtml(cut(String(row.subject), 200))}`);
  if (row && row.id) parts.push(`Fila: <code>${escapeHtml(row.id)}</code>`);
  parts.push(`Error: <code>${escapeHtml(cut(String(error || 'sin detalle'), 500))}</code>`);
  if (row && row.hint) parts.push('', `<b>Qué hacer:</b> ${escapeHtml(cut(String(row.hint), 1200))}`);
  return fit(parts);
}

const SEND_FAILURE_HINT = 'Queda en error_envio. Reintentar lo manda otra vez (tu texto si lo editaste). Si nadie pulsa, vence como una aprobación.';

// El aviso del 02 cuando el SMTP falla. Lleva Reintentar, Rechazar y Editar.
function sendFailureMessage(row, error) {
  return failureMessage('no se pudo enviar la respuesta', { ...row, hint: SEND_FAILURE_HINT }, error);
}

// Aviso de lead: llega al móvil al momento. Sin botones: no se contesta solo.
function leadMessage(row) {
  const parts = ['💼 <b>Lead nuevo</b>', fromLine(row), subjectLine(row)];
  if (row.reasoning) parts.push(`Motivo: ${escapeHtml(cut(String(row.reasoning).trim(), 300))}`);
  const draft = String(row.draft_reply || '').trim();
  parts.push('', '<b>Respuesta sugerida (no enviada)</b>');
  parts.push(draft
    ? { raw: draft, render: (text, trimmed) => quote(text) + (trimmed ? '\n<i>Recortada para Telegram.</i>' : '') }
    : '(sin borrador)');
  parts.push('', 'No se ha contestado: escríbele tú.');
  return fit(parts);
}

function ackLine(ack, ref) {
  if (!ack || typeof ack.sent !== 'boolean') return [];
  if (ack.sent) return ['', ref ? `📨 Acuse enviado al cliente con la referencia ${ref}.` : '📨 Ya le hemos mandado un acuse automático.'];
  const error = escapeHtml(cut(String(ack.error || 'sin detalle').replace(/\s+/g, ' ').trim(), 200));
  return ['', `⚠️ El acuse automático no salió: ${error}. Escríbele tú${ref ? ` con la referencia ${ref}` : ''}.`];
}

// Urgente: el texto del correo a la vista y si el cliente ya tiene acuse.
function urgentMessage(row, ack) {
  const body = String(row.body_normalized || '').trim();
  const parts = ['🚨 <b>URGENTE</b>', fromLine(row), subjectLine(row), ''];
  parts.push(body
    ? { raw: body, limit: 1500, render: (text, trimmed) => quote(text) + (trimmed ? '\n<i>Recortado. El correo entero está en el buzón.</i>' : '') }
    : '(sin texto)');
  parts.push(...ackLine(ack, ''));
  return fit(parts);
}

// Bug: la issue ya existe. Es un aviso interno: aquí sí va el enlace.
function bugMessage(row, ack) {
  const number = Number(row.issue_number);
  const ref = Number.isInteger(number) && number > 0 ? `#${number}` : '';
  const url = String(row.issue_url || '');
  const shown = ref || 'sin número';
  const issue = /^https:\/\/[^\s"<>]+$/.test(url) ? `<a href="${escapeAttr(url)}">${shown}</a>` : shown;
  const parts = ['🐞 <b>Bug registrado</b>', fromLine(row), `Issue: ${issue}`];
  if (row.issue_title) parts.push(`Título: ${escapeHtml(cut(String(row.issue_title), 200))}`);
  parts.push(...ackLine(ack, ref));
  return fit(parts);
}

// Resumen diario. Secciones; las líneas a 0 no salen, salvo las importantes.
function summaryMessage(counts) {
  const n = (key) => Number(counts[key] || 0);
  const section = (title, rows) => {
    const shown = rows.filter(([, value, always]) => always || value > 0);
    return shown.length ? ['', `<b>${title}</b>`, ...shown.map(([label, value]) => `${label}: ${value}`)] : [];
  };
  const lines = [
    '📊 <b>Resumen de ayer</b>',
    `Recibidos: ${n('received')} (últimas 24 h)`,
    ...section('Contestado', [
      ['Solos', n('auto_replied')],
      ['Aprobados por ti', n('approved')],
      ['Bugs con issue', n('issues')],
      ['Urgentes avisados', n('urgent')],
    ]),
    ...section('Pendiente de ti', [
      ['Esperando aprobación', n('waiting'), true],
      ['Leads por contestar', n('leads')],
    ]),
    ...section('Descartado', [
      ['Rechazados por ti', n('rejected')],
      ['Spam', n('spam')],
      ['Autorespuestas ignoradas', n('ignored')],
    ]),
    ...section('Problemas', [
      ['Con error (míralos)', n('errors'), true],
      ['Atascados más de 1 h', n('stuck')],
      ['Aprobaciones vencidas', n('expired')],
      ['Retenidos por bucle', n('held')],
    ]),
  ];
  if (n('purged')) lines.push('', `Borrados por retención: ${n('purged')}`);
  const plural = (value, one, many) => `${value} ${value === 1 ? one : many}`;
  const todo = [
    n('waiting') ? `${n('waiting')} por aprobar` : '',
    n('leads') ? plural(n('leads'), 'lead', 'leads') : '',
    n('errors') ? `${n('errors')} con error` : '',
    n('stuck') ? plural(n('stuck'), 'atascado', 'atascados') : '',
    n('expired') ? plural(n('expired'), 'vencida', 'vencidas') : '',
  ].filter(Boolean);
  lines.push('', todo.length ? `👉 Te toca: ${todo.join(', ')}.` : '✅ Nada pendiente de ti.');
  return lines.join('\n');
}

// Hora de Madrid sin depender de ICU: UTC+1, y UTC+2 desde el último domingo
// de marzo hasta el último de octubre (a la 01:00 UTC, regla de la UE).
function lastSundayUtc(year, month) {
  const last = new Date(Date.UTC(year, month + 1, 0));
  return last.getUTCDate() - last.getUTCDay();
}

function madridTime(date) {
  const when = new Date(date === undefined ? Date.now() : date);
  const year = when.getUTCFullYear();
  const summerStart = Date.UTC(year, 2, lastSundayUtc(year, 2), 1);
  const summerEnd = Date.UTC(year, 9, lastSundayUtc(year, 9), 1);
  const offset = when.getTime() >= summerStart && when.getTime() < summerEnd ? 2 : 1;
  const local = new Date(when.getTime() + offset * 3600000);
  return String(local.getUTCHours()).padStart(2, '0') + ':' + String(local.getUTCMinutes()).padStart(2, '0');
}

// Línea que se añade al mensaje con botones cuando se decide. telegram.js dice
// qué pasó (la clave); aquí está cómo se lee.
const RESULTS = {
  enviando: '⏳ Aprobado. Enviando…',
  enviado: '✅ Aprobado y enviado',
  enviado_editado: '✅ Enviado con tu texto',
  rechazado: '❌ Rechazado',
  editando: '✏️ Editando: responde al mensaje que te acabo de mandar',
  fallo_envio: '⚠️ Falló el envío',
  fallo_02: '⚠️ Falló el envío: el flujo 02 no recibió la petición',
  ya_respondido: '✅ Ya estaba respondido. No se envía otra vez.',
  ya_rechazado: '❌ Ya estaba rechazado. No se envía nada.',
  vencido: '⌛ Venció el plazo de aprobación. No se envía nada.',
  retenido: '🔁 Retenido por el freno anti-bucles y aún sin pasar a aprobación. Este botón no envía nada.',
  sin_fila: 'ℹ️ Este mensaje ya no corresponde a ningún correo.',
  otro: 'ℹ️ Este botón ya no hace nada.',
};
const RESULT_TAILS = {
  fallo_envio: 'Tienes Reintentar en el aviso de abajo.',
  fallo_02: 'Pulsa Aprobar otra vez cuando esté.',
};

function resultLine(kind, options = {}) {
  let line = RESULTS[kind] || RESULTS.otro;
  if (options.detail) line += ': ' + escapeHtml(cut(String(options.detail).replace(/\s+/g, ' ').trim(), 200));
  if (options.when) line += ' · ' + options.when;
  const tail = options.tail || RESULT_TAILS[kind];
  return tail ? `${line}. ${tail}` : line;
}

function withResult(base, line) {
  return cut(`${base}\n\n${line}`, TELEGRAM_MAX);
}

// Texto que tiene ahora el mensaje con botones de esa fila: el del 03a o, si el
// 02 mandó después un aviso de fallo (y la fila apunta a él), ese aviso.
// on_approval_message y last_send_error salen de mail_actions (ver la SQL).
function currentMessage(row) {
  if (row.on_approval_message === false && row.last_send_error) return sendFailureMessage(row, row.last_send_error);
  return approvalMessage(approvalFromRow(row));
}

// Un botón de un mensaje que ya no tiene fila: se rehace con el texto plano que
// trae el propio botón (Telegram lo manda sin formato).
function plainMessage(text) {
  return escapeHtml(cut(String(text || '').trim(), 3000));
}

// Asunto del correo que sale. Si el del cliente venía vacío, "Re:" a secas:
// con "Re: (sin asunto)" Gmail abre otro hilo aunque In-Reply-To y References
// estén bien. Probado con Gmail real.
function replySubject(subject) {
  const clean = String(subject || '').replace(/[\r\n]+/g, ' ').trim();
  if (!clean) return 'Re:';
  return /^re:/i.test(clean) ? clean : `Re: ${clean}`;
}

module.exports = { approvalMessage, approvalFromRow, leadMessage, urgentMessage, bugMessage, summaryMessage, failureMessage, sendFailureMessage, currentMessage, plainMessage, resultLine, withResult, madridTime, replySubject, formatSources, escapeHtml, cut, TELEGRAM_MAX, MESSAGE_MAX };
