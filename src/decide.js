'use strict';

// La decisión final no se fía del modelo. Si el JSON no parsea, si huele a
// inyección o si el tema tiene consecuencias, no se responde solo.

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
  const parsed = input.parsed && typeof input.parsed === 'object' ? input.parsed : null;
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

  let category = CATEGORIES.includes(parsed.categoria) ? parsed.categoria : 'revision';
  let confidence = clamp(parsed.confianza);
  let draft = String(parsed.borrador_respuesta || '').trim();
  const reasoning = String(parsed.razonamiento || '').trim();
  const sensitive = isSensitive(`${input.subject}\n${input.body}\n${draft}`, topics);
  const grants = outputGrantsMoney(draft, sources);
  const injection = Boolean(input.injection);

  if (injection || grants) {
    return {
      category: 'revision',
      confidence: Math.min(confidence, 0.2),
      draft_reply: 'Este correo pide saltarse las instrucciones o promete una devolución que no está en la base de conocimiento. No se envía nada automático.',
      reasoning: reasoning || 'Comprobación de salida: el correo no puede dar órdenes.',
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

  if (sensitive || category !== 'consulta_frecuente' || confidence < threshold || topScore < minScore || sources.length === 0 || !coversQuestion(input.body, sources)) {
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

module.exports = { decide, extractJson, llmPayload, isSensitive };
