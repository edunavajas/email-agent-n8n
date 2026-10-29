# email-agent-n8n

Agente de correo del episodio 3 de **Mi Empleado Digital**. Llega un email a `soporte@tudominio.com`, el sistema lo limpia, lo clasifica con la base de conocimiento del episodio 2 y actúa. Lo que no tiene claro se lo pasa a una persona por Telegram. Cada mañana manda un resumen con números.

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
| `workflows/02-respuesta.json` | Envía por SMTP en el mismo hilo (`In-Reply-To`, `References`) y marca la fila. | `POST /webhook/mail-reply` |
| `workflows/03a-aprobacion.json` | Manda el borrador a Telegram y guarda el `message_id`. Se acaba. | `POST /webhook/mail-approval` |
| `workflows/03b-botones.json` | Recibe el botón (solo del chat del dueño), busca la fila y envía, descarta o pide el texto corregido. | Telegram |
| `workflows/04-acciones.json` | Issue de GitHub, aviso urgente, lead o descarte. | `POST /webhook/mail-action` |
| `workflows/05-resumen.json` | Vence aprobaciones, borra lo viejo y manda el resumen. | Cada día a las 06:00 UTC, o el botón "Resumen ahora". |

### Por qué el 3 son dos flujos

Un nodo Wait deja la ejecución en memoria. Si n8n se reinicia, esa ejecución muere y el botón no tiene a quién contestar. Aquí el 03a solo escribe en la fila `telegram_message_id` y `esperando_aprobacion`. El 03b es otro flujo, con el trigger de Telegram. Cuando pulsas, busca la fila por ese id. El estado no está en la ejecución.

Cada paso es un `UPDATE ... WHERE status = '<el de antes>'` en una sola sentencia. Si dos ejecuciones llegan a la vez (un doble toque, un reintento), solo una cambia la fila y la otra no hace nada. Los estados y quién los mueve están al principio de `schema.sql`.

## Instalación

Partes del episodio 2 ya funcionando: Coolify, PostgreSQL + pgvector, n8n 2.10.2 y el webhook `POST /webhook/rag-search`.

1. Aplica el esquema en la misma base del episodio 2 (host `knowledge-db`, base `knowledge`):

   ```bash
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema.sql
   ```

   Crea `mail_messages` y `mail_actions`. No toca `knowledge_documents` ni `knowledge_chunks`.

