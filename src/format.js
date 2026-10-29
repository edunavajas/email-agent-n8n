'use strict';

// Textos que salen a Telegram y asuntos de respuesta. Todo lo que viene del
// correo se escapa: el mensaje va con parse_mode HTML.

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function formatSources(sources) {
  const list = Array.isArray(sources) ? sources.slice(0, 3) : [];
  if (!list.length) return 'Sin fragmentos en la base de conocimiento.';
  return list.map((source) => {
    const title = source.title || 'Documento';
    const when = source.updated_at ? ` (${String(source.updated_at).slice(0, 10)})` : '';
    const url = source.canonical_url || source.url || '';
    return `• ${title}${when}${url ? `\n  ${url}` : ''}`;
  }).join('\n');
}

// En Telegram un asunto vacío se lee mejor así. El correo que sale no lo lleva.
function shownSubject(subject) {
  return String(subject || '').trim() || '(sin asunto)';
}

function approvalMessage(row) {
  const confidence = Math.round(Number(row.confidence || 0) * 100);
  const draft = String(row.draft_reply || '').slice(0, 900);
  const lines = [
    '<b>Correo para revisar</b>',
    `De: ${escapeHtml(row.from_name ? `${row.from_name} ` : '')}&lt;${escapeHtml(row.from_address)}&gt;`,
    `Asunto: ${escapeHtml(shownSubject(row.subject))}`,
    `Categoría: ${escapeHtml(row.category)}`,
    `Confianza: ${confidence}%`,
  ];
  if (row.injection) {
    lines.push('Aviso: bloqueado. El correo intentó dar instrucciones al sistema o el borrador prometía algo que la base no dice. No hay botón Aprobar: escribe tú la respuesta con Editar, o Rechazar.');
  }
  if (row.sensitive) lines.push('Aviso: habla de precio, plazo, devolución o datos personales. Hace falta una persona.');
  if (row.reasoning) lines.push(`Motivo: ${escapeHtml(String(row.reasoning).slice(0, 300))}`);
  lines.push('', '<b>Borrador</b>', escapeHtml(draft || (row.injection ? '(sin borrador: bloqueado)' : '(vacío)')), '', '<b>Fuentes</b>', escapeHtml(formatSources(row.sources)));
  return lines.join('\n').slice(0, 3900);
}

// Aviso cuando algo falla. Corto y sin el cuerpo del correo.
function failureMessage(what, row, error) {
  const lines = [
    `<b>Fallo: ${escapeHtml(what)}</b>`,
    row && row.from_address ? `De: ${escapeHtml(row.from_address)}` : '',
    row && row.subject ? `Asunto: ${escapeHtml(String(row.subject).slice(0, 200))}` : '',
    row && row.id ? `Fila: <code>${escapeHtml(row.id)}</code>` : '',
    `Error: ${escapeHtml(String(error || 'sin detalle').slice(0, 500))}`,
  ];
  if (row && row.hint) lines.push('', escapeHtml(row.hint));
  return lines.filter((line) => line !== '').join('\n').slice(0, 3900);
}

// Aviso de lead: llega al móvil al momento. Sin botones: no se contesta solo.
function leadMessage(row) {
  const draft = String(row.draft_reply || '').trim().slice(0, 900);
  const lines = [
    '<b>Lead nuevo</b>',
    `De: ${escapeHtml(row.from_name ? `${row.from_name} ` : '')}&lt;${escapeHtml(row.from_address)}&gt;`,
    `Asunto: ${escapeHtml(shownSubject(row.subject).slice(0, 200))}`,
  ];
  if (row.reasoning) lines.push(`Motivo: ${escapeHtml(String(row.reasoning).slice(0, 300))}`);
  lines.push('', '<b>Respuesta sugerida (no enviada)</b>', escapeHtml(draft || '(sin borrador)'), '', 'No se ha contestado: escríbele tú.');
  return lines.join('\n').slice(0, 3900);
}

function summaryMessage(counts) {
  const n = (key) => Number(counts[key] || 0);
  const lines = [
    '<b>Resumen del correo (últimas 24 h)</b>',
    `Recibidos: ${n('received')}`,
    `Respondidos solos: ${n('auto_replied')}`,
    `Aprobados a mano: ${n('approved')}`,
    `Rechazados: ${n('rejected')}`,
    `Leads: ${n('leads')}`,
    `Issues: ${n('issues')}`,
    `Spam registrado: ${n('spam')}`,
    `Urgentes: ${n('urgent')}`,
    `Autorespuestas ignoradas: ${n('ignored')}`,
    `Retenidos por bucle: ${n('held')}`,
    `Esperando aprobación: ${n('waiting')}`,
    `Aprobaciones vencidas: ${n('expired')}`,
    `Con error (míralos): ${n('errors')}`,
    `Atascados más de 1 h: ${n('stuck')}`,
    `Borrados por retención: ${n('purged')}`,
  ];
  return lines.join('\n');
}

// Asunto del correo que sale. Si el del cliente venía vacío, "Re:" a secas:
// con "Re: (sin asunto)" Gmail abre otro hilo aunque In-Reply-To y References
// estén bien. Probado con Gmail real.
function replySubject(subject) {
  const clean = String(subject || '').replace(/[\r\n]+/g, ' ').trim();
  if (!clean) return 'Re:';
  return /^re:/i.test(clean) ? clean : `Re: ${clean}`;
}

module.exports = { approvalMessage, leadMessage, summaryMessage, failureMessage, replySubject, formatSources, escapeHtml };
