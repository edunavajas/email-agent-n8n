-- Tablas del agente de correo (episodio 3).
-- Se aplican sobre el mismo PostgreSQL del episodio 2, sin tocar knowledge_*.
-- Identificadores en inglés. Comentarios en español.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Un correo procesado. message_id es la clave de idempotencia.
CREATE TABLE IF NOT EXISTS mail_messages (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id           text NOT NULL UNIQUE,
    from_address         text NOT NULL,
    from_name            text,
    to_address           text,
    subject              text,
    body_normalized      text,
    in_reply_to          text,
    references_header    text,
    category             text,
    confidence           numeric(4,3),
    draft_reply          text,
    final_reply          text,
    reasoning            text,
    rag_sources          jsonb NOT NULL DEFAULT '[]'::jsonb,
    status               text NOT NULL,
    injection_flag       boolean NOT NULL DEFAULT false,
    sensitive_flag       boolean NOT NULL DEFAULT false,
    telegram_chat_id     text,
    telegram_message_id  text,
    telegram_edit_id     text,
    github_issue_number  integer,
    github_issue_url     text,
    approval_due_at      timestamptz,
    route                text,
    reply_message_id     text,
    auto_replied_at      timestamptz,
    received_at          timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT mail_messages_confidence_range
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

-- Si la tabla ya existía con el esquema anterior, se añaden las columnas nuevas.
ALTER TABLE mail_messages ADD COLUMN IF NOT EXISTS route text;
ALTER TABLE mail_messages ADD COLUMN IF NOT EXISTS reply_message_id text;

-- Estados posibles. Cada flujo pasa de uno a otro con un UPDATE ... WHERE
-- status = '<el de antes>': si dos ejecuciones llegan a la vez, solo una gana.
--   01: procesando -> pendiente | ignorado_autorespuesta | error_interno
--   02: pendiente/aprobado -> enviando -> respondido_auto | respondido_manual
--       | retenido_bucle | error_envio
--       (retenido_bucle = freno anti-bucles: el 02 llama enseguida al 03a)
--   03a: pendiente/retenido_bucle -> avisando -> esperando_aprobacion | error_aviso
--   03b: esperando_aprobacion/esperando_edicion/error_envio -> aprobado
--       | rechazado | esperando_edicion | aprobacion_vencida
--   04: pendiente -> procesando_accion -> descartado | lead_registrado
--       | urgente_avisado | issue_creada | error_accion
--   05: esperando_aprobacion/esperando_edicion -> aprobacion_vencida
ALTER TABLE mail_messages DROP CONSTRAINT IF EXISTS mail_messages_status_check;
ALTER TABLE mail_messages ADD CONSTRAINT mail_messages_status_check CHECK (status IN (
    'procesando', 'pendiente', 'ignorado_autorespuesta', 'error_interno',
    'enviando', 'respondido_auto', 'respondido_manual', 'retenido_bucle', 'error_envio',
    'avisando', 'esperando_aprobacion', 'esperando_edicion', 'aprobado', 'rechazado',
    'aprobacion_vencida', 'error_aviso',
    'procesando_accion', 'descartado', 'lead_registrado', 'urgente_avisado', 'issue_creada', 'error_accion'
));
ALTER TABLE mail_messages DROP CONSTRAINT IF EXISTS mail_messages_route_check;
ALTER TABLE mail_messages ADD CONSTRAINT mail_messages_route_check
    CHECK (route IS NULL OR route IN ('auto', 'approval', 'spam', 'lead', 'urgent', 'bug'));

-- Lo que el sistema hizo de verdad: enviar, descartar, abrir issue, avisar.
-- mail_id vacío = algo que no es de un correo (un botón de Telegram de otro chat).
CREATE TABLE IF NOT EXISTS mail_actions (
    id          bigserial PRIMARY KEY,
    mail_id     uuid REFERENCES mail_messages(id) ON DELETE CASCADE,
    action      text NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mail_messages_status_idx
    ON mail_messages (status);
CREATE INDEX IF NOT EXISTS mail_messages_from_auto_idx
    ON mail_messages (from_address, auto_replied_at DESC);
CREATE INDEX IF NOT EXISTS mail_messages_created_idx
    ON mail_messages (created_at DESC);
CREATE INDEX IF NOT EXISTS mail_messages_approval_due_idx
    ON mail_messages (approval_due_at)
    WHERE status = 'esperando_aprobacion';
CREATE UNIQUE INDEX IF NOT EXISTS mail_messages_telegram_uidx
    ON mail_messages (telegram_chat_id, telegram_message_id)
    WHERE telegram_message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS mail_messages_telegram_edit_uidx
    ON mail_messages (telegram_chat_id, telegram_edit_id)
    WHERE telegram_edit_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS mail_actions_mail_idx
    ON mail_actions (mail_id, created_at DESC);
CREATE INDEX IF NOT EXISTS mail_actions_orphan_idx
    ON mail_actions (created_at)
    WHERE mail_id IS NULL;

-- updated_at se mantiene solo. Los flujos no tienen que acordarse.
CREATE OR REPLACE FUNCTION mail_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS mail_messages_touch ON mail_messages;
CREATE TRIGGER mail_messages_touch
    BEFORE UPDATE ON mail_messages
    FOR EACH ROW
    EXECUTE FUNCTION mail_touch_updated_at();
