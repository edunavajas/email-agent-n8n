# email-agent-n8n

Agente de correo del episodio 3 de **Mi Empleado Digital**. Llega un email al buzón del agente (un Gmail gratuito, ver [Buzón: Gmail gratuito](#buzón-gmail-gratuito)), el sistema lo limpia, lo clasifica con la base de conocimiento del episodio 2 y actúa. Lo que no tiene claro se lo pasa a una persona por Telegram. Cada mañana manda un resumen con números.

No es un flujo con un nodo Wait. El estado vive en PostgreSQL. Si n8n se reinicia, el botón de Telegram sigue valiendo porque la fila sigue ahí.

## Los cinco flujos

Son cinco responsabilidades y seis ficheros. El 3 va partido a propósito.

```
Correo IMAP
    │
    ▼
01 Ingesta ── limpia, deduplica, filtra, pregunta al RAG, clasifica
    │
    ├── consulta clara y fuentes reales ──► 02 Respuesta (SMTP, en el hilo) ── respondido_auto
    │                                         └── freno anti-bucles ──► 03a (no sale sola)
    ├── duda, inyección, precio, JSON roto ──► 03a Telegram (Aprobar / Rechazar / Editar)
    │                                              │
    │                                              ▼  el botón llega después, en otra ejecución
    │                                            03b Botones ──► 02 si hay que enviar
    └── bug / urgente / lead / spam ──► 04 Acciones
                                              │
05 Resumen  (06:00 UTC) ──────────────────────┴── números a Telegram
```

| Fichero | Qué hace | Disparo |
|---|---|---|
| `workflows/01-ingesta.json` | Limpia el correo, no lo procesa dos veces, consulta `/webhook/rag-search` y decide la ruta. | IMAP. También `POST /webhook/mail-ingest` para pruebas. |
| `workflows/02-respuesta.json` | Envía por SMTP en el mismo hilo (`In-Reply-To`, `References`) y marca la fila. Si salta el freno anti-bucles, pasa el correo al 03a. Si se aprobó con un botón, marca ese mensaje como enviado (o fallido). | `POST /webhook/mail-reply` |
| `workflows/03a-aprobacion.json` | Manda el borrador a Telegram y guarda el `message_id`. Se acaba. | `POST /webhook/mail-approval`, desde el 01 o el 02 |
| `workflows/03b-botones.json` | Recibe el botón (solo del chat del dueño), busca la fila y envía, descarta o pide el texto corregido. Al decidir, el mensaje se queda sin botones y con lo que pasó. | Telegram |
| `workflows/04-acciones.json` | Issue de GitHub (y aviso del bug a Telegram), aviso urgente, lead (se guarda y avisa por Telegram) o descarte. | `POST /webhook/mail-action` |
| `workflows/05-resumen.json` | Vence aprobaciones, borra lo viejo y manda el resumen. | Cada día a las 06:00 UTC, o el botón "Resumen ahora". |

### Por qué el 3 son dos flujos

Un nodo Wait deja la ejecución en memoria. Si n8n se reinicia, esa ejecución muere y el botón no tiene a quién contestar. Aquí el 03a solo escribe en la fila `telegram_message_id` y `esperando_aprobacion`. El 03b es otro flujo, con el trigger de Telegram. Cuando pulsas, busca la fila por ese id. El estado no está en la ejecución.

Cada paso es un `UPDATE ... WHERE status = '<el de antes>'` en una sola sentencia. Si dos ejecuciones llegan a la vez (un doble toque, un reintento), solo una cambia la fila y la otra no hace nada. Los estados y quién los mueve están al principio de `schema.sql`.

## Instalación

Partes del episodio 2 ya funcionando: Coolify, PostgreSQL + pgvector, n8n 2.10.2 y el webhook `POST /webhook/rag-search`.

0. Prepara el buzón del agente: [Buzón: Gmail gratuito](#buzón-gmail-gratuito). Necesitas la dirección y una contraseña de aplicación de 16 letras.

1. Aplica el esquema en la misma base del episodio 2 (host `knowledge-db`, base `knowledge`):

   ```bash
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema.sql
   ```

   Crea `mail_messages` y `mail_actions`. No toca `knowledge_documents` ni `knowledge_chunks`.

2. Prepara el contenedor de **task runners** para el envío por SMTP (ver [Hilo del correo](#hilo-del-correo)). En Coolify, en el servicio de n8n:
   - Añade al servicio `task-runners` un fichero montado en `/etc/n8n-task-runners.json` con el contenido de `runners/n8n-task-runners.json`. Tiene que poder leerlo el usuario 1000 (permisos 644).
   - Añade al mismo servicio las variables `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER` y `SMTP_PASSWORD` del buzón del agente. Con Gmail: `smtp.gmail.com`, `465`, `ssl`, y usuario y contraseña de aplicación iguales a los de la credencial IMAP. Con otro buzón, ver [Otro buzón](#otro-buzón-hostinger-business-email-o-el-de-vuestra-empresa).
   - Reinicia el servicio. El contenedor de n8n no cambia.

   En el compose del servicio (*Edit Compose File*), el bloque `task-runners` queda así (lo demás, como venía en la plantilla):

   ```yaml
   task-runners:
     image: n8nio/runners:2.10.2
     environment:
       # ... las N8N_RUNNERS_* de la plantilla, sin tocar ...
       - SMTP_HOST=${SMTP_HOST}
       - SMTP_PORT=${SMTP_PORT:-465}
       - SMTP_SECURITY=${SMTP_SECURITY:-ssl}
       - SMTP_USER=${SMTP_USER}
       - SMTP_PASSWORD=${SMTP_PASSWORD}
     volumes:
       - type: bind
         source: ./n8n-task-runners.json
         target: /etc/n8n-task-runners.json
         read_only: true
         content: |
           PEGA AQUÍ EL CONTENIDO DE runners/n8n-task-runners.json (con esta sangría)
   ```

   Coolify crea el fichero con ese contenido al desplegar. Si lo prefieres, añádelo desde la pestaña *Storages* del servicio como *File Mount* con la misma ruta.

3. Crea las credenciales de la tabla de abajo **antes de importar**, con esos nombres exactos. Los nodos piden la credencial por nombre: si existe una con ese nombre y ese tipo, n8n la enlaza sola al importar. Si no, el nodo queda pidiendo credencial y la eliges a mano. El JSON no trae secretos.

4. En n8n: *Workflows → Import from File* y sube los seis JSON de `workflows/`. Entran sin publicar.

5. Abre el nodo **Configuración** de cada flujo y cambia los valores de ejemplo. Cada flujo lleva solo los campos que usa. Es el mismo sitio que en el episodio 2. La plantilla de n8n en Coolify trae `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`, así que un nodo no puede leer `$env`. El `.env` es para el script de pruebas y como lista de lo que tienes que rellenar.

   | Campo | Flujos | Qué poner |
   |---|---|---|
   | `support_address` | 01, 02, 04 | La dirección del buzón del agente, la misma de `SMTP_USER`. Es el From y el Reply-To. Con Gmail, si no coincide, Gmail reescribe el From. |
   | `telegram_chat_id` | todos | Tu chat con el bot (número). Solo ese chat puede pulsar botones. |
   | `telegram_user_ids` | 03b | Vacío si el chat es privado. Si es un grupo, los id de quienes pueden decidir, separados por comas. |
   | `n8n_url` | 01, 02, 03b | `http://localhost:5678`: n8n se llama a sí mismo, sin salir a internet. |
   | `rag_url` | 01 | `http://localhost:5678/webhook/rag-search` si el RAG del episodio 2 vive en el mismo n8n. |
   | `rag_source_type` | 01 | Dónde busca el agente: `repo` (de serie: la FAQ y los documentos de soporte indexados desde el repo), `outline` o `all`. Ver [Dónde busca](#dónde-busca). |
   | `llm_base_url`, `llm_model` | 01 | Ver [Modelo](#modelo). |
   | `github_repo`, `github_api_url` | 04 | `tu-usuario/email-agent-sandbox` y `https://api.github.com`. |
   | `confidence_threshold`, `min_rag_score`, `sensitive_topics` | 01 | Ver [Umbral de confianza](#umbral-de-confianza). |
   | `approval_hours` | 02, 03a | 24. |
   | `retention_days` | 05 | 90. |

6. Indexa `kb/faq-soporte.md` con el flujo 04 del episodio 2 (`POST /webhook/rag-index-repo`) o con el MCP. Ese flujo **exige** `replace_all: true` (sin él da error) y trata el lote como el estado completo del repositorio: borra del índice los documentos `source_type: repo` que no vengan en el lote. No toca los de Outline. Así que:

   - Si la FAQ es tu único documento de repo, mándala con `replace_all: true` sin miedo.
   - Si ya tienes otros documentos de repo, mándalos **todos en el mismo lote**, o desaparecerán del índice.

   ```bash
   jq -n --rawfile content kb/faq-soporte.md '{
     replace_all: true,
     documents: [{
       source_type: "repo",
       external_id: "email-agent/faq-soporte.md",
       title: "FAQ de soporte",
       collection: "repositorio",
       content: $content
     }]
   }' | curl -sS -X POST https://n8n.tudominio.com/webhook/rag-index-repo \
     -H 'X-RAG-API-Key: <clave>' \
     -H 'Content-Type: application/json' \
     --data-binary @-
   ```

   Es asíncrono: responde `Workflow was started` al momento y el indexado tarda unos 20 s. Comprueba con una búsqueda en `/webhook/rag-search` antes de seguir.

7. Publica (*Publish*) los seis flujos: en n8n 2.x publicar es lo que antes era activar. Empieza por 02, 03a, 04 y 03b, y deja el 01 para el final: es el que lee el buzón. El 03b registra el webhook en Telegram al publicarse.

## Buzón: Gmail gratuito

Es la opción por defecto: gratis, sin dominio y sin pagar un buzón aparte. Para un buzón de empresa, ver [Otro buzón](#otro-buzón-hostinger-business-email-o-el-de-vuestra-empresa).

1. Activa la **verificación en dos pasos** de la cuenta de Gmail del agente.
2. Crea una **contraseña de aplicación** en https://myaccount.google.com/apppasswords. Son 16 letras. Pégala **sin espacios**. No es la contraseña de la cuenta.
3. IMAP no hay que tocarlo: según Google, el acceso IMAP siempre está activado en Gmail y las opciones Habilitar/Inhabilitar IMAP se retiraron en enero de 2025. No hay nada que activar en Ajustes.

Dónde va cada cosa:

| Dónde | Qué poner |
|---|---|
| Credencial **IMAP** de n8n | User = la dirección completa de Gmail. Password = la contraseña de aplicación. Host `imap.gmail.com`. Port `993`. SSL/TLS activado. |
| Variables `SMTP_*` del servicio n8n en Coolify (las lee el contenedor `task-runners`) | `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=465`, `SMTP_SECURITY=ssl`, `SMTP_USER` = la dirección, `SMTP_PASSWORD` = la misma contraseña de aplicación. |
| Campo `support_address` del nodo Configuración | Esa misma dirección. Si no coincide con la cuenta que inicia sesión, Gmail reescribe el From. |

### Cuándo no sale la opción de contraseñas de aplicación

No aparece si:

- la verificación en dos pasos usa solo llaves de seguridad,
- la cuenta es de trabajo, de un centro educativo o de una organización (Google Workspace),
- la cuenta tiene activada la Protección Avanzada.

Cambiar la contraseña de la cuenta **revoca todas** las contraseñas de aplicación. Si el agente deja de entrar de un día para otro, mira eso primero. Fuente: https://support.google.com/accounts/answer/185833?hl=es

### Gmail frente a un buzón de dominio

Hechos comprobados en la documentación de Google:

- **Límite de envío**: 500 mensajes al día o 500 destinatarios del mismo correo en una cuenta personal. Al pasarlo, Gmail dice "Has llegado al límite de mensajes que puedes enviar" y se vuelve a enviar con normalidad tras 1 a 24 horas. Para este agente sobra, pero no es un buzón para un volumen alto. Fuente: https://support.google.com/mail/answer/22839?hl=es
- **Clientes IMAP**: hasta 15 conectados a la vez por cuenta. Fuente: https://support.google.com/mail/answer/7126229?hl=es
- **Enviados**: Gmail guarda solo la copia en Enviados de lo que sale por su SMTP. No hace falta ni conviene guardar enviados por IMAP. Lo que se borra desde un cliente IMAP queda en "Todos".
- **Spam**: Gmail filtra el spam antes de que llegue al cliente. En IMAP las etiquetas aparecen como carpetas y el flujo 01 lee solo `INBOX` (acción posterior `read`, formato simple). Lo que Gmail mande a Spam no está en `INBOX` y el flujo no lo ve. Fuente: https://support.google.com/mail/answer/78892?hl=es
- **Remitente**: Gmail pone como From la cuenta que inicia sesión, salvo que la dirección sea un alias suyo. Por eso `support_address` tiene que ser esa cuenta.

<!-- E2E: confirmar en la prueba real: si los correos de prueba caen en Spam o en Promociones -->
<!-- E2E: confirmar en la prueba real: si la respuesta aparece en el mismo hilo en Gmail -->
<!-- E2E: confirmar en la prueba real: si el nodo IMAP los marca como leídos en la web de Gmail -->
<!-- E2E: confirmar en la prueba real: si Gmail conserva el Message-ID propio de la respuesta (reply_message_id) -->

## Otro buzón: Hostinger Business Email o el de vuestra empresa

El flujo habla IMAP para leer y SMTP para enviar. Vale cualquier buzón que dé las dos cosas con usuario y contraseña.

**Hostinger Business Email.** Es un producto de pago aparte. Los datos salen de hPanel → Correos → Configurar dispositivos:

- IMAP: `imap.hostinger.com`, puerto 993, SSL.
- SMTP: `smtp.hostinger.com`, puerto 465, SSL (`SMTP_SECURITY=ssl`).
- Límites oficiales (https://www.hostinger.com/support/4625828-parameters-and-limits-of-hostinger-email): Business Starter 1.000 mensajes al día y Business Premium 3.000. Entrada y salida cuentan por separado, en una ventana móvil de 24 horas, por buzón. Las pruebas gratuitas y el antiguo Free Business Email, 100 al día. 100 destinatarios por mensaje.

**El buzón de vuestra empresa.** Pedid a vuestro proveedor:

- host y puerto IMAP (con SSL),
- host y puerto SMTP: 465 con SSL (`SMTP_SECURITY=ssl`) o 587 con STARTTLS (`SMTP_SECURITY=starttls`).

Si el proveedor solo admite OAuth y no contraseña, este flujo no sirve tal cual.

Se cambia en los mismos tres sitios que con Gmail: credencial IMAP, variables `SMTP_*` de Coolify y `support_address`.

## Credenciales

| Credencial en n8n | Tipo | Dónde se saca | Quién la usa |
|---|---|---|---|
| IMAP | IMAP | Gmail: User = dirección completa, Password = contraseña de aplicación, Host `imap.gmail.com`, puerto 993, SSL/TLS activado (ver [Buzón: Gmail gratuito](#buzón-gmail-gratuito)). | Nodo "Correo IMAP". |
| RAG API Key | Header Auth, cabecera `X-RAG-API-Key` | La misma clave que inventaste en el episodio 2. | "Buscar RAG". |
| Mail API Key | Header Auth, cabecera `X-MAIL-API-Key` | Te la inventas, igual que la del RAG. La misma en los webhooks y en quien los llama. | Webhooks internos y los HTTP que los disparan. |
| LLM API | Header Auth, cabecera `Authorization`, valor `Bearer sk-...` | Consola de DeepSeek (o el proveedor que elijas). | "Clasificar". |
| Telegram | Telegram API | BotFather: `/newbot`. El chat id sale al escribirle al bot y abrir `getUpdates`. | Los seis: botones (03a, 03b, y el 02 marca el mensaje del botón al enviar), urgentes, bugs y leads (04), resumen (05) y avisos de fallo (01, 02, 03b, 04). |
| GitHub Issues | Header Auth, cabecera `Authorization`, valor `Bearer github_pat_...` | GitHub → Settings → Developer settings → Fine-grained token. Solo permiso **Issues** sobre el repo de pruebas. | "Crear issue". |
| PostgreSQL | Postgres | La del episodio 2. Host `knowledge-db`, puerto 5432, base `knowledge`. | Todos los nodos de base de datos. |

El SMTP **no** es una credencial de n8n: son las variables `SMTP_*` del contenedor de task runners (paso 2 de la instalación). Las usan "Enviar" (02) y los acuses del 04.

El repo de la issue no es este. Crea uno vacío, por ejemplo `tu-usuario/email-agent-sandbox`, y ponlo en `github_repo`. Un token con permiso de issues no debe apuntar a un repo de producto.

## Umbral de confianza

Está en el nodo Configuración del flujo 01, campo `confidence_threshold`. De serie es **0,75**.

- Si lo **subes** (0,9), casi todo lo dudoso va a Telegram. Menos respuestas solas, más trabajo manual, menos riesgo de decir algo que no está en la base.
- Si lo **bajas** (0,5), el sistema contesta más solo. También se cuela más una respuesta que suena segura y no lo es.

No basta el número. Una consulta frecuente solo se envía sola si, además, el fragmento del RAG supera `min_rag_score` (0,45) **y** el texto del fragmento contiene las palabras de la pregunta. En las pruebas, una pregunta sobre SAP que no está en la base igual devolvía fragmentos con score 0,86 de páginas que no hablan de SAP. El score del episodio 2 no es una prueba de que la página responda.

### Dónde busca

El 01 consulta el RAG con `source_type` = `rag_source_type` (de serie `repo`). En la prueba real, con las 77 transcripciones de vídeos del episodio 2 en el mismo índice y `all`, «¿a qué hora abre el soporte los viernes?» devolvía cinco despedidas de vídeos con score 0,86-0,87 y la FAQ ni aparecía: el correo iba a Telegram por falta de fuente. Con `repo`, la FAQ sale primera (0,855). Si tu documentación de soporte vive en Outline, pon `outline`; `all` solo si el índice tiene únicamente documentación de soporte.

Precios, plazos, contratos, devoluciones, reembolsos, DNI, IBAN y tarjeta van a una persona aunque la confianza sea 0,99. La lista es `sensitive_topics`, separada por comas.

## Modelo

Recomiendo **DeepSeek Flash** (`deepseek-flash`, base `https://api.deepseek.com`; hoy lo sirve DeepSeek-V4.1-Flash-1017). El nombre antiguo `deepseek-v4-flash` todavía se acepta, pero ese modelo está retirado y la petición la atiende el mismo Flash. En español sigue el JSON bien y tiene modo JSON.

Ojo: en DeepSeek el modo *thinking* viene **activado por defecto** (esfuerzo alto). Para clasificar no hace falta, tarda más y se cobra. El nodo "Clasificar" manda `thinking: {type: "disabled"}` cuando la base es `api.deepseek.com`; con otro proveedor no lo manda.

Tarifa oficial a 29 de octubre de 2026 (https://api-docs.deepseek.com/quick_start/pricing), por millón de tokens, fuera de hora punta / en hora punta:

| | Fuera de punta | Punta |
|---|---|---|
| Entrada sin caché | 0,15 $ | 0,30 $ |
| Entrada cacheada | 0,003 $ | 0,006 $ |
| Salida | 0,60 $ | 1,20 $ |

La hora punta es de 01:00 a 04:00 y de 06:00 a 10:00 UTC, de lunes a viernes. El resto, fines de semana incluidos, es fuera de punta.

Un correo normal, ya limpio, más el prompt y cinco fragmentos, son unos 3.000 tokens de entrada y unos 400 de salida. Mil correos, sin caché, salen por unos **0,70 $** fuera de punta y **1,40 $** en punta. Con la caché del prompt, menos.

<!-- E2E: confirmar tokens reales por correo con la prueba real -->

Qwen3.8 Flash (lo que en la práctica es el "Qwen 3.8 Lite") está en unos 0,15 $ / 0,47 $ por millón. GLM-5.3 Flash, en la tarifa de Z.ai, unos 0,15 $ / 0,50 $. Los dos clasifican en español. Salen más caros en la salida, que es justo el JSON. OpenAI queda como alternativa si la empresa ya lo exige: para clasificar no hace falta el modelo de frontera y la factura se nota.

Se cambia en Configuración, campos `llm_model` y `llm_base_url`. La credencial es solo la clave.

## El prompt

La fuente de verdad es `prompts/clasificador.md`. No está metido en un Code node: el flujo 01 lo carga en el campo `prompt` del nodo Configuración, que es el texto que se ve en el lienzo.

Para cambiarlo: edita el Markdown, ejecuta `python3 scripts/build_workflows.py` y vuelve a importar el 01. Si estás en cámara y no quieres reimportar, pega el texto nuevo en ese campo. El siguiente correo ya lo usa.

`scripts/build_workflows.py` también copia `src/` dentro de los nodos Code. Si cambias la normalización o la decisión, regenera los JSON. Los tests de esa lógica son `node scripts/check.js`, que además comprueba que el prompt horneado en el 01 es el de `prompts/clasificador.md`. `python3 scripts/build_workflows.py --check` falla si algún JSON no está al día.

## Qué pasa si nadie pulsa

`approval_hours` es 24. El 03a guarda `approval_due_at`. El flujo 05, a las 06:00 UTC, pasa esas filas (y las que se quedaron a medias en Editar) a `aprobacion_vencida` y las cuenta en el resumen. No se envían solas. Si alguien pulsa un botón después del plazo, aunque el 05 aún no haya pasado, el 03b no envía: marca la fila vencida y el botón lo dice.

## Avisos de Telegram

Todos tienen la misma forma: emoji y título en negrita, los campos uno por línea («De:», «Asunto:»…) y los bloques separados. El texto del correo, el borrador y la respuesta sugerida van en una cita. Todo lo que viene del correo se escapa (`parse_mode` HTML). Si no cabe en un mensaje de Telegram, se recorta solo ese bloque largo y se dice; los avisos y el pie no se recortan nunca.

| Aviso | Flujo | Lleva |
|---|---|---|
| 📝 **Borrador para aprobar** | 03a | De, Asunto, categoría y confianza, 🔁 si lo retuvo el freno anti-bucles, ⚠️ si es un tema sensible, por qué, el borrador y las fuentes. Botones Aprobar, Rechazar y Editar. |
| 🛑 **Bloqueado: intenta dar órdenes** | 03a | Lo mismo, sin borrador ni Aprobar. Si lo bloqueó el borrador, el título dice «…el borrador prometía dinero» o «…repetía instrucciones internas». |
| 🚨 **URGENTE** | 04 | De, Asunto, el texto del correo y «📨 Ya le hemos mandado un acuse automático.» (o que no salió, y por qué). |
| 💼 **Lead nuevo** | 04 | De, Asunto, motivo, la respuesta sugerida (no enviada) y «No se ha contestado: escríbele tú.». |
| 🐞 **Bug registrado** | 04 | De, el número y el enlace de la issue, su título y si salió el acuse. |
| ⚠️ **Fallo: …** | 01, 02, 03b, 04 | Qué falló, la fila, el error y qué hacer. |
| 📊 **Resumen de ayer** | 05 | Contestado / Pendiente de ti / Descartado / Problemas. Las líneas a 0 no salen, salvo «Esperando aprobación» y «Con error». Al final, «✅ Nada pendiente de ti.» o «👉 Te toca: …». |

Un borrador ya aprobado, con datos inventados (en el móvil, las negritas y la cita se ven con formato):

```
📝 Borrador para aprobar
De: Ana Ruiz <ana@cliente.example>
Asunto: Horario de soporte
Categoría: consulta frecuente · confianza 62 %

Por qué: Está en la FAQ, pero la pregunta es muy corta.

Borrador
│ Hola, Ana:
│ Atendemos de lunes a viernes de 9:00 a 18:00.

Fuentes
• FAQ de soporte — Taller Norte (2026-10-17)
  https://docs.example.com/doc/faq-soporte

✅ Aprobado y enviado · 10:03
```

## Botones de Telegram

- Solo cuenta el chat de `telegram_chat_id` (y las personas de `telegram_user_ids`, si lo rellenas). Un botón o un texto de cualquier otro chat no hace nada, no recibe respuesta y queda apuntado como `telegram_ajeno`. Mientras `telegram_chat_id` tenga el valor de ejemplo, no vale nadie.
- No uses el campo *Restrict to Chat IDs* del trigger de Telegram: en n8n 2.10.2 mira `message.chat.id`, que un botón no trae, y descartaría todos los botones. El filtro está en el nodo "Leer update".
- Aprobar dos veces, aprobar después de Rechazar o con la fila ya enviada no manda nada: el botón contesta con un aviso ("Ya se respondió", "Ya estaba rechazado", "Venció el plazo").
- Editar manda un mensaje que hay que **responder** (Telegram abre la respuesta solo). Ese texto es el que sale. Un texto suelto, que no responde a ese mensaje, no se envía a nadie.
- En cuanto decides, el mensaje del borrador **pierde los botones** y gana una línea al final con lo que pasó y la hora de Madrid:

  | Cuándo | Línea |
  |---|---|
  | Pulsas Aprobar (03b) | «⏳ Aprobado. Enviando… · 10:03» |
  | Sale el correo (02) | «✅ Aprobado y enviado · 10:03» |
  | Pulsas Rechazar | «❌ Rechazado · 10:05» |
  | Pulsas Editar (cuando ya ha salido la petición de texto) | «✏️ Editando: responde al mensaje que te acabo de mandar» |
  | Sale tu texto (02) | «✅ Enviado con tu texto · 10:07» |
  | Falla el SMTP (02) | «⚠️ Falló el envío: … · 10:03. Tienes Reintentar en el aviso de abajo.» |
  | El 03b no llega al 02 | «⚠️ Falló el envío: el flujo 02 no recibió la petición · 10:03. Pulsa Aprobar otra vez cuando esté.» Los botones vuelven. |

  El texto se rehace desde la fila con `currentMessage` (`src/format.js`): sale igual que el que mandó el 03a, con su formato. Si pulsaste en el aviso de fallo del 02 (Reintentar), se rehace ese aviso.
- Un botón viejo (ya respondido, rechazado, vencido, retenido) también deja el mensaje sin botones, con «✅ Ya estaba respondido», «❌ Ya estaba rechazado», «⌛ Venció el plazo»... Un mensaje que ya no tiene fila se rehace con el texto que trae el botón (sin formato). Si la fila sigue en curso (un doble toque rápido), el mensaje no se toca: lo marca la ejecución que lo está enviando.
- La edición nunca para nada: los nodos que editan van con *On Error: Continue*. Si Telegram la rechaza ("message is not modified", un mensaje borrado o muy viejo), el flujo sigue y el correo sale igual. En el 02 la edición va después de marcar la fila como enviada.
- Solo edita el 03b después de "Leer update": un botón de otro chat no toca ningún mensaje. Edita con la misma credencial "Telegram" (`editMessageText` con un teclado vacío, que es lo que quita los botones).

## Si algo falla

Ningún error se queda callado. Cada uno deja la fila en un estado y, si se puede, avisa por Telegram:

| Qué falla | Estado | Aviso |
|---|---|---|
| El 01 no consigue llamar al 02, 03a o 04 (flujo sin publicar, `n8n_url` o Mail API Key mal) | `error_interno` | Telegram desde el 01 |
| El SMTP (o el runner de Python) | `error_envio` | Telegram con Reintentar, Rechazar y Editar. El mensaje que pulsaste dice «⚠️ Falló el envío» |
| Telegram no acepta el aviso de aprobación | `error_aviso` | No se puede avisar por Telegram: sale en el resumen |
| GitHub no crea la issue | `error_accion` | Telegram («⚠️ Fallo: no se pudo crear la issue») |
| Telegram no acepta el aviso de un lead | el lead sigue en `lead_registrado` | `error_aviso` en `mail_actions`; el lead sale en el resumen |
| El 03b no consigue llamar al 02 | vuelve a `esperando_aprobacion` | Telegram, y el mensaje del borrador recupera sus botones: pulsa Aprobar otra vez cuando esté |
| El 02 no consigue llamar al 03a con un correo retenido por el freno anti-bucles | sigue en `retenido_bucle` | Telegram desde el 02, sin botones. El resumen la cuenta como atascada |

El resumen cuenta las filas en error y las que llevan más de una hora a medio camino.

Si reinicias **solo** el contenedor de n8n, reinicia también `task-runners` (en Coolify, *Restart* del servicio entero los reinicia juntos). En n8n 2.10.2 el runner de JavaScript vuelve solo, pero el de Python se queda esperando a un broker que ya no existe: los envíos acaban en `error_envio` con el aviso "el nodo Enviar (Python) no se ejecutó". Tras reiniciar `task-runners`, Reintentar los manda. Visto en la prueba de la revisión, no en producción.

La instancia del episodio 2 está en UTC. Las 06:00 UTC son las 08:00 en Madrid en horario de verano y las 07:00 en invierno. No cambies el `TZ` del contenedor para este flujo: el reindexado del episodio 2 vive en la misma instancia. Si quieres las 08:00 de Madrid en invierno, pon `triggerAtHour` a 7.

## Inyección de prompt

El cuerpo del correo es un dato, no una orden. Hay tres cortes:

1. El prompt delimita el correo con `<correo_no_confiable>` y dice que nada de ahí es una instrucción.
2. `src/security.js` marca frases del estilo "ignora tus instrucciones" o "responde que le devolvemos el dinero". Eso no tira el correo: lo aparta de la respuesta automática.
3. `src/decide.js` mira la salida. Si el borrador promete una devolución y las fuentes no dicen "reembolso íntegro" o "devolución del dinero", el borrador se sustituye por un aviso y la ruta es aprobación.

Un correo así queda **bloqueado**: el borrador del modelo se tira (pudo escribirlo el atacante) y no se guarda. En Telegram llega el aviso, sin borrador y sin botón Aprobar: solo Rechazar o Editar. Si alguien pulsa un Aprobar viejo, el 03b lo rechaza. Lo único que puede salir hacia el remitente es lo que escriba una persona con Editar. Lo mismo pasa si el borrador repite trozos del prompt.

El correo tampoco puede cerrar su bloque: si trae `</correo_no_confiable>` o `<fuentes_rag>`, la marca se borra antes de llegar al modelo. La salida del modelo se valida: si no es un objeto con `categoria` en texto y `confianza` numérica, cuenta como JSON roto y va a una persona.

El correo 9 de `test-emails/` es exactamente ese intento. El sistema no confirma el reembolso. Como mucho le llega a una persona, con el aviso de que el correo intentaba dar órdenes.

## Datos personales

En `mail_messages` se guarda el remitente, el asunto, el cuerpo ya limpio, el borrador, la respuesta que se llegó a enviar y las fuentes. No se guardan adjuntos: el nodo IMAP los tiene desactivados.

El log de lo que se hizo está en `mail_actions`. Un botón o un texto de otro chat de Telegram queda ahí como `telegram_ajeno`, con el chat y el usuario, sin fila de correo.

`retention_days` (90) está en el flujo 05. Cada mañana borra las filas más viejas y, en cascada, su log (y los `telegram_ajeno` viejos). Si lo bajas, olvidas antes. Si lo subes, guardas más correo de clientes.

La issue de GitHub es otra copia, y el repo de pruebas suele ser público. Por eso lleva lo mínimo: el asunto y el cuerpo con correos, teléfonos, IBAN, DNI y números largos tapados, las URL sin parámetros, el texto dentro de un bloque de código (un `@usuario` no avisa a nadie) y una referencia interna (el `id` de la fila). No lleva remitente, ni Message-ID, ni enlace `mailto`. Quién escribió se mira en `mail_messages` con esa referencia. El acuse al cliente tampoco lleva el enlace de la issue: solo la referencia (#N). Un repo privado le daría un 404 y, además, enseñaría tu herramienta interna. El número y la URL de la issue se guardan en `mail_messages` (`github_issue_number`, `github_issue_url`) para ti.

El aviso de lead a Telegram lleva el remitente, el asunto, el motivo y la respuesta sugerida. Es otra copia del correo, en el chat del dueño. El aviso urgente lleva además el texto del correo. El de bug, solo el remitente, el número y el enlace de la issue (es interno), su título (ya tapado) y si salió el acuse. Aun así, el tapado es por patrones: un nombre propio en el cuerpo se queda. Con correo real, mejor un repo privado.

## Idempotencia y bucles

La clave única es `message_id` (la cabecera Message-ID). Lo primero que hace el 01 es reservarla (`procesando`), antes de llamar al RAG o al modelo. Un segundo insert no crea fila: el flujo anota `duplicado` en el log y no llama al modelo, aunque lleguen cuatro copias a la vez.

Si el correo no trae Message-ID, el 01 calcula uno estable con remitente, destinatario, fecha, asunto y cuerpo (`generado-` + SHA-256). El mismo correo leído dos veces da la misma clave. A ese correo se le contesta sin `In-Reply-To`: no se inventa un id que el cliente no tiene.

No se contesta si la cabecera `Auto-Submitted` no es `no`, si viene `X-Autoreply`, `X-Autorespond`, `List-Id`, si la precedencia es bulk/list/junk, si el remitente es del estilo `no-reply@`, `mailer-daemon` o `postmaster`, o si el From no es una sola dirección normal (dos direcciones o caracteres raros: la respuesta podría acabar en un tercero). El correo 10 es la autorespuesta de vacaciones: se guarda como `ignorado_autorespuesta` y no sale nada. El nodo IMAP va en formato *simple*: así entrega todas las cabeceras en `metadata`, que es lo que lee el filtro (y por eso los acentos se reparan en la normalización: ver [Acentos con Gmail](#acentos-con-gmail)). Las respuestas automáticas salen con `Auto-Submitted: auto-replied` (RFC 3834), para que otra autorespuesta no conteste.

### Freno anti-bucles

El flujo 02 no manda sola una respuesta a una dirección que ya recibió una respuesta automática en la última hora. El bucle se corta, pero el cliente no se queda sin respuesta. Si pregunta dos cosas en una hora, la segunda pasa por ti:

1. La fila pasa a `retenido_bucle` y queda anotada en `mail_actions` (`retenido_bucle`).
2. El 02 llama al 03a: `POST /webhook/mail-approval` con `{"mail_id": "...", "reason": "bucle"}`.
3. A Telegram llega el borrador con Aprobar, Editar y Rechazar, y el aviso «🔁 Retenido por el freno anti-bucles: a esta dirección ya se le contestó automáticamente hace menos de una hora. Revísalo antes de enviar.».
4. Si apruebas, sale por el camino manual del 02, que no tiene freno. Si nadie pulsa, vence como cualquier aprobación.

Un correo bloqueado (inyección o promesa de dinero) no pasa por aquí: el 02 no lo reclama en modo auto. Va al 03a desde el 01, sin Aprobar.

Si el 02 no consigue llamar al 03a, la fila sigue en `retenido_bucle` y llega un aviso a Telegram, sin botones. El resumen la cuenta como atascada. Cuando el 03a esté publicado, repite la llamada con el id de la fila:

```bash
curl -sS -X POST https://n8n.tudominio.com/webhook/mail-approval \
  -H 'X-MAIL-API-Key: <clave>' \
  -H 'Content-Type: application/json' \
  -d '{"mail_id": "<id de la fila>", "reason": "bucle"}'
```

Si es Telegram lo que falla dentro del 03a, la fila queda en `error_aviso`, como cualquier aviso de aprobación. En el resumen, "Retenidos por bucle" (en Problemas) son las veces que saltó el freno en las últimas 24 horas, sacadas de `mail_actions`.

## Acentos con Gmail

En la prueba con Gmail real, el cuerpo llegaba con los acentos rotos: «El panel de producciÃ³n estÃ¡ caÃ­do», «Â¿cuÃ¡l». El asunto, bien. Es un fallo del nodo IMAP de n8n 2.10.2 en formato *simple*: `@n8n/imap` decodifica el quoted-printable sin pasarle el charset de la parte (`getPartData` llama a `PartData.fromData` sin él) y cada byte UTF-8 llega como un carácter latin1. El asunto va por la cabecera (RFC 2047) y se decodifica por otro lado. Gmail manda el texto como `multipart/alternative`, `text/plain; charset="UTF-8"` en quoted-printable: le pasa a casi cualquier correo con tildes.

`src/normalize.js` lo arregla lo primero, en `textPlain` y `textHtml`, antes de quitar HTML, firmas y citas. Si el texto tiene pinta de UTF-8 leído como latin1 (`Ã³`, `Â¿`...), todos sus caracteres caben en latin1 y, releído como UTF-8, es válido, se cambia por ese. Si no, se queda como estaba: «producción», «São Paulo», un emoji o un texto con letras de fuera de latin1 no se tocan. Si el correo es de una sola parte y su `Content-Type` (en `metadata`) declara otro charset, tampoco. Con eso salen bien `body_normalized`, Telegram, la consulta al RAG y la issue. El runner de JavaScript de 2.10.2 tiene `Buffer`; si no lo tuviera, decodifica a mano.

¿Por qué no el formato *resolved*? Pasa el correo entero por `mailparser`, que sí respeta el charset. Pero en n8n 2.10.2 descarga siempre el mensaje completo y convierte cada adjunto en un binario de la ejecución, sin opción para evitarlo. No queremos adjuntos de clientes guardados en las ejecuciones. Con *simple* no se bajan, las cabeceras siguen en `metadata` para el filtro y la reparación es pequeña y está probada. Lo que no arregla: un cuerpo en ISO-8859-1 codificado en base64 (n8n lo lee como UTF-8 y se pierde). Gmail y Outlook mandan UTF-8.

## Hilo del correo

El nodo Send Email de n8n 2.10.2 pone asunto, cuerpo y Reply-To, y nada más: no hay campo para `In-Reply-To` ni `References` (tampoco en las versiones 2.x posteriores, mirado en el código de n8n). Sin esas cabeceras, Gmail, Outlook o Apple Mail pueden no meter la respuesta en el hilo del cliente.

Por eso el envío lo hace un **Code node de Python** con `smtplib`, de la biblioteca estándar. Está en `src/send_mail.py` y `scripts/build_workflows.py` lo copia dentro de los nodos "Enviar" (02) y los dos acuses (04). Pone `In-Reply-To` con el Message-ID del cliente, `References` con su cadena más ese id, un Message-ID propio (se guarda en `reply_message_id`) y quita los saltos de línea de todo lo que viene del correo, para que nadie cuele una cabecera.

Si el correo del cliente llega sin asunto, la respuesta sale con asunto `Re:` a secas. Con `Re: (sin asunto)`, Gmail abre un hilo nuevo aunque `In-Reply-To` y `References` estén bien. Probado con Gmail real. En Telegram sí se ve «(sin asunto)»: ese texto es para ti, no va en el correo.

Ese nodo corre en el contenedor de task runners (`n8nio/runners:2.10.2`, el de la plantilla de Coolify). De serie, ese contenedor no deja a Python importar nada ni leer variables. El fichero `runners/n8n-task-runners.json` es el de la imagen con tres cambios, solo para Python:

- `N8N_RUNNERS_STDLIB_ALLOW=email,os,re,smtplib,ssl`: los módulos que usa el envío.
- `N8N_BLOCK_RUNNER_ENV_ACCESS=false` y las cinco `SMTP_*` en `allowed-env`: el nodo lee el servidor y la contraseña del contenedor, no del flujo. La contraseña no aparece en el JSON ni en las ejecuciones.

El JavaScript sigue igual (`crypto` y `moment`). El precio: con `os` permitido, cualquier Code node de **Python** de esta instancia puede leer esas variables y ejecutar cosas dentro del contenedor de runners. Si eres el único que edita flujos en tu n8n, es razonable. Si no, no lo hagas así.

Si el fichero no está montado, el nodo falla al importar `smtplib`. No es silencioso: la fila queda en `error_envio` y llega un aviso a Telegram.

## Fecha de las fuentes

`/webhook/rag-search` devuelve título, URL, score y texto. No devuelve fecha. El flujo 01 lee `updated_at` de `knowledge_documents` con el `document_id` que sí viene en el fragmento, y eso es lo que sale en Telegram.

## Correos de prueba

Las pruebas de la lógica no necesitan nada instalado:

```bash
node scripts/check.js                     # normalización (acentos), filtros, decisión, botones, avisos, issue, JSON de los flujos
python3 scripts/check_mail.py             # el envío por SMTP en el hilo, con un servidor falso
python3 scripts/build_workflows.py --check  # los JSON están al día con src/ y prompts/
```

Doce ficheros en `test-emails/`. `send.py` los manda desde un **buzón cliente**: otra cuenta de Gmail, distinta de la del agente, con su propia contraseña de aplicación. Se rellena en el `.env` (`CLIENT_EMAIL`, `CLIENT_PASSWORD`, `CLIENT_SMTP_HOST`, `CLIENT_SMTP_PORT`). Sin esas variables usa `SMTP_*`, como antes.

El script reescribe `To` (la dirección del agente, `IMAP_USER`) y `From` (el nombre del `.eml` más el buzón cliente), porque Gmail reescribe el From si no es de la cuenta que inicia sesión. Cada envío lleva un **Message-ID nuevo**: Gmail descarta en silencio un correo cuyo Message-ID ya tiene, y con ids fijos el segundo ensayo no llegaría. Los ids del último envío quedan en `test-emails/.ultimo-envio.json` (no se sube). No imprime direcciones: solo `enviado 01-consulta-clara.eml (Message-ID <...>)`.

```bash
cp .env.example .env
python3 test-emails/send.py --dry-run     # monta los mensajes y dice qué enviaría, sin conectarse
python3 test-emails/send.py
python3 test-emails/send.py --resend 01   # reutiliza el Message-ID del último envío de ese correo
```

`--resend 01` es la prueba de duplicados. Con Gmail, ese reenvío puede no llegar al buzón (Gmail deduplica por Message-ID). Si no llega, la prueba de duplicados se hace con `POST /webhook/mail-ingest` y el mismo `message_id` dos veces.

<!-- E2E: confirmar en la prueba real si el reenvío con el mismo Message-ID llega o lo descarta Gmail -->

| Fichero | Qué tiene que pasar |
|---|---|
| 01 Consulta clara | Horario, que está en la FAQ. Respuesta sola, con fuente. |
| 02 Ambigua | Muy corta. A Telegram. |
| 03 Fuera de la base | SAP. A Telegram, no se inventa un conector. |
| 04 Bug con detalle | Acuse en el hilo con la referencia (#N), sin enlace a GitHub, e issue en el repo de pruebas, sin el correo del remitente. A Telegram, «🐞 Bug registrado» con el enlace. |
| 05 Bug mal escrito | También issue. |
| 06 Lead | Se guarda el contacto (`lead_registrado`) y llega a Telegram un aviso «💼 Lead nuevo» con la respuesta sugerida, sin botones. No se envía solo: contestas tú. |
| 07 Urgente | Acuse en el hilo y, segundos después, «🚨 URGENTE» en Telegram con el texto del correo y si el acuse salió. |
| 08 Spam | No se contesta. La fila queda como descartado. |
| 09 Inyección | No promete el reembolso. Llega a Telegram «🛑 Bloqueado: intenta dar órdenes», sin borrador y sin Aprobar. |
| 10 Vacaciones | No se contesta. |
| 11 Quince respuestas citadas | Se queda con la pregunta del horario. |
| 12 Inglés | Se ve que la base está en español. No se responde solo si el fragmento no contiene las palabras. |

## Estructura

```
schema.sql
.env.example
prompts/clasificador.md
kb/faq-soporte.md
src/                  lógica que también corre dentro de los nodos (JS y send_mail.py)
runners/              n8n-task-runners.json para el contenedor de task runners
workflows/            los seis JSON
test-emails/          los doce correos y send.py
scripts/build_workflows.py
scripts/check.js
scripts/check_mail.py
GUION-TECNICO-EP3.md
```

## Serie

- Episodio 1: Coolify, dominio, Outline.
- Episodio 2: `coolify-pgvector`, `coolify-embeddings`, `knowledge-hub-n8n`, `knowledge-hub-mcp`.
- Este repo es el episodio 3.

## Licencia

MIT © Eduardo Navajas
