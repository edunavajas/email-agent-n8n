'use strict';

// La issue va a un repo de GitHub que puede ser público. Lleva lo mínimo para
// que alguien reproduzca el fallo: asunto y cuerpo con los datos de contacto
// tapados, y una referencia interna. Ni remitente, ni Message-ID, ni mailto.
// Quién escribió se mira en mail_messages con esa referencia.

const REDACTIONS = [
  [/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[correo]'],
  [/\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,4})?\b/g, '[iban]'],
  [/\b(?:\d[ -]?){13,19}\b/g, '[número]'],
  [/(?:\+|00)\d{1,3}[ .-]?\d{2,4}(?:[ .-]?\d{2,4}){2,4}\b/g, '[teléfono]'],
  [/\b[6789]\d{2}[ .-]?\d{3}[ .-]?\d{3}\b/g, '[teléfono]'],
  [/\b\d{8}[A-HJ-NP-TV-Z]\b/gi, '[dni]'],
  [/\b[XYZ]\d{7}[A-HJ-NP-TV-Z]\b/gi, '[nie]'],
];

function stripUrlSecrets(text) {
  // Las URL se quedan (suelen ser la pantalla que falla), sin query ni fragmento:
  // ahí van tokens, correos y sesiones.
  return text.replace(/https?:\/\/[^\s<>"')]+/gi, (url) => {
    try {
      const parsed = new URL(url);
      if (!parsed.search && !parsed.hash && !parsed.username && !parsed.password) return url;
      return parsed.origin + parsed.pathname + (parsed.search || parsed.hash ? ' [parámetros quitados]' : '');
    } catch {
      return '[enlace]';
    }
  });
}

function redactPersonalData(value) {
  let text = stripUrlSecrets(String(value ?? ''));
  for (const [pattern, replacement] of REDACTIONS) text = text.replace(pattern, replacement);
  return text;
}

// El texto del cliente va dentro de un bloque de código: así un @usuario no
// avisa a nadie en GitHub y una imagen en Markdown no se carga.
function fenced(text) {
  const longest = Math.max(2, ...(String(text).match(/`+/g) || ['']).map((run) => run.length));
  const fence = '`'.repeat(longest + 1);
  return fence + 'text\n' + text + '\n' + fence;
}

function issuePayload(row) {
  const subject = redactPersonalData(String(row.subject || '').replace(/\s+/g, ' ').trim()) || 'sin asunto';
  const day = String(row.created_at || row.received_at || '').slice(0, 10);
  const body = redactPersonalData(String(row.body_normalized || '').trim()).slice(0, 4000);
  return {
    title: ('[soporte] ' + subject).slice(0, 100),
    body: [
      `Reportado por correo${day ? ' el ' + day : ''}. Referencia interna: \`${row.id}\``,
      'Los datos de contacto del cliente no se copian aquí: están en `mail_messages` con esa referencia.',
      '',
      fenced(body || '(sin texto)'),
    ].join('\n'),
  };
}

module.exports = { issuePayload, redactPersonalData };
