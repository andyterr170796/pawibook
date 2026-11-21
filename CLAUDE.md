# Pawbook — red social para mascotas

Web para perfiles de mascotas y entidades (veterinarias, tiendas, refugios, restaurantes, etc.), con amigos, búsqueda, pareja, calendario con alertas, mapa, restaurantes pet friendly, perdidos y encontrados, anuncios y el asistente **Pawi**.

## Stack
- FastAPI + Uvicorn, SQLAlchemy + SQLite (`pawbook.db`), Jinja2 + CSS/JS propios (sin build).
- Leaflet (mapa, tiles de OpenStreetMap), marked + DOMPurify (Markdown del chat) desde cdnjs.
- Pawi: OpenAI **Responses API** con streaming NDJSON (mismo patrón que UFIto de la web UFI).
- Puerto **8001** (la web UFI usa 8000).

## Ejecutar
- `iniciar_local.bat` → `python main.py --abrir` → http://localhost:8001
- `iniciar_ngrok.bat` → `python main.py --ngrok --abrir` → abre túnel con pyngrok, imprime y copia el enlace público. Ctrl+C cierra servidor y túnel.
- Configuración en `.env` (ver `.env.example`): `OPENAI_API_KEY`, `PAWBOOK_MODELO`, `PAWBOOK_PUERTO`, `NGROK_DOMAIN`, `PAWBOOK_ADMIN_*`, `PAWBOOK_DEMO`, `RESEND_API_KEY`, `RESEND_FROM`, `PAWBOOK_URL_PUBLICA`, `PAWBOOK_DB` / `PAWBOOK_UPLOADS` / `PAWBOOK_LOGS` (rutas alternativas, útiles para pruebas).
- Pruebas de seguridad: `python -m unittest discover -s pruebas -v` (base temporal, no tocan `pawbook.db` ni envían correos). Corren también en GitHub Actions (`.github/workflows/pruebas.yml`).
- Probar Resend: `python correos.py tu@correo.com`.
- Repo: https://github.com/andyterr170796/pawibook (**público**: nada de `.env`, `.secret_key`, `credenciales_admin.txt`, `pawbook.db*`, `uploads/`, `logs/`).

## Archivos
| Archivo | Qué contiene |
|---|---|
| `main.py` | App FastAPI: rutas, sesión, cuenta/contraseña, recuperación, recordatorios, arranque y ngrok |
| `models.py` | Modelos: Usuario, TokenRecuperacion, Perfil (mascota/entidad), Seguimiento, Publicacion, MeGusta, Comentario, Evento, Lugar, Anuncio, Notificacion, InteresPareja, ReportePerdido |
| `seguridad.py` | Cabeceras, rechazo de otros orígenes (CSRF), límite de cuerpo, cookie Secure en HTTPS, límite de intentos, política de contraseñas, `logs/seguridad.log` |
| `correos.py` | Envío con Resend (API HTTP, en hilo aparte) y plantillas: recuperación, bienvenida, contraseña cambiada |
| `migrar_bd.py` | Migración idempotente con respaldo (`ALTER TABLE`); `main.py` la ejecuta al iniciar |
| `pruebas/test_seguridad.py` | Pruebas de seguridad (cada una reproduce un ataque) |
| `catalogos.py` | Especies, razas, tags, categorías, amenidades pet friendly, tipos de aviso y radios de perdidos, tipos de evento, planes y precios de anuncios, países, distritos, íconos SVG |
| `utilidades.py` | Contraseñas (PBKDF2), imágenes (WebP, sin EXIF/GPS), fechas/edad/cumpleaños, distancia, avatar e íconos |
| `asistente.py` | Pawi: prompt, herramientas `buscar_en_pawbook` y `agendar_evento`, streaming |
| `seed.py` | Admin inicial y datos demo (solo si la BD está vacía); `complementar_demo()` agrega restaurantes y avisos demo a una BD demo existente |
| `templates/` | `base.html` (layout, menú, chat), `_macros.html` (publicación, tarjetas, etc.), una plantilla por página |
| `static/` | `css/pawbook.css` (variables de color del logo en `:root`), `js/pawbook.js`, `img/` (logo, icono) |

