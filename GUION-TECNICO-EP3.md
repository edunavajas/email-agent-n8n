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

**HACES:** *Workflows → Import from File*, uno por uno, en este orden: 01, 02, 03a, 03b, 04, 05.

**TARDA:** la importación por CLI de los seis tardó unos 15 segundos, copiar ficheros incluido. En la interfaz, cuenta unos 20–40 segundos por fichero si el navegador va justo. El 01 pesa más porque lleva el prompt.

**EN PANTALLA:** el lienzo. Quédate en el nodo Configuración, no en un Code node.

**SI FALLA:** si n8n dice que el JSON no es válido, no lo edites a mano. Regenera con `python3 scripts/build_workflows.py` y vuelve a subir.

**CENSURA:** nada, todavía no hay claves.

Di en voz alta que son seis ficheros y cinco trabajos, y que el 3 está partido para no usar Wait.

---

## 3. Credenciales, en este orden

Hazlas antes de activar nada.

1. **PostgreSQL.** La misma del episodio 2. Host `knowledge-db`.
2. **RAG API Key.** La misma cabecera `X-RAG-API-Key`.
3. **Mail API Key.** Nueva. Cabecera `X-MAIL-API-Key`. Te la inventas y la repites en todos los webhooks internos y en los HTTP que los llaman.
4. **IMAP y SMTP** del buzón `soporte@`. Hostinger: `imap.hostinger.com:993` y `smtp.hostinger.com:465`.
5. **LLM API.** Header `Authorization`, valor `Bearer sk-...`. DeepSeek V4 Flash.
6. **Telegram.** Token de BotFather. Un solo bot: Telegram no admite dos triggers del mismo bot.
7. **GitHub Issues.** Fine-grained, solo Issues, repo vacío. No el de un producto.

**TARDA:** si las tienes en un gestor, 8–12 minutos. BotFather y el token de GitHub son lo que más se alarga si no están creados. No lo he cronometrado con un alta nueva: no había buzón ni bot en esta máquina.

**EN PANTALLA:** el formulario de la credencial. El valor, tapado.

**SI FALLA:** un 401 del RAG es la cabecera mal puesta (`X-RAG-API-Key`, no `Authorization`). Un 401 de DeepSeek es el `Bearer`. El nodo SMTP no avisa de que no manda `In-Reply-To`: simplemente no tiene ese campo. No lo busques en las opciones.

**CENSURA:** todas. Token, contraseña del buzón, clave del RAG, `github_pat`.

Luego el nodo Configuración: dominio, `rag_url`, `n8n_url`, `telegram_chat_id`, `github_repo`, umbral 0,75. Enseña el umbral y di la frase: subir = más Telegram, bajar = más respuestas solas y más riesgo.

---

## 4. La FAQ dentro del RAG

**HACES:** indexa `kb/faq-soporte.md` como un documento `repo`, sin `replace_all` sobre el resto del índice.

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

- Aprobar llama al flujo 02 y el cliente recibe el borrador.
- Rechazar no envía. La fila pasa a `rechazado`.
- Editar pide un mensaje de respuesta. Ese mensaje es otro update: lo coge el 03b, guarda el texto y entonces envía.

**NO HE PULSADO NINGÚN BOTÓN.** No hay token de Telegram en el n8n del episodio. Los flujos están importados y parados.

**SI FALLA:** "botón que gira y no hace nada" = el 03b no está activo, o hay otro trigger del mismo bot. "No encuentro la fila" = el `message_id` que guardó el 03a no es el del mensaje del botón. Mira la columna `telegram_message_id`.

**CENSURA:** el token del bot si abres BotFather o `getUpdates`.

### Si nadie pulsa

A las 24 horas el flujo 05 marca `aprobacion_vencida`. No se envía. La comprobación va con el resumen de las 06:00 UTC, no en un temporizador aparte. Para enseñarlo sin esperar un día: pon `approval_due_at` en el pasado o baja `approval_hours` a 0 y pulsa "Resumen ahora". Lo he ejecutado en SQL: una fila vencida pasa a `aprobacion_vencida`. No he esperado 24 horas de reloj.

### El reinicio

