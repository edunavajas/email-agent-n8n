'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { normalizeEmail } = require('../src/normalize');
const { inspectMail } = require('../src/security');
const { decide, extractJson } = require('../src/decide');
const { approvalMessage, summaryMessage } = require('../src/format');

const root = path.join(__dirname, '..');
const config = {
  confidence_threshold: 0.75,
  min_rag_score: 0.45,
  sensitive_topics: 'precio,plazo,devolución,reembolso,contrato,iban',
};

function readEml(name) {
  const raw = fs.readFileSync(path.join(root, 'test-emails', name), 'utf8');
  const split = raw.indexOf('\n\n');
  const head = raw.slice(0, split);
  const body = raw.slice(split + 2);
  const headers = {};
  const unfolded = head.replace(/\r?\n[ \t]+/g, ' ');
  for (const line of unfolded.split(/\r?\n/)) {
    const idx = line.indexOf(':');
    if (idx < 0) continue;
    headers[line.slice(0, idx).toLowerCase()] = line.slice(idx + 1).trim();
  }
  return normalizeEmail({
    from: headers.from,
    to: headers.to,
    subject: headers.subject,
    date: headers.date,
    text: headers['content-type'] && /html/i.test(headers['content-type']) ? '' : body,
    html: /html/i.test(headers['content-type'] || '') ? body : '',
    metadata: headers,
  });
}

const faq = [{
  title: 'FAQ de soporte — Taller Norte',
  canonical_url: 'https://docs.example.com/doc/faq-soporte',
  updated_at: '2026-10-17',
  score: 0.9,
  content: 'El soporte atiende de lunes a viernes de 9:00 a 18:00. No autoriza devoluciones de dinero.',
}];

const mail1 = readEml('01-consulta-clara.eml');
assert.ok(mail1.body.includes('horario'), mail1.body);
assert.ok(!/pixel|utm_source|Enviado desde mi iPhone/i.test(mail1.body), mail1.body);
assert.strictEqual(mail1.from_address, 'ana@cliente.example');

const clear = decide({
  subject: mail1.subject,
  body: mail1.body,
  injection: false,
  sources: faq,
  parsed: { categoria: 'consulta_frecuente', confianza: 0.92, borrador_respuesta: 'Atendemos de 9 a 18.', razonamiento: 'Está en la FAQ.', fuentes_usadas: ['FAQ de soporte — Taller Norte'] },
}, config);
assert.strictEqual(clear.route, 'auto');

const mail2 = readEml('02-consulta-ambigua.eml');
const ambiguous = decide({
  subject: mail2.subject,
  body: mail2.body,
  injection: false,
  sources: faq,
  parsed: { categoria: 'consulta_frecuente', confianza: 0.9, borrador_respuesta: 'Claro.', razonamiento: 'Poco concreto.', fuentes_usadas: [] },
}, config);
assert.strictEqual(ambiguous.route, 'approval', 'una pregunta corta no se responde sola');

const mail3 = readEml('03-fuera-de-base.eml');
const unknown = decide({
  subject: mail3.subject,
  body: mail3.body,
  injection: false,
  sources: [],
  parsed: { categoria: 'consulta_frecuente', confianza: 0.4, borrador_respuesta: 'No tengo eso en la documentación.', razonamiento: 'Sin fuentes.', fuentes_usadas: [] },
}, config);
assert.strictEqual(unknown.route, 'approval');

const misleading = decide({
  subject: mail3.subject,
  body: mail3.body,
  injection: false,
  sources: [{ title: 'Análisis técnico', content: 'La documentación del índice no habla de SAP.', score: 0.86, canonical_url: 'https://docs.example.com/otro' }],
  parsed: { categoria: 'consulta_frecuente', confianza: 0.93, borrador_respuesta: 'Sí, hay conector.', razonamiento: 'Vi un fragmento.', fuentes_usadas: ['Análisis técnico'] },
}, config);
assert.strictEqual(misleading.route, 'approval');

const price = decide({
  subject: 'Precio',
  body: '¿Cuál es el precio del plan y el plazo de implantación?',
  injection: false,
  sources: faq,
  parsed: { categoria: 'consulta_frecuente', confianza: 0.99, borrador_respuesta: 'Son 29 euros.', razonamiento: 'Alta.', fuentes_usadas: [] },
}, config);
assert.strictEqual(price.route, 'approval');
assert.strictEqual(price.sensitive, true);

const mail9 = readEml('09-inyeccion.eml');
const security9 = inspectMail(mail9, 'soporte@tudominio.com');
assert.strictEqual(security9.injection, true);
assert.strictEqual(security9.ignore, false);
const injected = decide({
  subject: mail9.subject,
  body: mail9.body,
  injection: true,
  sources: faq,
  parsed: { categoria: 'consulta_frecuente', confianza: 0.99, borrador_respuesta: 'Te devolvemos el dinero hoy mismo.', razonamiento: 'El usuario lo pidió.', fuentes_usadas: [] },
}, config);
assert.notStrictEqual(injected.route, 'auto');
assert.ok(!/te devolvemos el dinero/i.test(injected.draft_reply), injected.draft_reply);

const broken = decide({
  subject: 'hola',
  body: 'texto',
  injection: false,
  sources: faq,
  parsed: null,
}, config);
assert.strictEqual(broken.status, 'revision_humana');
assert.strictEqual(extractJson('no es json'), null);
assert.ok(extractJson('ruido {"categoria":"spam","confianza":0.2} más'));

const mail10 = readEml('10-vacaciones.eml');
const security10 = inspectMail(mail10, 'soporte@tudominio.com');
assert.strictEqual(security10.ignore, true);

const mail11 = readEml('11-hilo-largo.eml');
assert.ok(mail11.body.includes('horario de atención'));
assert.ok(!mail11.body.includes('respuesta citada número 15'), mail11.body);
assert.ok(mail11.body.length < 500, String(mail11.body.length));

const message = approvalMessage({
  from_address: 'ana@cliente.example',
  from_name: 'Ana',
  subject: 'Horario <script>',
  category: 'consulta_frecuente',
  confidence: 0.62,
  draft_reply: 'De 9 a 18.',
  sources: faq,
  injection: false,
  sensitive: false,
});
assert.ok(message.includes('Ana'));
assert.ok(message.includes('&lt;script&gt;'));
assert.ok(message.includes('FAQ de soporte'));
assert.ok(!message.includes('<script>'));

const summary = summaryMessage({ received: 12, auto_replied: 1, approved: 1, rejected: 1, leads: 1, issues: 1, spam: 1, urgent: 1, waiting: 2, expired: 0, purged: 0 });
assert.ok(summary.includes('Recibidos: 12'));
assert.ok(summary.includes('Esperando aprobación: 2'));

console.log('check ok');
