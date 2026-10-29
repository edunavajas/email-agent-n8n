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
  const base = { kind: 'ignore', data: '', callback_id: '', chat_id: '', from_id: '', message_id: '', text: '', reply_to: '' };
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
function callbackOutcome(row, action) {
  if (!ACTIONS.includes(action)) return { next: 'none', notice: 'Botón desconocido.' };
  if (!row || !row.id) return { next: 'none', notice: 'Este mensaje ya no corresponde a ningún correo.' };
  if (Number(row.claimed) > 0) {
    if (action === 'approve') return { next: 'send', notice: 'Aprobado. Enviando la respuesta.' };
    if (action === 'reject') return { next: 'reject', notice: 'Rechazado. No se envía nada.' };
    return { next: 'edit', notice: 'Escribe el texto como respuesta al mensaje que te acabo de mandar.' };
  }
  const status = String(row.previous_status || '');
  if (row.expired && ['esperando_aprobacion', 'esperando_edicion', 'error_envio'].includes(status)) {
    return { next: 'none', notice: 'Venció el plazo de aprobación. No se envía nada.' };
  }
  if (action === 'approve' && row.injection_flag && !row.has_final_reply) {
    return { next: 'none', notice: 'Este correo está bloqueado (intentó dar órdenes o prometía dinero). No se puede aprobar: usa Editar y escribe tú la respuesta.' };
  }
  const notices = {
    aprobado: 'Ya está aprobado y en cola de envío.',
    enviando: 'Ya se está enviando.',
    respondido_auto: 'Ya se respondió. No se envía otra vez.',
    respondido_manual: 'Ya se respondió. No se envía otra vez.',
    rechazado: 'Ya estaba rechazado. No se envía nada.',
    aprobacion_vencida: 'Venció el plazo de aprobación. No se envía nada.',
    retenido_bucle: 'Retenido para no entrar en bucle. No se envía.',
  };
  return { next: 'none', notice: notices[status] || `No se puede hacer eso ahora (estado: ${status || 'desconocido'}).` };
}

module.exports = { parseUpdate, callbackOutcome, idList };
