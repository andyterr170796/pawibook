"""Datos iniciales: cuenta administradora y datos de demostración (solo si la base está vacía).

Los negocios, teléfonos y correos de la demo son ficticios. Los parques son lugares públicos reales de Lima
con coordenadas aproximadas.
"""
import os
import secrets
from datetime import date, datetime, timedelta

from models import (
    Anuncio, Comentario, Evento, Lugar, MeGusta, Notificacion, Perfil, Publicacion, ReportePerdido, SessionLocal,
    Seguimiento, Usuario,
)
from utilidades import BASE_DIR, hash_password

DEMO_EMAIL = "demo@pawbook.pe"
# Las cuentas demo no tienen una contraseña conocida (el código es público): la cuenta demo se usa con el
# botón "Explorar con la cuenta demo" y las cuentas "Vecinos" y "Negocios" solo son dueñas de los datos.

# Restaurantes pet friendly ficticios (cuenta "Negocios Pawbook (demo)")
RESTAURANTES_DEMO = [
    ("cafe-huellitas", dict(
        nombre="Café Huellitas", verificada=True, direccion="Jr. Los Cedros 315, Barranco", distrito="Barranco",
        lat=-12.1478, lng=-77.0212, horario="Mar–Dom 8:00–20:00", telefono="+51 999 000 108",
        email_contacto="hola@cafehuellitas.demo", tags="terraza,agua,menu,grandes",
        descripcion="Café de especialidad con terraza pet friendly. Tenemos puppuccino y galletas caseras para "
                    "perros. Perfil de demostración.")),
    ("terraza-perruna", dict(
        nombre="La Terraza Perruna", direccion="Calle Los Tulipanes 180, Miraflores", distrito="Miraflores",
        lat=-12.1232, lng=-77.0318, horario="Lun–Dom 12:00–23:00", telefono="+51 999 000 109",
        tags="terraza,agua,grandes",
        descripcion="Cocina criolla y parrillas con una terraza amplia y con sombra. Bebederos para tus mascotas. "
                    "Perfil de demostración.")),
    ("pizzeria-cola-feliz", dict(
        nombre="Pizzería Cola Feliz", direccion="Av. Las Camelias 950, San Isidro", distrito="San Isidro",
        lat=-12.1008, lng=-77.0337, horario="Mar–Dom 18:00–23:30", telefono="+51 999 000 110",
        tags="interior,agua,menu,gatos",
        descripcion="Pizzas al horno de leña. Las mascotas son bienvenidas también dentro del local y tenemos "
                    "snacks para perros. Perfil de demostración.")),
]
POST_CAFE = ("☕🐶 Este domingo: brunch pet friendly en nuestra terraza. Puppuccino gratis para los peludos que "
             "vengan con su familia.")


def _avisos_demo(P: dict, usuario_id: int, hoy: date, ahora: datetime) -> list:
    """Avisos de perdidos/encontrados de la cuenta "Vecinos" (P: perfiles toby, canela y lola)."""
    return [
        ReportePerdido(
            usuario_id=usuario_id, autor_id=P["toby"].id, mascota_id=P["toby"].id, tipo="perdido", nombre="Toby",
            especie="perro", raza="Beagle", sexo="macho", color="Tricolor (blanco, marrón y negro), collar azul con placa",
            fecha=hoy - timedelta(days=2), hora="18:30", distrito="Barranco", referencia="Cerca a la Bajada de Baños",
            lat=-12.151, lng=-77.024, telefono="+51 999 000 201", recompensa="S/ 200", creado=ahora - timedelta(days=2),
            descripcion="Se asustó con unos cohetes y salió corriendo. Es amigable pero asustadizo: si lo ves, llámalo "
                        "por su nombre y ofrécele comida. Aviso de demostración."),
        ReportePerdido(
            usuario_id=usuario_id, autor_id=P["canela"].id, tipo="encontrado", nombre="", especie="gato",
            raza="Mestizo", sexo="hembra", color="Atigrada gris, ojos verdes, sin collar", fecha=hoy - timedelta(days=1),
            hora="08:15", distrito="Miraflores", referencia="Calle Berlín, cerca al Parque Kennedy", lat=-12.121,
            lng=-77.028, telefono="+51 999 000 202", creado=ahora - timedelta(days=1),
            descripcion="Estaba escondida debajo de un auto. Está tranquila y sana; la tenemos en casa temporalmente. "
                        "Aviso de demostración."),
        ReportePerdido(
            usuario_id=usuario_id, autor_id=P["lola"].id, mascota_id=P["lola"].id, tipo="perdido", estado="resuelto",
            nombre="Lola", especie="perro", raza="Bulldog Francés", sexo="hembra", color="Atigrada, orejas paradas",
            fecha=hoy - timedelta(days=16), distrito="Miraflores", referencia="Malecón Cisneros", lat=-12.127,
            lng=-77.037, telefono="+51 999 000 203", creado=ahora - timedelta(days=16),
            resuelto_en=ahora - timedelta(days=14),
            descripcion="¡Gracias a todos los vecinos que compartieron el aviso! Aviso de demostración."),
    ]


