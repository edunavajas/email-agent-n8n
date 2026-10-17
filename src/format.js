'use strict';

function escapeHtml(value) {
  return String(value || '')
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

function approvalMessage(row) {
  const confidence = Math.round(Number(row.confidence || 0) * 100);
  const draft = String(row.draft_reply || '').slice(0, 900);
  const lines = [
    '<b>Correo para revisar</b>',
    `De: ${escapeHtml(row.from_name ? `${row.from_name} ` : '')}&lt;${escapeHtml(row.from_address)}&gt;`,
    `Asunto: ${escapeHtml(row.subject)}`,
    `Categoría: ${escapeHtml(row.category)}`,
    `Confianza: ${confidence}%`,
  ];
  if (row.injection) lines.push('Aviso: el correo intentó dar instrucciones al sistema. No se ha obedecido.');
  if (row.sensitive) lines.push('Aviso: habla de precio, plazo, devolución o datos personales. Hace falta una persona.');
  lines.push('', '<b>Borrador</b>', escapeHtml(draft || '(vacío)'), '', '<b>Fuentes</b>', escapeHtml(formatSources(row.sources)));
  return lines.join('\n').slice(0, 3900);
}

function summaryMessage(counts) {
  const n = (key) => Number(counts[key] || 0);
  return [
    '<b>Resumen del correo</b>',
    `Recibidos: ${n('received')}`,
    `Respondidos solos: ${n('auto_replied')}`,
    `Aprobados a mano: ${n('approved')}`,
    `Rechazados: ${n('rejected')}`,
    `Leads: ${n('leads')}`,
    `Issues: ${n('issues')}`,
    `Spam registrado: ${n('spam')}`,
    `Urgentes: ${n('urgent')}`,
    `Esperando aprobación: ${n('waiting')}`,
    `Aprobaciones vencidas: ${n('expired')}`,
    `Borrados por retención: ${n('purged')}`,
  ].join('\n');
}

function replySubject(subject) {
  const clean = String(subject || '').trim() || '(sin asunto)';
  return /^re:/i.test(clean) ? clean : `Re: ${clean}`;
}

module.exports = { approvalMessage, summaryMessage, replySubject, formatSources, escapeHtml };