## Conceptos clave
- **Una cuenta (`Usuario`) maneja varios `Perfil`** (mascotas y/o entidades). El perfil activo está en `Usuario.perfil_activo_id`; seguir, publicar, comentar y dar me gusta se hacen como el perfil activo.
- **Seguir** es perfil→perfil (`Seguimiento`). "Amigos" = mascotas seguidas; "Entidades" = entidades seguidas.
- **Pareja**: solo si ambas mascotas tienen `busca_pareja`, misma especie, sexo opuesto, ≥1 año y distinto dueño (`es_compatible`). "Me interesa" mutuo = match.
- **Calendario**: `Evento` por mascota + cumpleaños calculados (propios y de mascotas seguidas). `procesar_recordatorios()` crea notificaciones de alertas y cumpleaños (máx. cada 10 min por sesión, `Notificacion.clave` evita duplicados).
- **Mapa** (`/api/mapa`): entidades con coordenadas + `Lugar` (parques) + mascotas seguidas o del mismo distrito. Las coordenadas de mascotas se redondean (~100 m) por privacidad.
- **Anuncios**: solo perfiles de entidad. Gratuitos para `centro_adopcion`/`caridad` o campañas gratuitas de vacunación/esterilización; pagados con plan (`PLANES_ANUNCIO`). Todos quedan `pendiente` hasta que un admin los aprueba en `/admin`. Pago: coordinación manual (no hay pasarela).
- **Restaurantes pet friendly** (`/pet-friendly`): entidades con `categoria="restaurante"` + `Lugar` tipo `restaurante`. Lo que ofrecen (terraza, agua, menú...) se guarda en `Perfil.tags` de la entidad con claves de `AMENIDADES_PET_FRIENDLY`. Capa `petfriendly` del mapa.
- **Perdidos y encontrados** (`/perdidos`): `ReportePerdido` (`tipo` perdido/encontrado, `estado` activo/resuelto, coords redondeadas). Al publicar, `avisar_reporte()` notifica a seguidores de la mascota, vecinos (mismo distrito o ≤ `RADIO_AVISO_KM`, una notificación por cuenta) y avisos que podrían coincidir (`coincidencias()`). Claves `aviso:{id}:{usuario_id}` / `coincide:{id}:{otro}`; al resolver se avisa a los mismos con `aviso-fin:`. La tabla usa AUTOINCREMENT para no reutilizar ids. Capa `perdidos` del mapa.
- **Perfiles públicos**: `/p/{handle}`, `/perdidos`, `/perdidos/{id}` y `/pet-friendly` se pueden ver sin sesión (para compartir por ngrok).
- **Seguridad** (mismo esquema que la Suite Zoria): todo POST/PUT/PATCH/DELETE con `Origin` ajeno (o `Sec-Fetch-Site: cross-site`) → 403; 120 escrituras/min por IP; login 5/min por IP y por correo con demora igual si el correo no existe; registro 5/h por IP; recuperación 3/h por correo y 5/h por IP; Pawi 10/min y 100/día por cuenta. Cuerpo máx. 25 MB. Imágenes solo JPEG/PNG/WEBP/GIF, ≤ 40 MP, re-guardadas como WebP. Contraseñas: 8–128, mayúscula, minúscula y número; PBKDF2 600 000 (se re-hashea al entrar). Uvicorn solo confía en `X-Forwarded-*` desde 127.0.0.1 (agente ngrok).
- **Sesión**: cookie firmada `pawbook_sesion` con `uid` y `ver`. `Usuario.version_sesion` sube al cambiar/restablecer la contraseña o al "cerrar las demás sesiones"; una cookie con otra `ver` deja de valer. Usa `iniciar_sesion(request, u)` para entrar. Logout solo por POST.
- **Correos (Resend)**: `/recuperar` → `TokenRecuperacion` (solo SHA-256, 60 min, un uso, uno nuevo anula los anteriores) → `/restablecer?token=`. Los enlaces usan `url_publica()` (`PAWBOOK_URL_PUBLICA` → túnel ngrok → localhost), **nunca** la cabecera Host. No se envía a cuentas demo ni a dominios ficticios (`correos.es_destino_entregable`). Respuesta idéntica exista o no la cuenta.
- **Cuentas demo** (`demo@pawbook.pe`, `*@pawbook.demo`): contraseña aleatoria, se entra con el botón demo; no pueden cambiar contraseña, cerrar sesiones ni recibir correos.

## Convenciones
- Plantillas: `{% extends "base.html" %}` + `{% import "_macros.html" as m with context %}`; bloques `titulo`, `contenido`, `derecha`, `head`, `scripts`, `scripts_previos`. `shell_clase` = `sin-derecha` para páginas sin columna derecha.
- Íconos: `{{ icono('nombre', tam) }}` (definidos en `catalogos.ICONOS`). Avatares: `{{ avatar(perfil, tam) }}`.
- Mensajes flash: `flash(request, texto, "ok"|"error")`.
- Sin migraciones automáticas: si agregas columnas, agrégalas a `COLUMNAS_NUEVAS` de `migrar_bd.py` (respalda `pawbook.db` y hace el `ALTER TABLE`; las tablas nuevas las crea `create_all`).
- Formularios que cambian datos: siempre `method="post"` (el chequeo de origen y SameSite=Lax protegen POST, no GET). Redirecciones con `siguiente_seguro()` / `volver()`, nunca a una URL recibida sin validar.
- Rutas con formulario que deben limitar intentos: `intentos_agotados(request, (ámbito, clave, límite, ventana_seg))` y re-renderizar con `con_estado(..., 429)`; en `/api/` usar `seguridad.limitar(...)`.
- Contraseñas nuevas: validar con `seguridad.error_password()`; tras cambiarla subir `version_sesion` y avisar con `avisar_cambio_password(u)`.
