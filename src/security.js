'use strict';

// El cuerpo de un correo es texto de un desconocido. Estas reglas cortan
// autorespuestas y marcan intentos de inyección antes de gastar el modelo.

const INJECTION_PATTERNS = [
  /ignora (tus |las )?(instrucciones|reglas)/i,
  /ignore (all |any )?(previous|prior|above) instructions/i,
  /olvida (las |tus )?(reglas|instrucciones)/i,
  /system prompt/i,
  /you are now/i,
  /act[uú]a como si no tuvieras/i,
  /responde que (le |nos )?devolvemos el dinero/i,
];

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
  if (['bulk', 'list', 'junk'].includes(precedence)) reasons.push('precedence');
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

module.exports = { inspectMail, looksLikeNoReply };
