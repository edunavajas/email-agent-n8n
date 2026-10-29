'use strict';

// La decisión final no se fía del modelo. Si el JSON no parsea, si huele a
// inyección o si el tema tiene consecuencias, no se responde solo.
// Un correo bloqueado (inyección o promesa de dinero) se queda SIN borrador:
// en Telegram no hay botón Aprobar y solo sale lo que escriba una persona.

const CATEGORIES = ['consulta_frecuente', 'bug', 'incidencia_urgente', 'lead', 'spam', 'revision'];

const GRANT_PATTERNS = [
  /te devolvemos/i,
  /le devolvemos el dinero/i,
  /reembolso aprobado/i,
  /hemos abonado/i,
  /refund approved/i,
  /we will refund/i,
  /full refund/i,
];

function clamp(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.min(1, Math.max(0, number));
}

function extractJson(text) {
  const raw = String(text || '').trim();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    const start = raw.indexOf('{');
    const end = raw.lastIndexOf('}');
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(raw.slice(start, end + 1));
      } catch {
        return null;
      }
    }
    return null;
  }
}

function llmPayload(response) {
  if (!response) return '';
  if (typeof response === 'string') return response;
  const content = response.choices && response.choices[0] && response.choices[0].message
    ? response.choices[0].message.content
    : response.content;
  return typeof content === 'string' ? content : JSON.stringify(response);
}

// Trozos del prompt o de las marcas de datos en el borrador: el modelo está
// repitiendo instrucciones o el correo intentó sacarlas. No se envía.
const LEAK_PATTERNS = [
  /correo_no_confiable/i,
  /fuentes_rag/i,
  /eres el clasificador de soporte/i,
  /esquema exacto/i,
];

const MAX_DRAFT = 4000;

// Valida la forma del JSON del modelo. Devuelve null si no es un objeto con
// una categoría en texto y una confianza numérica: eso cuenta como JSON roto.
function validateModelOutput(parsed) {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  if (typeof parsed.categoria !== 'string') return null;
  const confidence = Number(parsed.confianza);
  if (parsed.confianza === null || parsed.confianza === '' || !Number.isFinite(confidence)) return null;
  const text = (value) => (typeof value === 'string' ? value.trim() : '');
  return {
    categoria: CATEGORIES.includes(parsed.categoria.trim()) ? parsed.categoria.trim() : 'revision',
    confianza: clamp(confidence),
    borrador: text(parsed.borrador_respuesta).slice(0, MAX_DRAFT),
    razonamiento: text(parsed.razonamiento).slice(0, 1000),
  };
}

function leaksPrompt(draft) {
  return LEAK_PATTERNS.some((pattern) => pattern.test(String(draft || '')));
}

function isSensitive(text, topics) {
  const haystack = String(text || '').toLowerCase();
  return topics.some((topic) => topic && haystack.includes(String(topic).toLowerCase()));
}

function coversQuestion(body, sources) {
  const normalize = (value) => String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const tokens = normalize(body).split(/[^a-z0-9]+/).filter((word) => word.length > 4);
  if (tokens.length === 0) return false;
  const blob = normalize((sources || []).slice(0, 2).map((source) => `${source.title || ''} ${source.content || ''}`).join(' '));
  const hits = tokens.filter((word) => blob.includes(word));
  return hits.length >= 2 || (hits.length === 1 && tokens.length <= 3);
}

function sourcesAllowGrant(sources) {
  const blob = (sources || []).map((source) => `${source.title || ''}\n${source.content || ''}`).join('\n');
  return /reembolso íntegro|devolución del dinero/i.test(blob);
}

function outputGrantsMoney(draft, sources) {
  if (sourcesAllowGrant(sources)) return false;
  return GRANT_PATTERNS.some((pattern) => pattern.test(String(draft || '')));
}

function decide(input, config) {
  const threshold = Number(config.confidence_threshold ?? 0.75);
  const minScore = Number(config.min_rag_score ?? 0.45);
  const topics = String(config.sensitive_topics || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  const sources = Array.isArray(input.sources) ? input.sources : [];
  const parsed = validateModelOutput(input.parsed);
  const topScore = Number(sources[0] && sources[0].score) || 0;

  if (!parsed) {
    return {
      category: 'revision',
      confidence: 0,
      draft_reply: '',
      reasoning: 'El modelo no devolvió JSON válido. Pasa a una persona.',
      route: 'approval',
      status: 'revision_humana',
      sensitive: false,
      injection: Boolean(input.injection),
      blocked: false,
    };
  }

  const category = parsed.categoria;
  let confidence = parsed.confianza;
  const draft = parsed.borrador;
  const reasoning = parsed.razonamiento;
  const sensitive = isSensitive(`${input.subject}\n${input.body}\n${draft}`, topics);
  const grants = outputGrantsMoney(draft, sources);
  const leak = leaksPrompt(draft);
  const injection = Boolean(input.injection);

  if (injection || grants || leak) {
    const why = injection
      ? 'El correo intenta dar instrucciones al sistema.'
      : grants
        ? 'El borrador prometía una devolución que no está en la base de conocimiento.'
        : 'El borrador repetía instrucciones internas.';
    // El borrador del modelo se tira: pudo escribirlo el atacante. Lo que vea
    // el remitente lo escribirá una persona con el botón Editar.
    return {
      category: 'revision',
      confidence: Math.min(confidence, 0.2),
      draft_reply: '',
      reasoning: (why + ' No hay borrador: responde con Editar o rechaza. ' + reasoning).trim().slice(0, 1000),
      route: 'approval',
      status: 'esperando_aprobacion',
      sensitive,
      injection: true,
      blocked: true,
    };
  }

  if (category === 'spam') {
    return { category, confidence, draft_reply: '', reasoning, route: 'spam', status: 'descartado', sensitive, injection: false, blocked: false };
  }
  if (category === 'bug') {
    return { category, confidence, draft_reply: draft, reasoning, route: 'bug', status: 'pendiente', sensitive, injection: false, blocked: false };
  }
  if (category === 'incidencia_urgente') {
    return { category, confidence, draft_reply: draft, reasoning, route: 'urgent', status: 'pendiente', sensitive, injection: false, blocked: false };
  }
  if (category === 'lead') {
    return { category, confidence, draft_reply: draft, reasoning, route: 'lead', status: 'pendiente', sensitive, injection: false, blocked: false };
  }

  const vague = String(input.body || '').trim().length < 40;
  if (vague) confidence = Math.min(confidence, 0.55);

  if (!draft || sensitive || category !== 'consulta_frecuente' || confidence < threshold || topScore < minScore || sources.length === 0 || !coversQuestion(input.body, sources)) {
    return {
      category: category === 'consulta_frecuente' ? category : 'revision',
      confidence,
      draft_reply: draft,
      reasoning,
      route: 'approval',
      status: 'esperando_aprobacion',
      sensitive,
      injection: false,
      blocked: false,
    };
  }

  return {
    category,
    confidence,
    draft_reply: draft,
    reasoning,
    route: 'auto',
    status: 'pendiente',
    sensitive: false,
    injection: false,
    blocked: false,
  };
}

module.exports = { decide, extractJson, llmPayload, isSensitive, validateModelOutput };
