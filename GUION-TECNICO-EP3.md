# GUION TÉCNICO — Episodio 3 "Mi Empleado Digital"

**Título de trabajo:** "Un empleado que lee el correo y sabe cuándo callarse"
**Punto de partida:** Coolify + Outline + PostgreSQL/pgvector + n8n + el RAG del episodio 2.
**Qué está probado de verdad y qué no:** la tabla del final. No taches un paso como hecho si esa tabla dice que no.

Los seis flujos ya están importados en el n8n del episodio 2, inactivos y sin las credenciales nuevas. Si quieres el plano de "Import from File" en cámara, bórralos antes de esa toma. No borres los cinco del episodio 2.

---

## 0. Lo que tienes que poder decir

| Pieza | Para qué |
|---|---|
| Flujo 01 | Entender el correo sin tragarse el HTML ni la cadena de respuestas. |
| Flujo 02 | Contestar solo cuando la base de conocimiento lo sostiene. |
| Flujos 03a y 03b | Pedir un humano sin dejar la ejecución colgada en memoria. |
| Flujo 04 | Hacer algo con consecuencias (issue, urgente, lead) fuera de la respuesta automática. |
| Flujo 05 | Un resumen con números, no un volcado. |

Frase de la arquitectura, para cámara: *"El botón de Telegram no espera dentro de n8n. Escribe en la base quién tiene que decidir y se va. Si el servidor se reinicia, el botón sigue vivo porque la fila sigue ahí."*

---

## 1. Las tablas

**HACES:** en la base `knowledge` del episodio 2, `psql -f schema.sql`.

**TARDA:** unos 3 segundos. Medido.

**EN PANTALLA:** `CREATE TABLE` dos veces y los índices. Nada de datos.

**SI FALLA:** si dice que la relación ya existe, el esquema ya está. No lo lances dos veces "por si acaso" sobre otra base. Host `knowledge-db`, no un Postgres que se llame `postgres`: en la red `coolify` ese nombre apunta a más de un sitio (episodio 2).

**CENSURA:** la contraseña de la credencial si el terminal la tiene en el `psql` URL.

---

## 2. Importar los seis JSON

**ANTES:** crea las credenciales del punto 3 con sus nombres exactos. Los nodos las piden por nombre y n8n las enlaza solas al importar (probado por CLI en un n8n 2.10.2 limpio: los 57 nodos con credencial quedaron enlazados). Si importas antes, eliges cada credencial a mano.

**HACES:** *Workflows → Import from File*, uno por uno, en este orden: 01, 02, 03a, 03b, 04, 05.

**TARDA:** la importación por CLI de los seis tardó unos 15 segundos, copiar ficheros incluido. En la interfaz, cuenta unos 20–40 segundos por fichero si el navegador va justo. El 01 pesa más porque lleva el prompt.

**EN PANTALLA:** el lienzo. Quédate en el nodo Configuración, no en un Code node.

**SI FALLA:** si n8n dice que el JSON no es válido, no lo edites a mano. Regenera con `python3 scripts/build_workflows.py` y vuelve a subir.

**CENSURA:** nada, todavía no hay claves.

Di en voz alta que son seis ficheros y cinco trabajos, y que el 3 está partido para no usar Wait.

---

## 3. Credenciales, en este orden

Hazlas antes de importar. Los nombres en negrita son los que buscan los nodos.

1. **PostgreSQL.** La misma del episodio 2. Host `knowledge-db`.
2. **RAG API Key.** La misma cabecera `X-RAG-API-Key`.
3. **Mail API Key.** Nueva. Cabecera `X-MAIL-API-Key`. Te la inventas: es la misma credencial en los webhooks internos y en los HTTP que los llaman.
4. **IMAP** del buzón del agente: un Gmail gratuito con contraseña de aplicación (`imap.gmail.com:993`, SSL). Alternativa de pago o de empresa: ver README, «Otro buzón».
5. **LLM API.** Header `Authorization`, valor `Bearer sk-...`. DeepSeek Flash (`deepseek-flash`).
6. **Telegram.** Token de BotFather. Un solo bot: Telegram no admite dos triggers del mismo bot.
7. **GitHub Issues.** Fine-grained, solo Issues, repo vacío. No el de un producto.