def _notificar_avisos_demo(db, rocky: Perfil, avisos: list, ahora: datetime):
    toby, gata = avisos[0], avisos[1]
    db.add(Notificacion(perfil_id=rocky.id, actor_id=toby.mascota_id, tipo="perdido",
                        texto="🚨 Tu amigo Toby se perdió en Barranco. ¿Lo has visto?", enlace=f"/perdidos/{toby.id}",
                        clave=f"aviso:{toby.id}:{rocky.usuario_id}", creado=ahora - timedelta(days=2)))
    db.add(Notificacion(perfil_id=rocky.id, tipo="perdido",
                        texto="🔎 Encontraron una gata en Miraflores. ¿Sabes quién es su familia?",
                        enlace=f"/perdidos/{gata.id}", clave=f"aviso:{gata.id}:{rocky.usuario_id}",
                        creado=ahora - timedelta(days=1)))


def asegurar_admin():
    with SessionLocal() as db:
        if db.query(Usuario.id).filter(Usuario.es_admin.is_(True)).first():
            return
        email = os.getenv("PAWBOOK_ADMIN_EMAIL", "admin@pawbook.local").strip().lower()
        password = os.getenv("PAWBOOK_ADMIN_PASSWORD", "").strip()
        generada = not password
        if generada:
            password = secrets.token_urlsafe(9)
        existente = db.query(Usuario).filter(Usuario.email == email).first()
        if existente:
            existente.es_admin = True
        else:
            db.add(Usuario(nombre="Administrador Pawbook", email=email, password_hash=hash_password(password),
                           es_admin=True))
        db.commit()
        if not existente:
            print(f"\n  Cuenta administradora creada: {email}")
            if generada:
                ruta = os.path.join(BASE_DIR, "credenciales_admin.txt")
                with open(ruta, "w", encoding="utf-8") as f:
                    f.write(f"Pawbook - cuenta administradora\nCorreo: {email}\nContraseña: {password}\n")
                print(f"  Contraseña generada y guardada en: credenciales_admin.txt\n")


def _fecha_hace(anios: int, dias_para_cumple: int) -> date:
    """Fecha de nacimiento para que la mascota tenga `anios` y cumpla dentro de `dias_para_cumple` días."""
    hoy = date.today()
    cumple = hoy + timedelta(days=dias_para_cumple)
    try:
        return cumple.replace(year=cumple.year - anios)
    except ValueError:
        return date(cumple.year - anios, 3, 1)