Lo he hecho. Puse una fila `esperando_aprobacion` con `telegram_message_id` 4242, reinicié el n8n del episodio 2 y la fila seguía. El botón, en un bot de verdad, preguntaría a esa fila. El primer reinicio lo rompí yo: copié el sqlite como root y n8n entró en bucle (`SQLITE_READONLY`). Los flujos del episodio 2 no se perdieron. Un reinicio limpio, después, respondió a `list:workflow` en unos 10 segundos.

No reinicies el n8n de NihongoHUB. Este era el del proyecto "Ep2 Knowledge Hub".

---

## 7. Bug, urgente, spam, inyección, vacaciones, hilo largo

Hazlos en este orden, que es el de la historia:

1. **04** bug detallado. Tiene que aparecer la issue en el repo vacío, con remitente, cuerpo y un `mailto:` de vuelta. El acuse lleva el número.
2. **07** urgente. El Telegram del equipo sale antes del resumen. No esperes al día siguiente para enseñarlo.
3. **08** spam. No hay respuesta. La fila está, estado `descartado`.
4. **09** inyección. Léelo en voz alta. El sistema no dice que devuelve el dinero. Enseña el borrador sustituido o la ruta a una persona.
5. **10** vacaciones. No sale correo. Estado `ignorado_autorespuesta`.
6. **11** el hilo de quince respuestas. Enseña el cuerpo ya limpio: solo la pregunta del horario. `node scripts/check.js` lo comprueba; el cuerpo limpio queda por debajo de 500 caracteres y no contiene "respuesta citada número 15".
7. Reenvía el **01** con el mismo Message-ID (`send.py --resend 01`). Segunda fila: no. En el log, `duplicado`. Esto sí lo he ejecutado en la base, con un id de prueba, y el segundo insert no creó fila.

**Issue de GitHub:** el nodo está en el flujo 04. No lo he disparado. No he creado una issue de prueba para no dejar basura antes de la toma. El repo de destino lo creas tú, vacío, delante de cámara o justo antes.

**CENSURA:** el token de GitHub. Si la issue lleva un correo real, píxelalo. Los de `test-emails/` son `@example` y se pueden ver.

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

Medido en el VPS del episodio 2 (23,4 GiB). Outline no está en este host: el contenedor no existe aquí, la wiki vive en `docs.nihongohub.online`. No he levantado Outline para no tocar eso.

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

1. **El nodo Enviar email no pone `In-Reply-To`.** Lo miré en el código de n8n 2.10.2, dentro de la imagen. Tiene Reply-To y ya está. El runner no deja abrir un socket (`crypto` y `moment` nada más). El hilo estricto no está resuelto. El asunto sale como `Re:`.
2. **`$env` no funciona.** Coolify deja `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`. El modelo se cambia en el nodo Configuración, no en una variable. El `.env` es la lista y el script de envío.
3. **El RAG no devuelve la fecha.** Devuelve título, URL, score y texto. La fecha la leo de `knowledge_documents`.
4. **Un score de 0,86 no significa que la página responda.** La pregunta de SAP cayó sobre páginas que no hablan de SAP. Por eso hay una segunda comprobación: las palabras de la pregunta tienen que estar en el fragmento.
5. **La firma no se iba.** El corte buscaba `-- ` al principio de línea. El HTML dejaba ` --` con un espacio delante y "Enviado desde mi iPhone" sobrevivía. El correo 1 lo cazó. Ya corta esa línea.
6. **Un umbral de "pregunta corta" a 80 caracteres** habría mandado a Telegram también el horario, que es una frase. Lo bajé a 40. El 02 ("¿me lo podéis mirar?") sigue yendo a una persona.
7. **Importar por `docker cp` a `/tmp` del contenedor** falla: el proceso es el usuario `node` y `/tmp` queda de root. Hay que dejar los JSON en `/home/node`.
8. **Copiar el sqlite de n8n como root tira la instancia.** `SQLITE_READONLY` y bucle de arranque. Se arregla devolviendo el fichero al uid 1000. No lo hagas en cámara. No toqué el n8n de NihongoHUB.
9. **No hay buzón, ni bot, ni clave de modelo, ni token de issues en este entorno.** La decisión, el esquema, el RAG vivo y el reinicio sí. El correo saliendo al remitente y el dedo en el botón, no.

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

El 05 (bug vago) y el 06 (lead) mételos si te sobra tiempo. Están en el repo para que la tabla esté completa; en cámara el bug detallado y el lead se explican en una frase.

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