El **SMTP no es una credencial de n8n.** Lo envía un Code node de Python para poder poner `In-Reply-To` y `References` (el nodo Send Email no tiene esos campos). En Coolify, en el servicio de n8n, contenedor `task-runners`: monta `runners/n8n-task-runners.json` en `/etc/n8n-task-runners.json` y añade `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=465`, `SMTP_SECURITY=ssl`, `SMTP_USER` (la dirección de Gmail) y `SMTP_PASSWORD` (la misma contraseña de aplicación). Reinicia el servicio entero.

**TARDA:** si las tienes en un gestor, 8–12 minutos. BotFather y el token de GitHub son lo que más se alarga si no están creados. No lo he cronometrado con un alta nueva: no había buzón ni bot en esta máquina.

**EN PANTALLA:** el formulario de la credencial. El valor, tapado.

**SI FALLA:** un 401 del RAG es la cabecera mal puesta (`X-RAG-API-Key`, no `Authorization`). Un 401 de DeepSeek es el `Bearer`. Si el envío falla con "el nodo Enviar (Python) no se ejecutó", el contenedor `task-runners` no tiene el fichero montado o perdió la conexión: reinícialo.

**CENSURA:** todas. Token, contraseña del buzón (también en las variables del contenedor), clave del RAG, `github_pat`.

Luego el nodo Configuración: `support_address`, `telegram_chat_id`, `github_repo`, umbral 0,75. `n8n_url` y `rag_url` ya vienen con `http://localhost:5678`: n8n se llama a sí mismo. Enseña el umbral y di la frase: subir = más Telegram, bajar = más respuestas solas y más riesgo.

---

## 4. La FAQ dentro del RAG

**HACES:** indexa `kb/faq-soporte.md` como un documento `repo` con `POST /webhook/rag-index-repo`. Ese flujo exige `replace_all: true` y borra del índice los documentos `repo` que no vengan en el lote (los de Outline no se tocan). Si la FAQ es tu único documento de repo, no pasa nada. Si tienes más, mándalos todos en el mismo lote. Es asíncrono: responde `Workflow was started` y tarda unos 20 s.

**TARDA:** el embedding de esa página, contra el TEI del episodio 2, tardó unos 9 segundos. La búsqueda siguiente, unos 4 segundos, y el primer resultado fue esa FAQ con score 0,90.

**EN PANTALLA:** el `curl` de `/webhook/rag-search` con la pregunta del horario. Se ve el título y la URL.

**SI FALLA:** si el score alto es una página de Outline que no habla del horario, la FAQ no está indexada. No bajes el umbral para "que conteste algo".

**CENSURA:** la cabecera `X-RAG-API-Key`.

Pregunta de control que hice: "integración con SAP". El mejor fragmento fue una página que no habla de SAP, con score 0,86. Por eso el flujo no se fía solo del número: el fragmento tiene que contener las palabras de la pregunta. Cuéntalo. Es el momento en que se ve que el episodio 2 busca por significado y este episodio decide si eso basta para contestar a un cliente.

---

## 5. El correo que se responde solo

**HACES:** activa 01, 02 y el RAG. Manda `01-consulta-clara.eml`.

**EN PANTALLA:** la ejecución del 01, el nodo Decidir con ruta `auto`, y el correo que vuelve al remitente. El cuerpo tiene que hablar del horario de 9 a 18 y no prometer otra cosa.

**QUÉ TARDA:** no lo he mandado por un buzón real. No hay IMAP ni SMTP de prueba en esta máquina. La lógica que decide `auto` sí está ejecutada (`node scripts/check.js`) y la FAQ sí sale del RAG vivo.

**SI FALLA:** si va a Telegram, mira el score y si el fragmento es la FAQ. Si el modelo no devolvió JSON, la fila queda en revisión humana: es el comportamiento bueno, no un descarte.

**CENSURA:** el remitente, si en la toma usas un correo real en vez de `ana@cliente.example`.

---

## 6. Telegram: aprobar, rechazar, editar

**HACES:** manda el 02 y el 03. En el móvil tienen que verse remitente, asunto, categoría, confianza, borrador y fuentes. Tres botones: Aprobar, Rechazar, Editar.

