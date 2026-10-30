'use strict';

// Botones y textos que llegan al bot. Solo cuenta lo que viene del chat del
// dueño (telegram_chat_id). Si además hay telegram_user_ids, la persona que
// pulsa tiene que estar en esa lista (útil si el chat es un grupo).
// Ojo: el filtro "Restrict to Chat IDs" del trigger de Telegram no sirve aquí.
// En n8n 2.10.2 mira message.chat.id, que un callback_query no trae, y
// descartaría todos los botones.

const ACTIONS = ['approve', 'reject', 'edit'];

function idList(value) {
  return String(value ?? '').split(',').map((item) => item.trim()).filter(Boolean);
}

function parseUpdate(update, config) {
  const ownerChat = String(config.telegram_chat_id ?? '').trim();
  const allowedUsers = idList(config.telegram_user_ids);
  const base = { kind: 'ignore', data: '', callback_id: '', chat_id: '', from_id: '', message_id: '', text: '', reply_to: '', message_text: '' };
  let item = base;

  if (update && update.callback_query) {
    const query = update.callback_query;
    const message = query.message || {};
    item = {
      ...base,
      kind: 'callback',
      data: String(query.data || ''),
      callback_id: String(query.id || ''),
      chat_id: message.chat ? String(message.chat.id) : '',
      from_id: query.from ? String(query.from.id) : '',
      message_id: message.message_id !== undefined ? String(message.message_id) : '',
      // Texto del mensaje del botón, sin formato. Solo sirve si ya no hay fila.
      message_text: typeof message.text === 'string' ? message.text.slice(0, 4000) : '',
    };
  } else if (update && update.message && typeof update.message.text === 'string') {
    const message = update.message;
    item = {
      ...base,
      kind: 'text',
      chat_id: message.chat ? String(message.chat.id) : '',
      from_id: message.from ? String(message.from.id) : '',
      message_id: message.message_id !== undefined ? String(message.message_id) : '',
      text: message.text.slice(0, 4000),
      reply_to: message.reply_to_message ? String(message.reply_to_message.message_id) : '',
    };
  } else if (update && update.message) {
    const message = update.message;
    item = { ...base, chat_id: message.chat ? String(message.chat.id) : '', from_id: message.from ? String(message.from.id) : '' };
  }

  // Sin chat configurado (o con el valor de ejemplo) no se autoriza a nadie.
  const configured = /^-?\d+$/.test(ownerChat);
  const chatOk = configured && item.chat_id === ownerChat;
  const userOk = allowedUsers.length === 0 || allowedUsers.includes(item.from_id);
  return { ...item, authorized: chatOk && userOk && item.kind !== 'ignore' };
}

// Qué hacer con un botón según lo que devolvió la transición en SQL.
// row: { id, previous_status, injection_flag, has_final_reply, expired, claimed }
// result: clave de la línea que se añade al mensaje (format.js, resultLine) al
// quitarle los botones. Vacía = el mensaje no se toca: la fila aún admite el
// botón o hay otra ejecución con ella (esa edita el mensaje). timed: con hora.
const STALE_RESULTS = {
  respondido_auto: 'ya_respondido',
  respondido_manual: 'ya_respondido',
  rechazado: 'ya_rechazado',
  aprobacion_vencida: 'vencido',
  retenido_bucle: 'retenido',
};
const IN_FLIGHT = ['avisando', 'esperando_aprobacion', 'esperando_edicion', 'error_envio', 'aprobado', 'enviando'];

function callbackOutcome(row, action) {
  const outcome = (next, notice, result = '', timed = false) => ({ next, notice, result, timed });
  if (!ACTIONS.includes(action)) return outcome('none', 'Botón desconocido.');
  if (!row || !row.id) return outcome('none', 'Este mensaje ya no corresponde a ningún correo.', 'sin_fila');
  if (Number(row.claimed) > 0) {
    if (action === 'approve') return outcome('send', 'Aprobado. Enviando la respuesta.', 'enviando', true);
    if (action === 'reject') return outcome('reject', 'Rechazado. No se envía nada.', 'rechazado', true);
    return outcome('edit', 'Escribe el texto como respuesta al mensaje que te acabo de mandar.', 'editando');
  }
  const status = String(row.previous_status || '');
  if (row.expired && ['esperando_aprobacion', 'esperando_edicion', 'error_envio'].includes(status)) {
    return outcome('none', 'Venció el plazo de aprobación. No se envía nada.', 'vencido');
  }
  if (action === 'approve' && row.injection_flag && !row.has_final_reply) {
    // Rechazar y Editar siguen valiendo: el mensaje se queda con sus botones.
    return outcome('none', 'Este correo está bloqueado (intentó dar órdenes o prometía dinero). No se puede aprobar: usa Editar y escribe tú la respuesta.');
  }
  const notices = {
    aprobado: 'Ya está aprobado y en cola de envío.',
    enviando: 'Ya se está enviando.',
    respondido_auto: 'Ya se respondió. No se envía otra vez.',
    respondido_manual: 'Ya se respondió. No se envía otra vez.',
    rechazado: 'Ya estaba rechazado. No se envía nada.',
    aprobacion_vencida: 'Venció el plazo de aprobación. No se envía nada.',
    // Una fila retenida tiene botones cuando el 03a la pasa a esperando_aprobacion.
    // Si un botón la encuentra aún aquí, es que no llegó a aprobación.
    retenido_bucle: 'Retenido por el freno anti-bucles y aún sin pasar a aprobación. Este botón no envía nada.',
  };
  const notice = notices[status] || `No se puede hacer eso ahora (estado: ${status || 'desconocido'}).`;
  if (IN_FLIGHT.includes(status)) return outcome('none', notice);
  
  return outcome('none', notice, STALE_RESULTS[status] || 'otro');
}

module.exports = { parseUpdate, callbackOutcome, idList };
