'use strict';

// El cuerpo de un correo es texto de un desconocido. Estas reglas cortan
// autorespuestas y marcan intentos de inyección antes de gastar el modelo.

const INJECTION_PATTERNS = [
  /ignora (tus |las |todas las )?(instrucciones|reglas)/i,
  /ignore (all |any )?(previous|prior|above) instructions/i,
  /disregard (all |any )?(previous|prior|above) instructions/i,
  /olvida (las |tus |todas las )?(reglas|instrucciones)/i,
  /system prompt/i,
  /you are now/i,
  /eres (ahora )?(otro|un nuevo) asistente/i,
  /act[uú]a como si no tuvieras/i,
  /responde que (le |nos )?devolvemos el dinero/i,
  // Intento de cerrar el bloque de datos y escribir fuera de él.
  /<\s*\/?\s*(correo_no_confiable|fuentes_rag|system|assistant)\b/i,
];

// Una sola dirección, sin comas ni espacios. Si el From trae dos direcciones
// o algo raro, no se contesta: la respuesta podría salir a un tercero.
const ADDRESS = /^[^\s@,;:<>()[\]"'\\]+@[^\s@,;:<>()[\]"'\\]+\.[^\s@,;:<>()[\]"'\\]+$/;

function isValidAddress(address) {
  const value = String(address || '');
  return value.length <= 254 && ADDRESS.test(value);
}

function looksLikeNoReply(address) {
  const value = String(address || '').toLowerCase();
  return /(^|[^a-z])(no-?reply|mailer-daemon|postmaster)@/.test(value);
}

function inspectMail(mail, supportAddress) {
  const headers = mail.headers || {};
  const autoSubmitted = String(headers['auto-submitted'] || '').toLowerCase();
  const reasons = [];
  if (autoSubmitted && autoSubmitted !== 'no') reasons.push('auto-submitted');
  if (headers['x-autoreply'] || headers['x-autorespond'] || headers['x-auto-response-suppress']) {
    reasons.push('x-autoreply');
  }
  if (headers['list-id']) reasons.push('list-id');
  const precedence = String(headers.precedence || '').toLowerCase();
  if (['bulk', 'list', 'junk', 'auto_reply'].includes(precedence)) reasons.push('precedence');
  if (!isValidAddress(mail.from_address)) reasons.push('remitente-invalido');
  if (looksLikeNoReply(mail.from_address)) reasons.push('no-reply');
  if (supportAddress && mail.from_address === String(supportAddress).toLowerCase()) reasons.push('propio');

  const blob = `${mail.subject}\n${mail.body}`;
  const injection = INJECTION_PATTERNS.some((pattern) => pattern.test(blob));
  return {
    ignore: reasons.length > 0,
    ignore_reason: reasons.join(','),
    injection,
  };
}

module.exports = { inspectMail, looksLikeNoReply, isValidAddress };