2. Prepara el contenedor de **task runners** para el envío por SMTP (ver [Hilo del correo](#hilo-del-correo)). En Coolify, en el servicio de n8n:
   - Añade al servicio `task-runners` un fichero montado en `/etc/n8n-task-runners.json` con el contenido de `runners/n8n-task-runners.json`. Tiene que poder leerlo el usuario 1000 (permisos 644).
   - Añade al mismo servicio las variables `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER` y `SMTP_PASSWORD` del buzón `soporte@`. En Hostinger: `smtp.hostinger.com`, `465`, `ssl`.
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
   | `support_address` | 01, 02, 04 | El buzón, `soporte@tudominio.com`. Es el From y el Reply-To. |
   | `telegram_chat_id` | todos | Tu chat con el bot (número). Solo ese chat puede pulsar botones. |
   | `telegram_user_ids` | 03b | Vacío si el chat es privado. Si es un grupo, los id de quienes pueden decidir, separados por comas. |
   | `n8n_url` | 01, 03b | `http://localhost:5678`: n8n se llama a sí mismo, sin salir a internet. |
   | `rag_url` | 01 | `http://localhost:5678/webhook/rag-search` si el RAG del episodio 2 vive en el mismo n8n. |
   | `llm_base_url`, `llm_model` | 01 | Ver [Modelo](#modelo). |
   | `github_repo`, `github_api_url` | 04 | `tu-usuario/email-agent-sandbox` y `https://api.github.com`. |
   | `confidence_threshold`, `min_rag_score`, `sensitive_topics` | 01 | Ver [Umbral de confianza](#umbral-de-confianza). |
   | `approval_hours` | 02, 03a | 24. |
   | `retention_days` | 05 | 90. |

6. Indexa `kb/faq-soporte.md` con el flujo 04 del episodio 2 o con el MCP, **sin** `replace_all` si ya tienes otros documentos de repositorio. Si mandas un lote con `replace_all: true`, el flujo 04 borra del índice los ficheros que no vengan en ese lote. Para esta FAQ basta un documento con `source_type: repo` y `external_id: email-agent/faq-soporte.md`.

7. Publica (*Publish*) los seis flujos: en n8n 2.x publicar es lo que antes era activar. Empieza por 02, 03a, 04 y 03b, y deja el 01 para el final: es el que lee el buzón. El 03b registra el webhook en Telegram al publicarse.

## Credenciales

| Credencial en n8n | Tipo | Dónde se saca | Quién la usa |
|---|---|---|---|
| IMAP | IMAP | Hostinger → hPanel → Correos → el buzón `soporte@`. Host `imap.hostinger.com`, puerto 993, SSL. | Nodo "Correo IMAP". |
| RAG API Key | Header Auth, cabecera `X-RAG-API-Key` | La misma clave que inventaste en el episodio 2. | "Buscar RAG". |
| Mail API Key | Header Auth, cabecera `X-MAIL-API-Key` | Te la inventas, igual que la del RAG. La misma en los webhooks y en quien los llama. | Webhooks internos y los HTTP que los disparan. |
| LLM API | Header Auth, cabecera `Authorization`, valor `Bearer sk-...` | Consola de DeepSeek (o el proveedor que elijas). | "Clasificar". |
| Telegram | Telegram API | BotFather: `/newbot`. El chat id sale al escribirle al bot y abrir `getUpdates`. | Los seis: botones (03a, 03b), urgentes (04), resumen (05) y avisos de fallo (01, 02, 04). |
| GitHub Issues | Header Auth, cabecera `Authorization`, valor `Bearer github_pat_...` | GitHub → Settings → Developer settings → Fine-grained token. Solo permiso **Issues** sobre el repo de pruebas. | "Crear issue". |
| PostgreSQL | Postgres | La del episodio 2. Host `knowledge-db`, puerto 5432, base `knowledge`. | Todos los nodos de base de datos. |

El SMTP **no** es una credencial de n8n: son las variables `SMTP_*` del contenedor de task runners (paso 2 de la instalación). Las usan "Enviar" (02) y los acuses del 04.

El repo de la issue no es este. Crea uno vacío, por ejemplo `tu-usuario/email-agent-sandbox`, y ponlo en `github_repo`. Un token con permiso de issues no debe apuntar a un repo de producto.

## Umbral de confianza

Está en el nodo Configuración del flujo 01, campo `confidence_threshold`. De serie es **0,75**.

- Si lo **subes** (0,9), casi todo lo dudoso va a Telegram. Menos respuestas solas, más trabajo manual, menos riesgo de decir algo que no está en la base.
- Si lo **bajas** (0,5), el sistema contesta más solo. También se cuela más una respuesta que suena segura y no lo es.

No basta el número. Una consulta frecuente solo se envía sola si, además, el fragmento del RAG supera `min_rag_score` (0,45) **y** el texto del fragmento contiene las palabras de la pregunta. En las pruebas, una pregunta sobre SAP que no está en la base igual devolvía fragmentos con score 0,86 de páginas que no hablan de SAP. El score del episodio 2 no es una prueba de que la página responda.

Precios, plazos, contratos, devoluciones, reembolsos, DNI, IBAN y tarjeta van a una persona aunque la confianza sea 0,99. La lista es `sensitive_topics`, separada por comas.

## Modelo

Recomiendo **DeepSeek V4 Flash** (`deepseek-v4-flash`, base `https://api.deepseek.com`). Es el Lite de la serie V4. En español sigue el JSON bien, tiene modo JSON y, a 17 de octubre de 2026, en la tarifa oficial sale a **0,14 $ el millón de tokens de entrada** (sin caché) y **0,28 $ el millón de salida**. La entrada cacheada baja a 0,0028 $.

Un correo normal, ya limpio, más el prompt y cinco fragmentos, son unos 3.000 tokens de entrada y unos 400 de salida. Mil correos, sin caché, salen alrededor de **0,50 $ a 1,20 $**. Con la caché del prompt, menos.

Qwen3.8 Flash (lo que en la práctica es el "Qwen 3.8 Lite") está en unos 0,15 $ / 0,47 $ por millón. GLM-5.3 Flash, en la tarifa de Z.ai, unos 0,15 $ / 0,50 $. Los dos clasifican en español. Salen más caros en la salida, que es justo el JSON. OpenAI queda como alternativa si la empresa ya lo exige: para clasificar no hace falta el modelo de frontera y la factura se nota.

Se cambia en Configuración, campos `llm_model` y `llm_base_url`. La credencial es solo la clave.

## El prompt

La fuente de verdad es `prompts/clasificador.md`. No está metido en un Code node: el flujo 01 lo carga en el campo `prompt` del nodo Configuración, que es el texto que se ve en el lienzo.

Para cambiarlo: edita el Markdown, ejecuta `python3 scripts/build_workflows.py` y vuelve a importar el 01. Si estás en cámara y no quieres reimportar, pega el texto nuevo en ese campo. El siguiente correo ya lo usa.

`scripts/build_workflows.py` también copia `src/` dentro de los nodos Code. Si cambias la normalización o la decisión, regenera los JSON. Los tests de esa lógica son `node scripts/check.js`, que además comprueba que el prompt horneado en el 01 es el de `prompts/clasificador.md`. `python3 scripts/build_workflows.py --check` falla si algún JSON no está al día.

## Qué pasa si nadie pulsa

`approval_hours` es 24. El 03a guarda `approval_due_at`. El flujo 05, a las 06:00 UTC, pasa esas filas (y las que se quedaron a medias en Editar) a `aprobacion_vencida` y las cuenta en el resumen. No se envían solas. Si alguien pulsa un botón después del plazo, aunque el 05 aún no haya pasado, el 03b no envía: marca la fila vencida y el botón lo dice.

## Botones de Telegram

- Solo cuenta el chat de `telegram_chat_id` (y las personas de `telegram_user_ids`, si lo rellenas). Un botón o un texto de cualquier otro chat no hace nada, no recibe respuesta y queda apuntado como `telegram_ajeno`. Mientras `telegram_chat_id` tenga el valor de ejemplo, no vale nadie.
- No uses el campo *Restrict to Chat IDs* del trigger de Telegram: en n8n 2.10.2 mira `message.chat.id`, que un botón no trae, y descartaría todos los botones. El filtro está en el nodo "Leer update".
- Aprobar dos veces, aprobar después de Rechazar o con la fila ya enviada no manda nada: el botón contesta con un aviso ("Ya se respondió", "Ya estaba rechazado", "Venció el plazo").
- Editar manda un mensaje que hay que **responder** (Telegram abre la respuesta solo). Ese texto es el que sale. Un texto suelto, que no responde a ese mensaje, no se envía a nadie.

## Si algo falla

Ningún error se queda callado. Cada uno deja la fila en un estado y, si se puede, avisa por Telegram:

| Qué falla | Estado | Aviso |
|---|---|---|
| El 01 no consigue llamar al 02, 03a o 04 (flujo sin publicar, `n8n_url` o Mail API Key mal) | `error_interno` | Telegram desde el 01 |
| El SMTP (o el runner de Python) | `error_envio` | Telegram con Reintentar, Rechazar y Editar |
| Telegram no acepta el aviso de aprobación | `error_aviso` | No se puede avisar por Telegram: sale en el resumen |
| GitHub no crea la issue | `error_accion` | Telegram |
| El 03b no consigue llamar al 02 | vuelve a `esperando_aprobacion` | Telegram: pulsa Aprobar otra vez cuando esté |

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

La issue de GitHub es otra copia, y el repo de pruebas suele ser público. Por eso lleva lo mínimo: el asunto y el cuerpo con correos, teléfonos, IBAN, DNI y números largos tapados, las URL sin parámetros, el texto dentro de un bloque de código (un `@usuario` no avisa a nadie) y una referencia interna (el `id` de la fila). No lleva remitente, ni Message-ID, ni enlace `mailto`. Quién escribió se mira en `mail_messages` con esa referencia. Aun así, el tapado es por patrones: un nombre propio en el cuerpo se queda. Con correo real, mejor un repo privado.

## Idempotencia y bucles

La clave única es `message_id` (la cabecera Message-ID). Lo primero que hace el 01 es reservarla (`procesando`), antes de llamar al RAG o al modelo. Un segundo insert no crea fila: el flujo anota `duplicado` en el log y no llama al modelo, aunque lleguen cuatro copias a la vez.

Si el correo no trae Message-ID, el 01 calcula uno estable con remitente, destinatario, fecha, asunto y cuerpo (`generado-` + SHA-256). El mismo correo leído dos veces da la misma clave. A ese correo se le contesta sin `In-Reply-To`: no se inventa un id que el cliente no tiene.

No se contesta si la cabecera `Auto-Submitted` no es `no`, si viene `X-Autoreply`, `X-Autorespond`, `List-Id`, si la precedencia es bulk/list/junk, si el remitente es del estilo `no-reply@`, `mailer-daemon` o `postmaster`, o si el From no es una sola dirección normal (dos direcciones o caracteres raros: la respuesta podría acabar en un tercero). El correo 10 es la autorespuesta de vacaciones: se guarda como `ignorado_autorespuesta` y no sale nada. El nodo IMAP va en formato *simple*: así entrega todas las cabeceras en `metadata`, que es lo que lee el filtro. Las respuestas automáticas salen con `Auto-Submitted: auto-replied` (RFC 3834), para que otra autorespuesta no conteste.

El flujo 02 tampoco manda una respuesta automática a una dirección que ya recibió una en la última hora. Esa fila queda en `retenido_bucle`.

## Hilo del correo

El nodo Send Email de n8n 2.10.2 pone asunto, cuerpo y Reply-To, y nada más: no hay campo para `In-Reply-To` ni `References` (tampoco en las versiones 2.x posteriores, mirado en el código de n8n). Sin esas cabeceras, Gmail, Outlook o Apple Mail pueden no meter la respuesta en el hilo del cliente.

Por eso el envío lo hace un **Code node de Python** con `smtplib`, de la biblioteca estándar. Está en `src/send_mail.py` y `scripts/build_workflows.py` lo copia dentro de los nodos "Enviar" (02) y los dos acuses (04). Pone `In-Reply-To` con el Message-ID del cliente, `References` con su cadena más ese id, un Message-ID propio (se guarda en `reply_message_id`) y quita los saltos de línea de todo lo que viene del correo, para que nadie cuele una cabecera.

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
node scripts/check.js                     # normalización, filtros, decisión, botones, issue, JSON de los flujos
python3 scripts/check_mail.py             # el envío por SMTP en el hilo, con un servidor falso
python3 scripts/build_workflows.py --check  # los JSON están al día con src/ y prompts/
```

Doce ficheros en `test-emails/`. El script los manda tal cual, Message-ID incluido:

```bash
cp .env.example .env
python3 test-emails/send.py
python3 test-emails/send.py --resend 01
```

| Fichero | Qué tiene que pasar |
|---|---|
| 01 Consulta clara | Horario, que está en la FAQ. Respuesta sola, con fuente. |
| 02 Ambigua | Muy corta. A Telegram. |
| 03 Fuera de la base | SAP. A Telegram, no se inventa un conector. |
| 04 Bug con detalle | Acuse en el hilo e issue en el repo de pruebas, sin el correo del remitente. |
| 05 Bug mal escrito | También issue. |
| 06 Lead | Se guarda el contacto y el borrador. No se envía solo. |
| 07 Urgente | Telegram al momento. |
| 08 Spam | No se contesta. La fila queda como descartado. |
| 09 Inyección | No promete el reembolso. Llega a Telegram sin borrador y sin Aprobar. |
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