- Aprobar llama al flujo 02 y el cliente recibe el borrador, en el mismo hilo.
- Rechazar no envía. La fila pasa a `rechazado`.
- Editar pide un mensaje de respuesta. Hay que **responder** a ese mensaje (Telegram abre la respuesta solo). Ese mensaje es otro update: lo coge el 03b, guarda el texto y entonces envía. Un texto suelto no se envía a nadie.
- Pulsa Aprobar dos veces delante de cámara: el segundo toque contesta "Ya se respondió" y no sale otro correo. Lo mismo con Aprobar después de Rechazar.
- Solo vale tu chat (`telegram_chat_id`). Un botón desde otro chat no hace nada y queda apuntado como `telegram_ajeno`.

**NO HE PULSADO NINGÚN BOTÓN.** No hay token de Telegram en el n8n del episodio. Los flujos están importados y parados.

**SI FALLA:** "botón que gira y no hace nada" = el 03b no está activo, o hay otro trigger del mismo bot, o `telegram_chat_id` no es tu chat (mira `mail_actions` con `action = 'telegram_ajeno'`). No rellenes *Restrict to Chat IDs* en el trigger: en 2.10.2 descarta los botones. "No encuentro la fila" = el `message_id` que guardó el 03a no es el del mensaje del botón. Mira la columna `telegram_message_id`.

**CENSURA:** el token del bot si abres BotFather o `getUpdates`.

### Si nadie pulsa

A las 24 horas el flujo 05 marca `aprobacion_vencida`. No se envía. La comprobación va con el resumen de las 06:00 UTC, no en un temporizador aparte. Para enseñarlo sin esperar un día: pon `approval_due_at` en el pasado o baja `approval_hours` a 0 y pulsa "Resumen ahora". Lo he ejecutado en SQL: una fila vencida pasa a `aprobacion_vencida`. No he esperado 24 horas de reloj.

### El reinicio

Lo he hecho. Puse una fila `esperando_aprobacion` con `telegram_message_id` 4242, reinicié el n8n del episodio 2 y la fila seguía. El botón, en un bot de verdad, preguntaría a esa fila. El primer reinicio lo rompí yo: copié el sqlite como root y n8n entró en bucle (`SQLITE_READONLY`). Los flujos del episodio 2 no se perdieron. Un reinicio limpio, después, respondió a `list:workflow` en unos 10 segundos.

No reinicies un n8n de otro proyecto que viva en la misma máquina. Si reinicias solo el contenedor de n8n, reinicia también `task-runners`: en la prueba de la revisión (n8n 2.10.2), el runner de Python no se volvió a conectar solo y los envíos fallaban hasta reiniciarlo.

---

## 7. Bug, urgente, spam, inyección, vacaciones, hilo largo

Hazlos en este orden, que es el de la historia:

1. **04** bug detallado. Tiene que aparecer la issue en el repo vacío, con el asunto, el cuerpo con los datos de contacto tapados y una referencia interna. Sin remitente ni `mailto:`: el repo es público. El acuse lleva la referencia (#N), sin enlace a GitHub, y va en el hilo.
2. **07** urgente. El Telegram del equipo sale antes del resumen. No esperes al día siguiente para enseñarlo.
3. **08** spam. No hay respuesta. La fila está, estado `descartado`.
4. **09** inyección. Léelo en voz alta. El sistema no dice que devuelve el dinero. En Telegram llega sin borrador y sin botón Aprobar: solo Rechazar o Editar. Lo único que puede salir es lo que escribas tú.
5. **10** vacaciones. No sale correo. Estado `ignorado_autorespuesta`.
6. **11** el hilo de quince respuestas. Enseña el cuerpo ya limpio: solo la pregunta del horario. `node scripts/check.js` lo comprueba; el cuerpo limpio queda por debajo de 500 caracteres y no contiene "respuesta citada número 15".
7. Reenvía el **01** con el mismo Message-ID (`send.py --resend 01`). Segunda fila: no. En el log, `duplicado`. Esto sí lo he ejecutado en la base, con un id de prueba, y el segundo insert no creó fila. Con Gmail el reenvío puede no llegar (deduplica por Message-ID): entonces, `POST /webhook/mail-ingest` con el mismo `message_id`.
8. **Freno anti-bucles.** Manda otra vez el **01**, con Message-ID nuevo (`send.py --only 01`), antes de que pase una hora. No sale solo: llega a Telegram con el borrador, los tres botones y «Retenido por el freno anti-bucles: a esta dirección ya se le contestó automáticamente hace menos de una hora». Aprobar lo envía, en el hilo. Todos los correos de prueba salen del mismo buzón cliente: cualquier segunda respuesta automática dentro de esa hora hace lo mismo. No es un fallo.

**Issue de GitHub:** el nodo está en el flujo 04. No lo he disparado. No he creado una issue de prueba para no dejar basura antes de la toma. El repo de destino lo creas tú, vacío, delante de cámara o justo antes.

**CENSURA:** el token de GitHub. Si la issue lleva algo de un correo real que el tapado no cogió (un nombre), píxelalo. Los de `test-emails/` son `@example` y se pueden ver.

---

## 8. El resumen

**HACES:** flujo 05, botón "Resumen ahora". No esperes a las 06:00 UTC.

**EN PANTALLA:** un mensaje corto. Recibidos, respondidos solos, aprobados, rechazados, leads, issues, spam, urgentes, esperando, vencidas, borrados. Números, no un listado de cuerpos.

**TARDA:** la consulta, con la tabla vacía, es instantánea. No la he mandado a Telegram.

**SI FALLA:** chat id vacío o el bot sin permiso para escribirte. `getUpdates` tiene que mostrar tu chat.

**CENSURA:** el chat id si se considera identificable. El texto del resumen, no.

La retención de 90 días corre en el mismo flujo. Lo probé borrando una fila con fecha de hace 200 días. Desapareció. No borres la toma de Outline: este delete solo mira `mail_messages`.

---

## Tiempos muertos

Córtalos o prepáralos. No son el contenido.

| Espera | Cuánto medí | Qué se ve |
|---|---|---|
| `schema.sql` | ~3 s | El terminal quieto un instante. |
| Importar 6 JSON por CLI | ~15 s | Barra de n8n. En UI será más. |
| Embedding de la FAQ | ~9 s | El curl del TEI sin pintar nada. |
| Una búsqueda RAG | ~4 s | El webhook pensando. |
| Reinicio limpio de n8n | ~10 s hasta que lista los flujos | El editor "connection lost". |
| Clasificación con DeepSeek | No la he llamado. Cuenta 3–8 s y ten un plano del móvil. | El nodo Clasificar en "running". |
| IMAP desde que mandas el correo | No lo he medido. El nodo usa IDLE; a veces es segundos y a veces un minuto. | La bandeja. |
| Alta de BotFather y token de GitHub | No cronometrada. Hazlas antes de darle a grabar. | — |

---

## RAM

Medido en el VPS del episodio 2 (23,4 GiB). Outline no estaba en ese host. No lo levanté para no tocar eso.

| | Antes | Después de importar y reiniciar |
|---|---|---|
| n8n del episodio 2 | 222 MiB | 218 MiB |
| task runners | 78 MiB | 148 MiB justo después del reinicio |
| Postgres `knowledge-db` | 21 MiB | 17 MiB |
| Host, usada / disponible | 14,7 GiB / 9,2 GiB | 14,2 GiB / 9,8 GiB |

El agente no añade contenedor. Son flujos dentro del n8n que ya tenías. El salto de los runners es el reinicio, no un servicio nuevo.

---

## Lo que se rompió

Sin maquillar. Sirve para contarlo.

1. **El nodo Enviar email no pone `In-Reply-To`.** Lo miré en el código de n8n 2.10.2, dentro de la imagen. Tiene Reply-To y ya está (tampoco en las 2.x posteriores). El runner de JavaScript solo deja `crypto` y `moment`. **Resuelto en la revisión:** el envío lo hace un Code node de Python con `smtplib`, en el contenedor `task-runners`, con `runners/n8n-task-runners.json` montado y las `SMTP_*` en sus variables. Probado contra un SMTP de pruebas: salen `In-Reply-To`, `References` y `Auto-Submitted` en las respuestas automáticas.
2. **`$env` no funciona.** Coolify deja `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`. El modelo se cambia en el nodo Configuración, no en una variable. El `.env` es la lista y el script de envío.
3. **El RAG no devuelve la fecha.** Devuelve título, URL, score y texto. La fecha la leo de `knowledge_documents`.
4. **Un score de 0,86 no significa que la página responda.** La pregunta de SAP cayó sobre páginas que no hablan de SAP. Por eso hay una segunda comprobación: las palabras de la pregunta tienen que estar en el fragmento.
5. **La firma no se iba.** El corte buscaba `-- ` al principio de línea. El HTML dejaba ` --` con un espacio delante y "Enviado desde mi iPhone" sobrevivía. El correo 1 lo cazó. Ya corta esa línea.
6. **Un umbral de "pregunta corta" a 80 caracteres** habría mandado a Telegram también el horario, que es una frase. Lo bajé a 40. El 02 ("¿me lo podéis mirar?") sigue yendo a una persona.
7. **Importar por `docker cp` a `/tmp` del contenedor** falla: el proceso es el usuario `node` y `/tmp` queda de root. Hay que dejar los JSON en `/home/node`.
8. **Copiar el sqlite de n8n como root tira la instancia.** `SQLITE_READONLY` y bucle de arranque. Se arregla devolviendo el fichero al uid 1000. No lo hagas en cámara. No toqué el n8n del otro proyecto.
9. **No hay buzón, ni bot, ni clave de modelo, ni token de issues en este entorno.** La decisión, el esquema, el RAG vivo y el reinicio sí. El correo saliendo al remitente y el dedo en el botón, no.
10. **El freno anti-bucles retenía en silencio.** En la prueba con Gmail real, un cliente que preguntó dos cosas en una hora se quedó sin respuesta y sin aviso: la fila se quedaba en `retenido_bucle` y solo salía en el resumen del día siguiente. Ahora el freno sigue cortando el envío automático, pero el correo pasa al 03a y llega a Telegram con el borrador, los tres botones y el motivo.
11. **`Re: (sin asunto)` rompe el hilo en Gmail.** A un correo sin asunto se le contestaba con `Re: (sin asunto)` y Gmail abría un hilo nuevo, con `In-Reply-To` y `References` correctos. Con `Re:` a secas lo mete en el mismo hilo. Ahora sale así.
12. **Acentos rotos en el cuerpo con Gmail.** «El panel de producciÃ³n estÃ¡ caÃ­do» en la base, en Telegram, en la consulta al RAG y en la issue. El asunto, bien. Es el nodo IMAP de n8n 2.10.2 en formato simple: decodifica el quoted-printable sin mirar el charset y cada byte UTF-8 llega como un carácter latin1. Lo miré en el código de `@n8n/imap`, dentro de la imagen. Ahora `normalize.js` lo repara lo primero, solo cuando tiene pinta de eso y releído como UTF-8 es válido. No cambié al formato *resolved*: decodifica bien, pero baja siempre los adjuntos a la ejecución.

---

## Orden de grabación

Los doce correos, si los mandas todos con el flujo ya activo, entran en lote: el IMAP del nodo trae hasta 20 no leídos de una vez y la demo se atropella. No los dejes en la bandeja "para que salgan solos" al darle a grabar.

Orden que sí sale seguido:

1. **Antes de cámara, del todo:** tablas, import, credenciales, Configuración, FAQ indexada, flujos activos, un `curl` de prueba al RAG. BotFather y el token de GitHub hechos. El repo de issues vacío.
2. **Justo antes de darle al rec:** no mandes nada todavía.
3. **Toma 1, la arquitectura.** Lienzo del 01 y del 03a/03b. La frase del Wait. 2 minutos. No hay espera.
4. **Toma 2, uno por uno, con el flujo ya activo.** Manda el 01 y espera la respuesta. Corta el silencio. Luego 02 y 03, y el móvil. Luego 04, 07, 08, 09, 10. El 11 enséñalo en el nodo Normalizar, que es donde se ve el corte. El 12 al final, como nota de idioma.
5. **Toma 3, el reenvío del 01** y, si quieres el reinicio, hazlo con una fila ya en `esperando_aprobacion` y el botón en el móvil antes de reiniciar. Comprueba el botón después, no durante el "connection lost".
6. **Toma 4, Resumen ahora.** Los números tienen que cuadrar con lo que acabas de hacer. Si mandaste los doce, el resumen tiene que decirlo.

El 05 (bug vago) y el 06 (lead) mételos si te sobra tiempo. Están en el repo para que la tabla esté completa; en cámara el bug detallado y el lead se explican en una frase: el lead llega al móvil con la respuesta sugerida, sin botones, y no se contesta solo.

---

## Verificación: qué ejecuté

| Punto | ¿Lo ejecuté? |
|---|---|
| Crear las tablas con `schema.sql` en el Postgres del episodio 2 | Sí |
| Importar los seis flujos en el n8n del episodio 2 | Sí. Inactivos. Sin credenciales nuevas asignadas |
| Configurar IMAP, SMTP, Telegram, LLM y GitHub dentro de n8n | No. No están esas credenciales |
| Mandar los 12 correos a un buzón | No |
| El 1 se responde solo y llega al remitente | No. La ruta `auto` está probada en `scripts/check.js` y la FAQ sale del RAG vivo con score ~0,90 |
| El 2 y el 3 llegan a Telegram | No |
| Aprobar / Rechazar / Editar con el dedo | No |
| El 4 crea la issue | No. El nodo está. No disparé la API |
| El 7 dispara aviso inmediato | No |
| El 8 se descarta y queda registrado | La regla está en el código y en el test. No hay fila real de ese correo |
| El 9 no consigue el reembolso | Sí, en `scripts/check.js`: inyección detectada y el borrador que prometía el dinero no sale |
| El 10 no genera respuesta | Sí, en el test: `Auto-Submitted` + `X-Autoreply` se ignoran |
| El 11 se queda sin la cadena citada | Sí, en el test |
| Reenviar el mismo Message-ID no crea otra fila | Sí, en Postgres |
| Reiniciar n8n con una fila esperando aprobación | Sí. La fila seguía. El botón de un bot real, no lo pulsé |
| El resumen diario con números | La SQL de contar, vencer y borrar está probada. El mensaje de Telegram, no |

El episodio 2 sigue respondiendo al RAG después de los reinicios. Outline no se ha tocado.

---

## Revisión de la fase 3 (29-10-2026)

Probado en un n8n 2.10.2 desechable (`n8nio/n8n:2.10.2` + `n8nio/runners:2.10.2`, como la plantilla de Coolify), con Postgres, un buzón IMAP de pruebas (GreenMail), un SMTP de pruebas (Mailpit) y un servidor falso para Telegram, el modelo, el RAG y GitHub. Nada real: ni buzón, ni bot, ni DeepSeek, ni GitHub.

| Punto | Resultado |
|---|---|
| Importar y publicar los seis flujos por CLI, credenciales enlazadas por nombre | Sí |
| 01 por IMAP (formato simple): HTML limpio, respuesta sola en el hilo | Sí. `In-Reply-To`, `References` y `Auto-Submitted: auto-replied` en el correo recibido |
| 10 por IMAP: las cabeceras de autorespuesta llegan y se ignora | Sí |
| Reenvío del 01, y cuatro copias a la vez del mismo Message-ID | Una fila, un correo, el modelo una vez, tres `duplicado` |
| Correo sin Message-ID, dos veces | Una fila `generado-...`, un correo, sin `In-Reply-To` inventado |
| Aprobar, doble toque, tres toques a la vez, aprobar tras rechazar, tras vencer | Un solo correo. Los toques de más contestan con un aviso |
| Botón y texto desde otro chat | No hacen nada, quedan como `telegram_ajeno` |
| 09: sin Aprobar; Aprobar forzado; Editar respondiendo al mensaje | Aprobar se rechaza. Solo sale el texto escrito por la persona |
| 04 issue sin remitente ni mailto; 07 urgente; 08 spam; 06 lead | Sí |
| SMTP caído, GitHub caído, 02 y 03a sin publicar | `error_envio` / `error_accion` / `error_interno` y aviso a Telegram. Reintentar envía cuando vuelve |
| 05: vence, purga (también botones ajenos viejos) y manda el resumen | Sí |

Queda para la prueba con lo real: el buzón de Gmail por IMAP y SMTP 465, el bot de verdad (botones con el dedo, `force_reply` en el móvil), DeepSeek devolviendo JSON y una issue en GitHub. Y cómo pinta el hilo en Gmail, Outlook y Apple Mail.
