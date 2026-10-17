'use strict';

// Convierte el correo del nodo IMAP (o del webhook de prueba) en texto limpio.
// El HTML, la firma y la cadena de respuestas no deben llegar al modelo.

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

function headerMap(raw) {
  const metadata = raw.metadata && typeof raw.metadata === 'object' ? raw.metadata : {};
  const headers = raw.headers && typeof raw.headers === 'object' ? raw.headers : {};
  const merged = {};
  for (const [key, value] of Object.entries({ ...metadata, ...headers })) {
    merged[String(key).toLowerCase()] = Array.isArray(value) ? value.join(' ') : String(value ?? '');
  }
  return merged;
}

function isoOrNull(value) {
  const time = Date.parse(value || '');
  if (!Number.isFinite(time)) return null;
  return new Date(time).toISOString();
}

function parseAddress(value) {
  const text = String(value || '').trim();
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

function normalizeEmail(raw) {
  const source = raw && raw.body && (raw.body.text || raw.body.textPlain || raw.body.subject || raw.body.from)
    ? raw.body
    : (raw || {});
  const headers = headerMap(source);
  const plain = String(source.textPlain || source.text || source.body || '').trim();
  const html = String(source.textHtml || source.html || '').trim();
  let body = plain || htmlToText(html);
  body = body.replace(/\r\n/g, '\n').replace(/\u00a0/g, ' ');
  body = cutQuotedChain(body);
  body = cutSignature(body);
  body = stripTrackers(body);
  body = body.replace(/[ \t]+\n/g, '\n').replace(/[ \t]{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  if (body.length > 8000) body = body.slice(0, 8000);

  const from = parseAddress(source.from || headers.from || '');
  const to = parseAddress(source.to || headers.to || '');
  const messageId = String(headers['message-id'] || source.message_id || '').trim().replace(/^<|>$/g, '');
  return {
    message_id: messageId,
    from_address: from.address,
    from_name: from.name,
    to_address: to.address,
    subject: String(source.subject || headers.subject || '').replace(/\s+/g, ' ').trim(),
    body,
    in_reply_to: String(headers['in-reply-to'] || '').trim(),
    references_header: String(headers.references || '').trim(),
    headers,
    received_at: isoOrNull(source.date || headers.date),
  };
}

module.exports = { normalizeEmail, htmlToText };
