'use strict';

// Mensaje de usuario para el modelo. Las instrucciones van en el prompt de
// sistema (prompts/clasificador.md). Aquí solo hay datos, entre marcas.
// Si el correo o una fuente traen las propias marcas, se borran: así nadie
// puede cerrar el bloque <correo_no_confiable> y escribir fuera de él.

const DATA_TAGS = /<\s*\/?\s*(correo_no_confiable|fuentes_rag)\b[^>]*>/gi;

function neutralize(value) {
  return String(value ?? '').replace(DATA_TAGS, '[marca eliminada]');
}

function buildUserBlock(email, sources) {
  const list = Array.isArray(sources) ? sources : [];
  const packed = list.map((source, index) => (
    '[' + (index + 1) + '] ' + neutralize(source.title) + ' | ' + (source.updated_at || 'sin fecha') + ' | ' + neutralize(source.canonical_url) + '\n' + neutralize(source.content)
  )).join('\n\n');
  return [
    '<correo_no_confiable>',
    'asunto: ' + neutralize(email.subject),
    'de: ' + neutralize(email.from_address),
    'cuerpo:',
    neutralize(email.body),
    '</correo_no_confiable>',
    '<fuentes_rag>',
    packed || '(sin fragmentos)',
    '</fuentes_rag>',
  ].join('\n');
}

module.exports = { buildUserBlock, neutralize };
