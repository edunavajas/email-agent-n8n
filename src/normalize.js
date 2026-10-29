'use strict';

// Convierte el correo del nodo IMAP (o del webhook de prueba) en texto limpio.
// El HTML, la firma y la cadena de respuestas no deben llegar al modelo.

const crypto = require('crypto');

function decodeEntities(value) {
  return String(value || '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)));
}

function htmlToText(html) {
  let text = String(html || '');
  text = text.replace(/<script[\s\S]*?<\/script>/gi, ' ');
  text = text.replace(/<style[\s\S]*?<\/style>/gi, ' ');
  text = text.replace(/<img\b[^>]*>/gi, ' ');
  text = text.replace(/<br\s*\/?>/gi, '\n');
  text = text.replace(/<\/p>/gi, '\n');
  text = text.replace(/<\/div>/gi, '\n');
  text = text.replace(/<\/tr>/gi, '\n');
  text = text.replace(/<[^>]+>/g, ' ');
  return decodeEntities(text);
}

// El nodo IMAP en formato "simple" deja las cabeceras en metadata como
// "valor". En formato "resolved" llegan en headers como "Clave: valor".
// Aquí se queda solo el valor, con la clave en minúsculas.
function headerMap(raw) {
  const metadata = raw.metadata && typeof raw.metadata === 'object' ? raw.metadata : {};
  const headers = raw.headers && typeof raw.headers === 'object' ? raw.headers : {};
  const merged = {};
  for (const [key, value] of Object.entries({ ...metadata, ...headers })) {
    const name = String(key).toLowerCase();
    let text = Array.isArray(value) ? value.join(' ') : String(value ?? '');
    const prefix = name + ':';
    if (text.toLowerCase().startsWith(prefix)) text = text.slice(prefix.length);
    merged[name] = text.replace(/\s+/g, ' ').trim();
  }
  return merged;
}

function isoOrNull(value) {
  const time = Date.parse(value || '');
  if (!Number.isFinite(time)) return null;
  return new Date(time).toISOString();
}

function parseAddress(value) {
  // Formato "resolved" de mailparser: { value: [{ address, name }], text }.
  if (value && typeof value === 'object') {
    const first = Array.isArray(value.value) ? value.value[0] : null;
    if (first && first.address) return { address: String(first.address).trim().toLowerCase(), name: String(first.name || '').trim() };
    value = value.text || '';
  }
  const text = String(value || '').replace(/[\r\n]+/g, ' ').trim();
  const match = text.match(/<([^>]+)>/);
  const address = (match ? match[1] : text).trim().toLowerCase();
  const name = match ? text.slice(0, match.index).replace(/"/g, '').trim() : '';
  return { address, name };
}

function cutQuotedChain(text) {
  const markers = [
    /^-----Original Message-----/im,
    /^_{5,}\s*$/m,
    /^On .+wrote:\s*$/im,
    /^El .+escribi[oó]:\s*$/im,
    /^From:\s.+\nSent:\s/im,
    /^De:\s.+\nEnviado(?: el)?:\s/im,
    /^>+ ?On .+wrote:\s*$/im,
  ];
  let cut = text.length;
  for (const marker of markers) {
    const found = marker.exec(text);
    if (found && found.index < cut) cut = found.index;
  }
  const kept = text.slice(0, cut);
  return kept
    .split('\n')
    .filter((line) => !/^\s*>/.test(line))
    .join('\n');
}

function cutSignature(text) {
  const lines = text.split('\n');
  const cutAt = lines.findIndex((line) => {
    const trimmed = line.trim();
    return trimmed === '--' || trimmed === '—' || /^enviado desde mi /i.test(trimmed) || /^sent from my /i.test(trimmed) || /^get outlook for /i.test(trimmed);
  });
  if (cutAt <= 0) return text;
  return lines.slice(0, cutAt).join('\n');
}

function stripTrackers(text) {
  return text.replace(/https?:\/\/[^\s>]+/gi, (url) => {
    try {
      const parsed = new URL(url);
      for (const key of [...parsed.searchParams.keys()]) {
        if (/^(utm_|mc_|mkt_|fbclid|gclid|vero_)/i.test(key)) parsed.searchParams.delete(key);
      }
      if (/pixel|track|open\.gif|spacer/i.test(parsed.pathname)) return '';
      return parsed.toString();
    } catch {
      return url;
    }
  });
}

function sha256(text) {
  return crypto.createHash('sha256').update(String(text)).digest('hex');
}

// Clave de idempotencia. Si el correo trae Message-ID, es ese. Si no lo trae,
// se calcula con remitente, destinatario, fecha, asunto y cuerpo: el mismo
// correo leído dos veces da la misma clave y no se procesa dos veces.
// Un Message-ID absurdo de largo se resume para que el índice único no falle.
function messageKey(rawId, mail) {
  const id = String(rawId || '').replace(/\s+/g, '').replace(/^<|>$/g, '');
  if (id && id.length <= 400) return { message_id: id, message_id_generated: false };
  if (id) return { message_id: 'largo-' + sha256(id).slice(0, 40), message_id_generated: true };
  const seed = [mail.from_address, mail.to_address, mail.received_at || '', mail.subject, mail.body].join('\n');
  return { message_id: 'generado-' + sha256(seed).slice(0, 40), message_id_generated: true };
}

function normalizeEmail(raw) {
  const source = raw && raw.body && typeof raw.body === 'object' && (raw.body.text || raw.body.textPlain || raw.body.subject || raw.body.from)
    ? raw.body
    : (raw || {});
  const headers = headerMap(source);
  const plain = String(source.textPlain || source.text || (typeof source.body === 'string' ? source.body : '') || '').trim();
  const html = String(source.textHtml || (typeof source.html === 'string' ? source.html : '') || '').trim();
  let body = plain || htmlToText(html);
  body = body.replace(/\r\n/g, '\n').replace(/ /g, ' ');
  body = cutQuotedChain(body);
  body = cutSignature(body);
  body = stripTrackers(body);
  body = body.replace(/[ \t]+\n/g, '\n').replace(/[ \t]{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  if (body.length > 8000) body = body.slice(0, 8000);

  const from = parseAddress(source.from || headers.from || '');
  const to = parseAddress(source.to || headers.to || '');
  const mail = {
    from_address: from.address,
    from_name: from.name.slice(0, 200),
    to_address: to.address,
    subject: String(source.subject || headers.subject || '').replace(/\s+/g, ' ').trim().slice(0, 500),
    body,
    in_reply_to: String(headers['in-reply-to'] || source.inReplyTo || '').trim().slice(0, 1000),
    references_header: String(headers.references || (Array.isArray(source.references) ? source.references.join(' ') : source.references) || '').trim().slice(0, 4000),
    headers,
    received_at: isoOrNull(source.date || headers.date),
  };
  const key = messageKey(headers['message-id'] || source.messageId || source.message_id, mail);
  return { message_id: key.message_id, message_id_generated: key.message_id_generated, ...mail };
}

module.exports = { normalizeEmail, htmlToText, messageKey };