def cargar_demo_si_vacio():
    with SessionLocal() as db:
        if db.query(Perfil.id).first():
            return
        hoy = date.today()
        ahora = datetime.now()

        def usuario(nombre, email):
            u = Usuario(nombre=nombre, email=email, password_hash=hash_password(secrets.token_urlsafe(24)))
            db.add(u)
            db.flush()
            return u

        demo = usuario("Cuenta Demo", DEMO_EMAIL)
        vecinos = usuario("Vecinos Pawbook (demo)", "vecinos@pawbook.demo")
        negocios = usuario("Negocios Pawbook (demo)", "negocios@pawbook.demo")

        perfiles = {}

        def mascota(u, clave, **kw):
            p = Perfil(usuario_id=u.id, tipo="mascota", handle=clave, pais="Perú", ciudad="Lima", **kw)
            db.add(p)
            perfiles[clave] = p
            return p

        def entidad(clave, **kw):
            p = Perfil(usuario_id=negocios.id, tipo="entidad", handle=clave, pais="Perú", ciudad="Lima",
                       verificada=kw.pop("verificada", False), **kw)
            db.add(p)
            perfiles[clave] = p
            return p

        # ---------------- mascotas
        mascota(demo, "rocky", nombre="Rocky", especie="perro", raza="Golden Retriever", sexo="macho",
                fecha_nacimiento=_fecha_hace(4, 45), distrito="Miraflores", lat=-12.121, lng=-77.031,
                tags="juguetón,pelota,nadador,playa,parque,glotón", busca_pareja=True,
                descripcion="Soy Rocky, un golden con energía infinita. Me encanta correr por el malecón, "
                            "nadar en la playa y robar medias. Busco amigos para jugar a la pelota los fines de semana.")
        mascota(demo, "mishi", nombre="Mishi", especie="gato", raza="Siamés", sexo="hembra",
                fecha_nacimiento=_fecha_hace(3, 12), distrito="Miraflores", lat=-12.122, lng=-77.029,
                tags="dormilón,mimoso,tranquilo",
                descripcion="Reina de la casa. Duermo 16 horas al día y el resto lo dedico a mirar pájaros por la ventana.")
        mascota(vecinos, "luna", nombre="Luna", especie="perro", raza="Golden Retriever", sexo="hembra",
                fecha_nacimiento=_fecha_hace(3, 2), distrito="San Isidro", lat=-12.098, lng=-77.036,
                tags="cariñoso,paseo,parque,sociable", busca_pareja=True,
                descripcion="Golden dulce y tranquila. Mis paseos favoritos son en El Olivar.")
        mascota(vecinos, "toby", nombre="Toby", especie="perro", raza="Beagle", sexo="macho",
                fecha_nacimiento=_fecha_hace(5, 80), distrito="Barranco", lat=-12.149, lng=-77.021,
                tags="glotón,paseo,corredor", descripcion="Mi nariz me lleva a todas partes. Experto en encontrar galletas.")
        mascota(vecinos, "canela", nombre="Canela", especie="perro", raza="Mestizo", sexo="hembra", edad_aprox=2,
                distrito="Miraflores", lat=-12.118, lng=-77.034, tags="adoptado,juguetón,sociable",
                descripcion="Me adoptaron en una jornada de adopción y ahora tengo la mejor familia. ¡Adopta, no compres!")
        mascota(vecinos, "lola", nombre="Lola", especie="perro", raza="Bulldog Francés", sexo="hembra",
                fecha_nacimiento=_fecha_hace(2, 150), distrito="Miraflores", lat=-12.125, lng=-77.026,
                tags="dormilón,fotogénico,mimoso", descripcion="Pequeña, ruidosa y muy fotogénica.")
        mascota(vecinos, "max", nombre="Max", especie="perro", raza="Pastor Alemán", sexo="macho",
                fecha_nacimiento=_fecha_hace(6, 200), distrito="Lince", lat=-12.086, lng=-77.035,
                tags="guardián,entrenado,paseo", descripcion="Obediente y protector. Me encanta aprender trucos nuevos.")
        mascota(vecinos, "simba", nombre="Simba", especie="gato", raza="Maine Coon", sexo="macho",
                fecha_nacimiento=_fecha_hace(4, 30), distrito="La Molina", lat=-12.084, lng=-76.946,
                tags="tranquilo,cariñoso", busca_pareja=True, descripcion="Gigante gentil de 8 kilos.")
        mascota(vecinos, "nube", nombre="Nube", especie="conejo", raza="Cabeza de León", sexo="hembra",
                fecha_nacimiento=_fecha_hace(1, 60), distrito="San Borja", lat=-12.107, lng=-77.001,
                tags="tímido,glotón", descripcion="Como zanahorias y hago saltitos cuando estoy feliz.")
        mascota(vecinos, "kiwi", nombre="Kiwi", especie="ave", raza="Periquito australiano", sexo="macho",
                fecha_nacimiento=_fecha_hace(2, 3), distrito="Jesús María", lat=-12.073, lng=-77.045,
                tags="sociable", descripcion="Silbo la canción del noticiero y saludo a todos los que llegan.")
        mascota(vecinos, "chispa", nombre="Chispa", especie="perro", raza="Perro sin pelo del Perú", sexo="hembra",
                fecha_nacimiento=_fecha_hace(3, 95), distrito="Pueblo Libre", lat=-12.075, lng=-77.064,
                tags="energético,corredor,paseo", descripcion="Orgullosamente peruana. Mi piel necesita bloqueador en verano.")

        # ---------------- entidades (ficticias)
        entidad("patitas-sanas", nombre="Veterinaria Patitas Sanas", categoria="veterinaria", verificada=True,
                direccion="Calle Los Geranios 245, Miraflores", distrito="Miraflores", lat=-12.1195, lng=-77.0305,
                horario="Lun–Sáb 8:00–20:00 · Dom 9:00–13:00", telefono="+51 999 000 101",
                email_contacto="citas@patitassanas.demo",
                descripcion="Consultas, vacunación, desparasitación, laboratorio y cirugía. Perfil de demostración.")
        entidad("clinica-bigotes", nombre="Clínica Vet Bigotes 24 h", categoria="veterinaria",
                direccion="Av. Las Palmeras 1180, San Isidro", distrito="San Isidro", lat=-12.0975, lng=-77.0320,
                horario="Atención 24 horas", telefono="+51 999 000 102", email_contacto="urgencias@bigotes.demo",
                descripcion="Emergencias las 24 horas, hospitalización y especialistas. Perfil de demostración.")
        entidad("croqueta-feliz", nombre="Tienda Croqueta Feliz", categoria="tienda", verificada=True,
                direccion="Jr. Las Begonias 530, Surquillo", distrito="Surquillo", lat=-12.1130, lng=-77.0190,
                horario="Lun–Dom 9:00–21:00", telefono="+51 999 000 103", email_contacto="ventas@croquetafeliz.demo",
                web="https://example.com", descripcion="Alimento, accesorios y juguetes con delivery. Perfil de demostración.")
        entidad("buen-chico", nombre="Escuela Canina Buen Chico", categoria="entrenamiento",
                direccion="Parque Los Robles, Santiago de Surco", distrito="Santiago de Surco", lat=-12.1350, lng=-76.9950,
                horario="Sáb y Dom 8:00–12:00", telefono="+51 999 000 104",
                descripcion="Obediencia básica, socialización de cachorros y clases grupales. Perfil de demostración.")
        entidad("cola-alegre", nombre="Paseos Cola Alegre", categoria="paseador",
                direccion="Miraflores y San Isidro", distrito="Miraflores", lat=-12.1150, lng=-77.0350,
                horario="Lun–Vie 7:00–19:00", telefono="+51 999 000 105",
                descripcion="Paseos grupales e individuales con reporte y fotos. Perfil de demostración.")
        entidad("segunda-oportunidad", nombre="Refugio Segunda Oportunidad", categoria="centro_adopcion", verificada=True,
                direccion="Av. Los Pinos 890, Chorrillos", distrito="Chorrillos", lat=-12.1700, lng=-77.0150,
                horario="Visitas Sáb y Dom 10:00–16:00", telefono="+51 999 000 106",
                email_contacto="adopciones@segundaoportunidad.demo",
                descripcion="Rescatamos, rehabilitamos y damos en adopción responsable a perros y gatos. Perfil de demostración.")
        entidad("patas-unidas", nombre="Fundación Patas Unidas", categoria="caridad",
                direccion="Jesús María", distrito="Jesús María", lat=-12.0760, lng=-77.0480,
                telefono="+51 999 000 107", email_contacto="hola@patasunidas.demo",
                descripcion="ONG que organiza campañas de esterilización a bajo costo y gratuitas. Perfil de demostración.")
        entidad("nutripet", nombre="NutriPet (marca demo)", categoria="marca",
                web="https://example.com", mostrar_en_mapa=False,
                descripcion="Alimento balanceado para perros y gatos. Marca ficticia de demostración.")
        for clave, datos in RESTAURANTES_DEMO:
            entidad(clave, categoria="restaurante", **dict(datos))
        db.flush()

        # ---------------- parques (lugares públicos reales, coordenadas aproximadas)
        parques = [
            ("Parque Kennedy", "Miraflores", -12.1211, -77.0297, "Parque céntrico; mascotas con correa."),
            ("Parque El Olivar", "San Isidro", -12.0995, -77.0359, "Bosque de olivos, ideal para paseos tranquilos."),
            ("Campo de Marte", "Jesús María", -12.0700, -77.0430, "Amplias áreas verdes y zona para mascotas."),
            ("Parque Reducto N.° 2", "Miraflores", -12.1290, -77.0230, "Áreas verdes y ciclovía cercana."),
            ("Parque del Amor", "Miraflores", -12.1270, -77.0380, "Malecón con vista al mar."),
            ("Parque de la Amistad", "Santiago de Surco", -12.1340, -76.9930, "Gran parque familiar."),
            ("Parque Mariscal Castilla", "Lince", -12.0870, -77.0350, "Parque tradicional con laguna."),
        ]
        for nombre, distrito, lat, lng, desc in parques:
            db.add(Lugar(nombre=nombre, tipo="parque", distrito=distrito, lat=lat, lng=lng, descripcion=desc))

        P = perfiles

        # ---------------- seguimientos
        sigue = {
            "rocky": ["luna", "toby", "canela", "lola", "chispa", "patitas-sanas", "croqueta-feliz",
                      "segunda-oportunidad", "cola-alegre", "cafe-huellitas"],
            "mishi": ["simba", "kiwi", "patitas-sanas"],
            "luna": ["rocky", "canela", "patitas-sanas"], "toby": ["rocky", "lola", "buen-chico"],
            "canela": ["rocky", "luna", "segunda-oportunidad"], "lola": ["rocky", "canela"],
            "max": ["rocky", "buen-chico"], "simba": ["mishi"], "chispa": ["rocky", "toby"],
            "kiwi": ["mishi"],
        }
        for a, lista in sigue.items():
            for b in lista:
                db.add(Seguimiento(seguidor_id=P[a].id, seguido_id=P[b].id))

        # ---------------- publicaciones
        posts = [
            ("luna", 1, "Mañana de sol en El Olivar ☀️ ¿Quién se apunta al paseo del sábado?"),
            ("patitas-sanas", 3, "🩺 Recordatorio: la vacuna antirrábica es anual. Revisa la cartilla de tu mascota y "
                                 "agenda tu cita. Esta semana atendemos sin cita previa de 9 a 12."),
            ("rocky", 5, "Hoy aprendí a abrir la puerta del refrigerador. Mi familia no está tan orgullosa como yo 🐶 #glotón"),
            ("canela", 9, "Hace un año estaba en un refugio. Hoy tengo sofá, familia y una pelota favorita. "
                          "#adopta en @segunda-oportunidad 💛"),
            ("segunda-oportunidad", 14, "🏠 Este fin de semana tenemos jornada de adopción. 12 perritos y 8 gatitos "
                                        "buscan hogar. Todos vacunados y esterilizados."),
            ("toby", 20, "Encontré una galleta debajo del sillón. No preguntaré de cuándo es."),
            ("mishi", 26, "Postura oficial de la casa: la caja vale más que el juguete que venía dentro."),
            ("croqueta-feliz", 30, "Nuevos juguetes interactivos para gatos curiosos 🐱 Delivery en Miraflores, "
                                   "San Isidro y Surquillo."),
            ("lola", 36, "Nadie ronca más fuerte que yo. Es un talento."),
            ("chispa", 44, "Recuerden: los perros sin pelo también necesitamos bloqueador ☀️ #perrosinpelo"),
            ("buen-chico", 50, "Tip de entrenamiento: sesiones cortas (5 minutos) y siempre terminar con un éxito. "
                               "Los premios pequeños funcionan mejor."),
            ("rocky", 60, "Primer día de playa del verano 🌊 #playa #nadador"),
            ("simba", 75, "8 kilos de puro amor y pelo en tu ropa negra."),
            ("kiwi", 90, "Hoy aprendí a silbar el timbre. Ya nadie sabe cuándo es de verdad."),
            ("cafe-huellitas", 7, POST_CAFE),
        ]
        creados = []
        for clave, horas, texto in posts:
            post = Publicacion(perfil_id=P[clave].id, texto=texto, creado=ahora - timedelta(hours=horas))
            db.add(post)
            creados.append(post)
        db.flush()
        likes = {0: ["rocky", "canela", "toby"], 2: ["luna", "lola", "chispa", "toby", "mishi"], 3: ["rocky", "luna"],
                 4: ["rocky", "canela", "luna", "max"], 6: ["simba", "kiwi"], 11: ["luna", "toby", "lola"]}
        for idx, quienes in likes.items():
            for q in quienes:
                db.add(MeGusta(publicacion_id=creados[idx].id, perfil_id=P[q].id))
        comentarios = [
            (0, "rocky", "¡Yo voy! Llevo la pelota 🎾"), (2, "luna", "Jajaja Rocky eres un genio"),
            (2, "toby", "Enséñame, por favor"), (3, "rocky", "¡Qué linda historia, Canela!"),
            (4, "canela", "¡Ahí me adoptaron a mí! Vayan 💛"), (11, "luna", "¡Qué envidia!"),
        ]
        for idx, clave, texto in comentarios:
            db.add(Comentario(publicacion_id=creados[idx].id, perfil_id=P[clave].id, texto=texto,
                              creado=creados[idx].creado + timedelta(minutes=40)))

        # ---------------- calendario
        eventos = [
            ("rocky", "vacuna", "Vacuna antirrábica", 5, "10:30", "Veterinaria Patitas Sanas", 3),
            ("rocky", "veterinaria", "Control anual", 12, "16:00", "Veterinaria Patitas Sanas", 1),
            ("rocky", "desparasitacion", "Desparasitación interna", 33, None, None, 1),
            ("mishi", "grooming", "Baño y corte de uñas", 2, "11:00", None, 0),
            ("mishi", "vacuna", "Vacuna triple felina", 20, "09:00", "Veterinaria Patitas Sanas", 3),
        ]
        for clave, tipo, titulo, dias, hora, lugar, alerta in eventos:
            db.add(Evento(perfil_id=P[clave].id, tipo=tipo, titulo=titulo, fecha=hoy + timedelta(days=dias),
                          hora=hora, lugar=lugar, alerta_dias=alerta))

        # ---------------- anuncios
        anuncios = [
            ("croqueta-feliz", "pagado", "promocion", "20 % en alimento premium",
             "Solo este mes en todas las marcas premium. Delivery gratis desde S/ 120.", "mes"),
            ("clinica-bigotes", "pagado", "servicio", "Chequeo geriátrico para mascotas senior",
             "Evaluación completa para perros y gatos mayores de 7 años.", "mes"),
            ("nutripet", "pagado", "producto", "NutriPet Cachorros",
             "Nutrición balanceada para las primeras etapas. Marca ficticia de demostración.", "semana"),
            ("segunda-oportunidad", "gratuito", "adopcion", "Jornada de adopción este sábado",
             "Parque Kennedy, 10:00 a 16:00. Lleva tu DNI y muchas ganas de amar.", None),
            ("patas-unidas", "gratuito", "campana_esterilizacion", "Esterilización gratuita",
             "Campaña para perros y gatos. Cupos limitados, inscríbete con anticipación.", None),
            ("patitas-sanas", "gratuito", "campana_vacunacion", "Vacunación antirrábica gratuita",
             "Domingo de 9:00 a 13:00 en nuestra sede de Miraflores.", None),
        ]
        for clave, tipo, categoria, titulo, texto, plan in anuncios:
            db.add(Anuncio(perfil_id=P[clave].id, tipo=tipo, categoria=categoria, titulo=titulo, texto=texto,
                           plan=plan, estado="activo", fecha_inicio=hoy - timedelta(days=2),
                           fecha_fin=hoy + timedelta(days=28), impresiones=0, clics=0))
        db.add(Anuncio(perfil_id=P["cola-alegre"].id, tipo="pagado", categoria="servicio",
                       titulo="Primer paseo gratis", texto="Prueba nuestros paseos grupales.", plan="semana",
                       estado="pendiente"))

        # ---------------- notificaciones de bienvenida para la cuenta demo
        db.add(Notificacion(perfil_id=P["rocky"].id, actor_id=P["luna"].id, tipo="seguidor",
                            texto="Luna empezó a seguirte.", enlace="/p/luna", creado=ahora - timedelta(hours=2)))
        db.add(Notificacion(perfil_id=P["rocky"].id, actor_id=P["luna"].id, tipo="pareja",
                            texto="💞 Luna (Golden Retriever) también busca pareja y es de tu misma raza.",
                            enlace="/pareja", creado=ahora - timedelta(hours=1)))

        # ---------------- perdidos y encontrados
        avisos = _avisos_demo(P, vecinos.id, hoy, ahora)
        db.add_all(avisos)
        db.flush()
        _notificar_avisos_demo(db, P["rocky"], avisos, ahora)

        demo.perfil_activo_id = P["rocky"].id
        db.commit()
        print("  Datos de demostración cargados. Entra con el botón «Explorar con la cuenta demo».")


