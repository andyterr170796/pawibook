"""Pawi: asistente conversacional de Pawbook (OpenAI Responses API, streaming NDJSON).

Mismo patrón que UFIto: el modelo puede llamar herramientas (buscar en Pawbook, agendar eventos)
antes de dar la respuesta final, y el frontend recibe una línea JSON por evento:
  {"tipo": "estado", "texto": ...}   qué está haciendo
  {"tipo": "texto", "delta": ...}    fragmento de la respuesta
  {"tipo": "accion", "texto": ..., "enlace": ...}   algo que hizo (p. ej. agendó un evento)
  {"tipo": "fin"} / {"tipo": "error", "texto": ...}
"""
import json
import os
from datetime import date, timedelta

import catalogos as cat
from models import Evento, Lugar, Perfil, ReportePerdido, SessionLocal, Usuario
from utilidades import DIAS, MESES, a_fecha, edad_texto, fecha_larga, normalizar, proximo_cumpleanos

MAX_VUELTAS = 6
_cliente = None


def modelo():
    return os.getenv("PAWBOOK_MODELO", "gpt-6.1-terra")


def disponible() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def cliente():
    global _cliente
    if _cliente is None and disponible():
        import openai
        _cliente = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY").strip())
    return _cliente


HERRAMIENTAS = [
    {
        "type": "function",
        "name": "buscar_en_pawbook",
        "description": (
            "Busca en Pawbook entidades (veterinarias, tiendas, centros de adopción, paseadores, entrenadores, "
            "grooming, marcas, ONG, restaurantes y cafés pet friendly), lugares del mapa (parques, restaurantes), "
            "perfiles públicos de mascotas o avisos activos de mascotas perdidas y encontradas. "
            "Devuelve hasta 15 resultados con su enlace dentro de Pawbook."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ["entidad", "lugar", "mascota", "perdido"]},
                "categoria": {
                    "type": ["string", "null"],
                    "description": (
                        "entidad: centro_adopcion, veterinaria, tienda, entrenamiento, paseador, grooming, marca, "
                        "caridad, restaurante, otro. lugar: parque, veterinaria, tienda, restaurante, otro. "
                        "mascota y perdido: especie (perro, gato, conejo, ave, hamster, cuy, tortuga, pez, huron, otro). "
                        "null = todas."
                    ),
                },
                "texto": {"type": ["string", "null"], "description": "Palabras a buscar (nombre, raza, dirección, descripción)"},
                "distrito": {"type": ["string", "null"], "description": "Distrito o ciudad, p. ej. Miraflores"},
            },
            "required": ["tipo", "categoria", "texto", "distrito"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "agendar_evento",
        "description": (
            "Agrega un evento al calendario de una mascota del usuario (cita veterinaria, vacuna, desparasitación, "
            "baño/grooming, medicamento u otro). Úsala solo si el usuario pide agendar o recordar algo y ya "
            "conoces la mascota, la fecha y el motivo."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mascota_id": {"type": "integer", "description": "id de la mascota (ver lista de mascotas del usuario)"},
                "tipo": {"type": "string", "enum": ["veterinaria", "vacuna", "desparasitacion", "grooming", "medicamento", "otro"]},
                "titulo": {"type": "string"},
                "fecha": {"type": "string", "description": "YYYY-MM-DD"},
                "hora": {"type": ["string", "null"], "description": "HH:MM en formato 24 h"},
                "lugar": {"type": ["string", "null"]},
                "notas": {"type": ["string", "null"]},
                "alerta_dias": {"type": ["integer", "null"], "description": "Aviso con 0, 1, 3 o 7 días de anticipación; null sin aviso"},
            },
            "required": ["mascota_id", "tipo", "titulo", "fecha", "hora", "lugar", "notas", "alerta_dias"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


# ------------------------------------------------------------------ herramientas

def _buscar(args: dict) -> dict:
    tipo = args.get("tipo")
    categoria = (args.get("categoria") or "").strip().lower() or None
    texto = normalizar(args.get("texto") or "")
    distrito = normalizar(args.get("distrito") or "")
    resultados = []
    with SessionLocal() as db:
        if tipo == "perdido":
            q = db.query(ReportePerdido).filter(ReportePerdido.estado == "activo")
            if categoria:
                q = q.filter(ReportePerdido.especie == categoria)
            for r in q.order_by(ReportePerdido.id.desc()).limit(200).all():
                bolsa = normalizar(" ".join(filter(None, [r.nombre, r.raza, r.color, r.distrito, r.referencia,
                                                          r.descripcion])))
                if texto and not all(t in bolsa for t in texto.split()):
                    continue
                if distrito and distrito not in normalizar(f"{r.distrito} {r.referencia or ''}"):
                    continue
                resultados.append({
                    "aviso": "mascota perdida (su familia la busca)" if r.tipo == "perdido"
                             else "mascota encontrada (buscan a su familia)",
                    "nombre": r.nombre or None, "especie": cat.ESPECIES.get(r.especie or "otro", ("Otro",))[0],
                    "raza": r.raza, "color_y_senas": r.color, "distrito": r.distrito, "referencia": r.referencia,
                    "fecha": r.fecha.isoformat() if r.fecha else None, "enlace": f"/perdidos/{r.id}",
                })
            return {"total": len(resultados), "resultados": resultados[:15]}
        if tipo == "lugar":
            q = db.query(Lugar)
            if categoria:
                q = q.filter(Lugar.tipo == categoria)
            for l in q.all():
                bolsa = normalizar(" ".join(filter(None, [l.nombre, l.direccion, l.distrito, l.descripcion])))
                if texto and not all(t in bolsa for t in texto.split()):
                    continue
                if distrito and distrito not in normalizar(l.distrito or "") + " " + normalizar(l.direccion or ""):
                    continue
                resultados.append({
                    "nombre": l.nombre, "tipo": cat.TIPOS_LUGAR.get(l.tipo, ("Otro",))[0],
                    "direccion": l.direccion, "distrito": l.distrito, "descripcion": (l.descripcion or "")[:200],
                    "enlace": "/mapa",
                })
        else:
            q = db.query(Perfil).filter(Perfil.tipo == ("entidad" if tipo == "entidad" else "mascota"))
            if categoria:
                q = q.filter(Perfil.categoria == categoria) if tipo == "entidad" else q.filter(Perfil.especie == categoria)
            for p in q.all():
                bolsa = normalizar(" ".join(filter(None, [
                    p.nombre, p.raza, p.direccion, p.distrito, p.ciudad, p.descripcion, p.tags,
                    cat.CATEGORIAS_ENTIDAD.get(p.categoria or "", ("",))[0],
                ])))
                if texto and not all(t in bolsa for t in texto.split()):
                    continue
                if distrito and distrito not in normalizar(f"{p.distrito} {p.ciudad} {p.direccion or ''}"):
                    continue
                if tipo == "entidad":
                    resultados.append({
                        "nombre": p.nombre,
                        "categoria": cat.CATEGORIAS_ENTIDAD.get(p.categoria or "otro", ("Otro",))[0],
                        "direccion": p.direccion, "distrito": p.distrito, "horario": p.horario,
                        "telefono": p.telefono, "verificada": bool(p.verificada),
                        "descripcion": (p.descripcion or "")[:200], "enlace": f"/p/{p.handle}",
                    })
                    if p.categoria == "restaurante":
                        resultados[-1]["ofrece_a_mascotas"] = [
                            cat.AMENIDADES_PET_FRIENDLY[a][0] for a in p.lista_tags if a in cat.AMENIDADES_PET_FRIENDLY]
                else:
                    resultados.append({
                        "nombre": p.nombre, "especie": cat.ESPECIES.get(p.especie or "otro", ("Otro",))[0],
                        "raza": p.raza, "sexo": p.sexo, "edad": edad_texto(p), "distrito": p.distrito,
                        "tags": p.tags, "enlace": f"/p/{p.handle}",
                    })
    return {"total": len(resultados), "resultados": resultados[:15]}


def _agendar(args: dict, usuario_id: int) -> dict:
    with SessionLocal() as db:
        mascota = db.get(Perfil, args.get("mascota_id"))
        if not mascota or mascota.usuario_id != usuario_id or mascota.tipo != "mascota":
            return {"ok": False, "error": "La mascota no pertenece al usuario."}
        fecha = a_fecha(args.get("fecha"))
        if not fecha:
            return {"ok": False, "error": "Fecha inválida, usa YYYY-MM-DD."}
        tipo = args.get("tipo") if args.get("tipo") in cat.TIPOS_EVENTO else "otro"
        hora = (args.get("hora") or "").strip()[:5] or None
        alerta = args.get("alerta_dias")
        if alerta not in (0, 1, 3, 7):
            alerta = None
        ev = Evento(
            perfil_id=mascota.id, tipo=tipo, titulo=(args.get("titulo") or "Evento")[:200], fecha=fecha,
            hora=hora, lugar=(args.get("lugar") or "")[:200] or None, notas=(args.get("notas") or "")[:1000] or None,
            alerta_dias=alerta,
        )
        db.add(ev)
        db.commit()
        return {
            "ok": True, "evento_id": ev.id, "mascota": mascota.nombre, "fecha": fecha_larga(fecha),
            "enlace": f"/calendario?mes={fecha:%Y-%m}",
        }


# ------------------------------------------------------------------ contexto

def _contexto_usuario(usuario_id: int, perfil_activo_id) -> str:
    hoy = date.today()
    lineas = []
    with SessionLocal() as db:
        usuario = db.get(Usuario, usuario_id)
        if not usuario:
            return ""
        lineas.append(f"Usuario: {usuario.nombre.split()[0] if usuario.nombre else ''}")
        mascotas = [p for p in usuario.perfiles if p.tipo == "mascota"]
        entidades = [p for p in usuario.perfiles if p.tipo == "entidad"]
        activo = db.get(Perfil, perfil_activo_id) if perfil_activo_id else None
        if activo and activo.usuario_id == usuario_id:
            lineas.append(f"Perfil activo: {activo.nombre} ({'mascota' if activo.es_mascota else 'entidad'}, id {activo.id})")
        if mascotas:
            lineas.append("Mascotas del usuario:")
            for m in mascotas:
                cumple, dias = proximo_cumpleanos(m.fecha_nacimiento, hoy)
                datos = [
                    f"id {m.id}", cat.ESPECIES.get(m.especie or "otro", ("Otro",))[0], m.raza or "raza no indicada",
                    cat.SEXOS.get(m.sexo or "", ("sexo no indicado",))[0], edad_texto(m) or "edad no indicada",
                    f"distrito {m.distrito}" if m.distrito else "",
                    f"cumpleaños {m.fecha_nacimiento:%d/%m} (en {dias} días)" if cumple else "",
                    f"tags: {m.tags}" if m.tags else "",
                ]
                lineas.append(f"- {m.nombre}: " + ", ".join(d for d in datos if d))
            ids = [m.id for m in mascotas]
            eventos = (db.query(Evento).filter(Evento.perfil_id.in_(ids), Evento.fecha >= hoy,
                                               Evento.fecha <= hoy + timedelta(days=90))
                       .order_by(Evento.fecha).limit(20).all())
            if eventos:
                nombres = {m.id: m.nombre for m in mascotas}
                lineas.append("Próximos eventos del calendario:")
                for e in eventos:
                    lineas.append(f"- {e.fecha.isoformat()} {e.hora or ''} · {nombres.get(e.perfil_id)} · "
                                  f"{cat.TIPOS_EVENTO.get(e.tipo, ('Otro',))[0]}: {e.titulo}")
            else:
                lineas.append("No tiene eventos próximos en el calendario.")
        else:
            lineas.append("El usuario aún no tiene perfiles de mascota.")
        if entidades:
            lineas.append("Entidades que administra: " + ", ".join(
                f"{e.nombre} ({cat.CATEGORIAS_ENTIDAD.get(e.categoria or 'otro', ('Otro',))[0]})" for e in entidades))
    return "\n".join(lineas)


def prompt_sistema(usuario_id: int, perfil_activo_id) -> str:
    hoy = date.today()
    return (
        "Eres Pawi, el asistente de Pawbook, la red social para mascotas. Ayudas a los dueños con el cuidado de "
        "sus mascotas (alimentación, paseos, vacunas, higiene, comportamiento, adopción responsable), a usar "
        "Pawbook y a encontrar servicios publicados en la plataforma.\n\n"
        "REGLAS:\n"
        "1. Salud: da orientación general; NO diagnostiques ni indiques dosis de medicamentos. Ante síntomas, "
        "recomienda ir al veterinario. Ante señales de emergencia (dificultad para respirar, convulsiones, "
        "posible intoxicación, sangrado abundante, golpe fuerte, golpe de calor, no puede orinar, abdomen "
        "hinchado) indica ir de inmediato a una veterinaria de urgencias; puedes buscar veterinarias con "
        "buscar_en_pawbook.\n"
        "2. Para recomendar servicios o lugares usa buscar_en_pawbook y comparte los enlaces que devuelve en "
        "formato Markdown, p. ej. [Nombre](/p/handle). No inventes negocios, direcciones ni teléfonos.\n"
        "3. Para agendar usa agendar_evento con el mascota_id correcto. Si falta la mascota o la fecha, "
        "pregunta. Interpreta fechas relativas (\"el viernes\", \"en 2 semanas\") a partir de la fecha de hoy. "
        "Al terminar confirma qué agendaste.\n"
        "4. No compartas datos personales de dueños; solo información pública de perfiles.\n"
        "5. Responde en español, cálido y breve, con Markdown (listas y negritas). Máximo 1 o 2 emojis.\n"
        "6. Si alguien perdió a su mascota: muestra empatía, invítalo a publicar un aviso en "
        "[/perdidos/nuevo](/perdidos/nuevo) (Pawbook avisa a los vecinos de la zona y a sus amigos), revisa con "
        "buscar_en_pawbook (tipo \"perdido\") si hay mascotas encontradas parecidas, y sugiere avisar a "
        "veterinarias y refugios cercanos. Si encontró una, sugiere llevarla a una veterinaria para leer su "
        "microchip y publicar el aviso de \"Encontré una mascota\".\n\n"
        "GUÍA DE PAWBOOK (rutas):\n"
        "- Inicio (/): publicaciones de amigos y entidades seguidas.\n"
        "- Buscar (/buscar): mascotas por raza, especie, edad y cercanía; entidades por categoría.\n"
        "- Amigos (/amigos): mascotas y entidades que sigues, y tus seguidores.\n"
        "- Pareja (/pareja): activa la búsqueda de pareja para ver mascotas compatibles (misma especie, sexo "
        "opuesto, mayores de 1 año) y enviar \"Me interesa\".\n"
        "- Calendario (/calendario): citas veterinarias, vacunas, desparasitación, cumpleaños, con alertas.\n"
        "- Mapa (/mapa): veterinarias, tiendas, parques, restaurantes pet friendly, centros de adopción, avisos de "
        "mascotas perdidas y amigos cerca.\n"
        "- Restaurantes pet friendly (/pet-friendly): restaurantes y cafés que aceptan mascotas, con filtros por "
        "distrito y por lo que ofrecen (terraza, plato de agua, menú para mascotas, perros grandes...).\n"
        "- Perdidos y encontrados (/perdidos): avisos de mascotas perdidas y encontradas; se pueden compartir "
        "sin tener cuenta. Al publicar uno, Pawbook avisa a los vecinos y sugiere posibles coincidencias.\n"
        "- Anuncios (/anuncios): solo para perfiles de entidad. Gratuitos para centros de adopción, caridades y "
        "campañas gratuitas de vacunación o esterilización; pagados para veterinarias, marcas y tiendas. Todos "
        "pasan por revisión antes de publicarse.\n"
        "- Mis perfiles (/mis-perfiles): una cuenta puede tener varias mascotas y entidades.\n\n"
        f"Hoy es {DIAS[hoy.weekday()]} {hoy.isoformat()} ({hoy.day} de {MESES[hoy.month - 1]}).\n\n"
        f"--- DATOS DEL USUARIO ---\n{_contexto_usuario(usuario_id, perfil_activo_id)}"
    )


# ------------------------------------------------------------------ streaming

def generar_respuesta(mensaje: str, historial: list, usuario_id: int, perfil_activo_id):
    def evento(**datos):
        return json.dumps(datos, ensure_ascii=False) + "\n"

    cli = cliente()
    if cli is None:
        yield evento(tipo="texto", delta=(
            "Pawi aún no está configurado. Agrega tu `OPENAI_API_KEY` en el archivo `.env` "
            "de la carpeta de Pawbook y reinicia el servidor."))
        yield evento(tipo="fin")
        return

    entrada = [{"role": "system", "content": prompt_sistema(usuario_id, perfil_activo_id)}]
    for m in (historial or [])[-12:]:
        rol, contenido = m.get("role"), m.get("content")
        if rol in ("user", "assistant") and isinstance(contenido, str) and contenido.strip():
            entrada.append({"role": rol, "content": contenido[:4000]})
    entrada.append({"role": "user", "content": mensaje[:4000]})

    try:
        hubo_texto = False
        yield evento(tipo="estado", texto="Pensando…")
        for vuelta in range(MAX_VUELTAS + 1):
            kwargs = {"model": modelo(), "input": entrada}
            if vuelta < MAX_VUELTAS:
                kwargs["tools"] = HERRAMIENTAS
            with cli.responses.stream(**kwargs) as stream:
                for ev in stream:
                    if ev.type == "response.output_text.delta":
                        hubo_texto = True
                        yield evento(tipo="texto", delta=ev.delta)
                    elif ev.type == "response.output_item.added" and getattr(ev.item, "type", "") == "function_call":
                        nombre = getattr(ev.item, "name", "")
                        yield evento(tipo="estado", texto="Agendando en tu calendario…" if nombre == "agendar_evento"
                                     else "Buscando en Pawbook…")
                respuesta = stream.get_final_response()

            llamadas = [o for o in respuesta.output if o.type == "function_call"]
            if not llamadas:
                break
            entrada = entrada + list(respuesta.output)
            for llamada in llamadas:
                try:
                    args = json.loads(llamada.arguments or "{}")
                except Exception:
                    args = {}
                if llamada.name == "agendar_evento":
                    resultado = _agendar(args, usuario_id)
                    if resultado.get("ok"):
                        yield evento(tipo="accion", texto=f"Agendado para {resultado['mascota']}: {resultado['fecha']}",
                                     enlace=resultado["enlace"])
                elif llamada.name == "buscar_en_pawbook":
                    resultado = _buscar(args)
                else:
                    resultado = {"error": "Herramienta desconocida"}
                entrada.append({
                    "type": "function_call_output",
                    "call_id": llamada.call_id,
                    "output": json.dumps(resultado, ensure_ascii=False, default=str),
                })
            yield evento(tipo="estado", texto="Preparando la respuesta…")

        if not hubo_texto:
            yield evento(tipo="texto", delta="No pude generar una respuesta. ¿Puedes reformular tu pregunta?")
        yield evento(tipo="fin")
    except Exception as e:
        print(f"[Pawi] Error: {e}")
        yield evento(tipo="error", texto="Ocurrió un error al generar la respuesta. Intenta de nuevo en un momento.")
