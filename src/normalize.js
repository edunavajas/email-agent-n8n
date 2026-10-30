'use strict';

// Convierte el correo del nodo IMAP (o del webhook de prueba) en texto limpio.
// El HTML, la firma y la cadena de respuestas no deben llegar al modelo.

const crypto = require('crypto');

// Acentos rotos del nodo IMAP de n8n 2.10.2 en formato "simple". @n8n/imap
// decodifica el quoted-printable sin pasarle el charset de la parte
// (getPartData llama a PartData.fromData sin él), así que un cuerpo UTF-8 de
// Gmail llega con cada byte leído como latin1: "producciÃ³n", "Â¿cuÃ¡l". El
// asunto llega bien porque va por la cabecera (RFC 2047).
// Se repara solo si tiene pinta de eso, todo el texto cabe en latin1 y la vuelta
// es UTF-8 válido. Un texto correcto ("producción", "São Paulo", emojis) no se toca.
const MOJIBAKE = /[\u00C2-\u00F4][\u0080-\u00BF]/;

// UTF-8 a mano, por si el runner no tuviera Buffer (en n8n 2.10.2 sí lo tiene).
// Cada carácter del texto es un byte. Devuelve null si no es UTF-8 válido.
function decodeUtf8Bytes(text) {
  let out = '';
  for (let i = 0; i < text.length;) {
    const lead = text.charCodeAt(i);
    if (lead < 0x80) {
      out += text[i];
      i += 1;
      continue;
    }
    const size = lead >= 0xC2 && lead <= 0xDF ? 2 : lead >= 0xE0 && lead <= 0xEF ? 3 : lead >= 0xF0 && lead <= 0xF4 ? 4 : 0;
    if (!size || i + size > text.length) return null;
    let code = lead & (size === 2 ? 0x1F : size === 3 ? 0x0F : 0x07);
    for (let k = 1; k < size; k += 1) {
      const next = text.charCodeAt(i + k);
      if ((next & 0xC0) !== 0x80) return null;
      code = (code << 6) | (next & 0x3F);
    }
    if (size === 3 && (code < 0x800 || (code >= 0xD800 && code <= 0xDFFF))) return null;
    if (size === 4 && (code < 0x10000 || code > 0x10FFFF)) return null;
    out += String.fromCodePoint(code);
    i += size;
  }
  return out;
}

// charset de la cabecera Content-Type del correo, solo si es una parte de texto.
// En un multipart (lo normal en Gmail) el charset va en cada parte y aquí no está.
function declaredCharset(headers) {
  const type = String((headers && headers['content-type']) || '');
  if (!/^\s*text\//i.test(type)) return '';
  const match = type.match(/charset\s*=\s*"?([^";\s]+)/i);
  return match ? match[1].toLowerCase() : '';
}

function repairMojibake(value, charset = '') {
  const text = String(value ?? '');
  if (!MOJIBAKE.test(text)) return text;
  // El correo dice que no es UTF-8: lo que llega no es UTF-8 mal leído.
  if (charset && !/^utf-?8$/.test(charset)) return text;
  if (/[^\u0000-\u00FF]/.test(text)) return text;
  const fixed = typeof Buffer === 'function'
    ? Buffer.from(text, 'latin1').toString('utf8')
    : decodeUtf8Bytes(text);
  // Buffer cambia lo inválido por U+FFFD; el texto de entrada no puede traerlo (es latin1).
  if (fixed === null || fixed.includes('\uFFFD')) return text;
  return fixed;
}

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
  // Lo primero: los acentos. Todo lo demás (HTML, firma, citas) ya trabaja con texto bueno.
  const charset = declaredCharset(headers);
  const plain = repairMojibake(source.textPlain || source.text || (typeof source.body === 'string' ? source.body : '') || '', charset).trim();
  const html = repairMojibake(source.textHtml || (typeof source.html === 'string' ? source.html : '') || '', charset).trim();
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

module.exports = { normalizeEmail, htmlToText, messageKey, repairMojibake, decodeUtf8Bytes };