def complementar_demo():
    """Agrega a una base demo ya creada los datos de las secciones nuevas (restaurantes pet friendly y
    perdidos/encontrados). Solo actúa si existen las cuentas demo y todavía no hay ningún restaurante ni aviso."""
    with SessionLocal() as db:
        negocios = db.query(Usuario).filter(Usuario.email == "negocios@pawbook.demo").first()
        vecinos = db.query(Usuario).filter(Usuario.email == "vecinos@pawbook.demo").first()
        if not negocios or not vecinos:
            return
        if (db.query(Perfil.id).filter(Perfil.categoria == "restaurante").first()
                or db.query(ReportePerdido.id).first()):
            return
        hoy, ahora = date.today(), datetime.now()
        for clave, datos in RESTAURANTES_DEMO:
            if db.query(Perfil.id).filter(Perfil.handle == clave).first():
                continue
            db.add(Perfil(usuario_id=negocios.id, tipo="entidad", categoria="restaurante", handle=clave,
                          pais="Perú", ciudad="Lima", **datos))
        db.flush()
        cafe = db.query(Perfil).filter(Perfil.handle == "cafe-huellitas", Perfil.usuario_id == negocios.id).first()
        if cafe:
            db.add(Publicacion(perfil_id=cafe.id, texto=POST_CAFE, creado=ahora - timedelta(hours=7)))
        P = {p.handle: p for p in db.query(Perfil).filter(Perfil.usuario_id == vecinos.id,
                                                          Perfil.handle.in_(["toby", "canela", "lola"]))}
        if len(P) == 3:
            avisos = _avisos_demo(P, vecinos.id, hoy, ahora)
            db.add_all(avisos)
            db.flush()
            demo = db.query(Usuario).filter(Usuario.email == DEMO_EMAIL).first()
            rocky = db.query(Perfil).filter(Perfil.handle == "rocky").first()
            if demo and rocky and rocky.usuario_id == demo.id:
                _notificar_avisos_demo(db, rocky, avisos, ahora)
        db.commit()
        print("  Datos demo agregados: restaurantes pet friendly y avisos de perdidos/encontrados.")
