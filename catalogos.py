"""Catálogos y constantes de Pawbook (editar aquí para cambiar opciones de la web)."""

ESPECIES = {
    "perro": ("Perro", "🐶"),
    "gato": ("Gato", "🐱"),
    "conejo": ("Conejo", "🐰"),
    "ave": ("Ave", "🐦"),
    "hamster": ("Hámster", "🐹"),
    "cuy": ("Cuy", "🐹"),
    "tortuga": ("Tortuga", "🐢"),
    "pez": ("Pez", "🐠"),
    "huron": ("Hurón", "🦦"),
    "otro": ("Otro", "🐾"),
}

RAZAS = {
    "perro": [
        "Mestizo", "Labrador Retriever", "Golden Retriever", "Pastor Alemán", "Bulldog Francés",
        "Bulldog Inglés", "Poodle", "Shih Tzu", "Schnauzer", "Chihuahua", "Beagle", "Husky Siberiano",
        "Pug", "Yorkshire Terrier", "Dachshund (Salchicha)", "Border Collie", "Cocker Spaniel",
        "Boxer", "Rottweiler", "Pitbull", "Pomerania", "Maltés", "Shar Pei", "Akita",
        "Perro sin pelo del Perú", "Jack Russell Terrier", "Bichón Frisé", "Gran Danés", "San Bernardo",
    ],
    "gato": [
        "Mestizo", "Siamés", "Persa", "Maine Coon", "Angora Turco", "Bengalí", "Ragdoll",
        "Británico de pelo corto", "Esfinge", "Azul Ruso", "Bombay", "Scottish Fold",
    ],
    "conejo": ["Mestizo", "Cabeza de León", "Belier (Lop)", "Holland Lop", "Rex", "Enano Holandés", "Angora"],
    "ave": ["Periquito australiano", "Canario", "Cacatúa ninfa", "Agapornis", "Loro", "Pericos"],
    "hamster": ["Sirio", "Ruso", "Roborovski", "Chino"],
    "cuy": ["Peruano", "Abisinio", "Inglés", "Andino"],
    "tortuga": ["Orejas rojas", "Terrestre", "Morrocoy"],
    "pez": ["Betta", "Goldfish", "Guppy", "Disco", "Escalar"],
    "huron": ["Estándar", "Albino", "Panda"],
    "otro": [],
}

TAGS_SUGERIDOS = [
    "juguetón", "parque", "pelota", "nadador", "playa", "paseo", "dormilón", "glotón",
    "sociable", "tímido", "cariñoso", "energético", "tranquilo", "viajero", "mimoso",
    "guardián", "adoptado", "entrenado", "corredor", "fotogénico",
]

SEXOS = {"macho": ("Macho", "♂"), "hembra": ("Hembra", "♀")}

CATEGORIAS_ENTIDAD = {
    "centro_adopcion": ("Centro de adopción", "🏠"),
    "veterinaria": ("Veterinaria", "🩺"),
    "tienda": ("Tienda de mascotas", "🛍️"),
    "entrenamiento": ("Entrenamiento", "🎓"),
    "paseador": ("Paseador", "🦮"),
    "grooming": ("Peluquería / Grooming", "✂️"),
    "marca": ("Marca de productos", "🏷️"),
    "caridad": ("Caridad / ONG", "💛"),
    "restaurante": ("Restaurante / café pet friendly", "🍽️"),
    "otro": ("Otro servicio", "⭐"),
}

# Qué ofrece un restaurante o café pet friendly (se guarda en Perfil.tags de la entidad)
AMENIDADES_PET_FRIENDLY = {
    "terraza": ("Terraza o área exterior", "🌿"),
    "interior": ("Mascotas en el interior", "🏠"),
    "agua": ("Plato de agua", "💧"),
    "menu": ("Menú o snacks para mascotas", "🦴"),
    "grandes": ("Acepta perros grandes", "🐕"),
    "gatos": ("También gatos y otras mascotas", "🐱"),
}

# Capas del mapa: (etiqueta, emoji, color)
CAPAS_MAPA = {
    "veterinarias": ("Veterinarias", "🩺", "#E5484D"),
    "tiendas": ("Tiendas y marcas", "🛍️", "#F5A301"),
    "parques": ("Parques", "🌳", "#2F9E44"),
    "adopcion": ("Adopción y ONG", "🏠", "#8E44AD"),
    "servicios": ("Otros servicios", "⭐", "#0B7285"),
    "petfriendly": ("Restaurantes pet friendly", "🍽️", "#C2255C"),
    "perdidos": ("Perdidos y encontrados", "🚨", "#D9480F"),
    "amigos": ("Amigos cerca", "🐾", "#023E90"),
}

CATEGORIA_A_CAPA = {
    "veterinaria": "veterinarias",
    "tienda": "tiendas",
    "marca": "tiendas",
    "centro_adopcion": "adopcion",
    "caridad": "adopcion",
    "entrenamiento": "servicios",
    "paseador": "servicios",
    "grooming": "servicios",
    "restaurante": "petfriendly",
    "otro": "servicios",
}

TIPOS_LUGAR = {
    "parque": ("Parque", "🌳", "parques"),
    "veterinaria": ("Veterinaria", "🩺", "veterinarias"),
    "tienda": ("Tienda", "🛍️", "tiendas"),
    "restaurante": ("Restaurante / café pet friendly", "🍽️", "petfriendly"),
    "otro": ("Otro", "📍", "servicios"),
}

# Avisos de mascotas perdidas / encontradas: (etiqueta corta, emoji, texto del sello)
TIPOS_AVISO = {
    "perdido": ("Perdida", "🚨", "Se busca"),
    "encontrado": ("Encontrada", "🔎", "Encontrada"),
}
# Radio (km) para avisar a vecinos y para sugerir coincidencias entre perdidos y encontrados
RADIO_AVISO_KM = 3
RADIO_COINCIDENCIA_KM = 5

TIPOS_EVENTO = {
    "veterinaria": ("Cita veterinaria", "🩺", "#E5484D"),
    "vacuna": ("Vacunación", "💉", "#023E90"),
    "desparasitacion": ("Desparasitación", "💊", "#0B7285"),
    "grooming": ("Baño / grooming", "🛁", "#8E44AD"),
    "medicamento": ("Medicamento", "⏰", "#D9480F"),
    "cumpleanos": ("Cumpleaños", "🎂", "#F5A301"),
    "otro": ("Otro", "📌", "#5B6475"),
}

OPCIONES_ALERTA = [
    ("", "Sin alerta"),
    ("0", "El mismo día"),
    ("1", "1 día antes"),
    ("3", "3 días antes"),
    ("7", "1 semana antes"),
]

# Anuncios pagados: (etiqueta, días, precio en soles). Precios referenciales: edítalos aquí.
PLANES_ANUNCIO = {
    "semana": ("1 semana", 7, 29),
    "mes": ("1 mes", 30, 89),
    "trimestre": ("3 meses", 90, 219),
}

CATEGORIAS_ANUNCIO_PAGADO = {
    "producto": "Producto",
    "servicio": "Servicio",
    "promocion": "Promoción / descuento",
    "evento": "Evento",
}

CATEGORIAS_ANUNCIO_GRATUITO = {
    "adopcion": "Adopción",
    "campana_vacunacion": "Campaña de vacunación gratuita",
    "campana_esterilizacion": "Campaña de esterilización gratuita",
    "donaciones": "Donaciones / caridad",
}

# Entidades que pueden publicar cualquier anuncio gratuito
ENTIDADES_ANUNCIO_GRATIS = {"centro_adopcion", "caridad"}
# Cualquier entidad puede anunciar gratis estas campañas (deben ser gratuitas para el público)
CAMPANAS_GRATIS_PARA_TODOS = {"campana_vacunacion", "campana_esterilizacion"}

PAISES = [
    "Perú", "Argentina", "Bolivia", "Brasil", "Chile", "Colombia", "Costa Rica", "Cuba", "Ecuador",
    "El Salvador", "España", "Estados Unidos", "Guatemala", "Honduras", "México", "Nicaragua",
    "Panamá", "Paraguay", "Puerto Rico", "República Dominicana", "Uruguay", "Venezuela", "Otro",
]

DISTRITOS_LIMA = [
    "Barranco", "Breña", "Chorrillos", "Jesús María", "La Molina", "La Victoria", "Lince",
    "Los Olivos", "Magdalena del Mar", "Miraflores", "Pueblo Libre", "Rímac", "San Borja",
    "San Isidro", "San Juan de Lurigancho", "San Juan de Miraflores", "San Martín de Porres",
    "San Miguel", "Santiago de Surco", "Surquillo", "Callao", "Ate", "Cercado de Lima",
]

# Centro por defecto del mapa (Lima)
CENTRO_MAPA = (-12.1000, -77.0300)

# Íconos SVG (estilo trazo, 24x24)
ICONOS = {
    "inicio": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    "buscar": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "mapa": '<polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>',
    "calendario": '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "campana": '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    "corazon": '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    "comentario": '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    "usuario": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "usuarios": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "mas": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "imagen": '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    "salir": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
    "editar": '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
    "cerrar": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "enviar": '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    "pin": '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    "reloj": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "telefono": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
    "correo": '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    "web": '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "basura": '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "izq": '<polyline points="15 18 9 12 15 6"/>',
    "der": '<polyline points="9 18 15 12 9 6"/>',
    "abajo": '<polyline points="6 9 12 15 18 9"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "megafono": '<path d="M3 11l18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
    "escudo": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "huella": '<circle cx="11" cy="4" r="2"/><circle cx="18" cy="8" r="2"/><circle cx="20" cy="16" r="2"/><path d="M9 10a5 5 0 0 1 5 5v3.5a3.5 3.5 0 0 1-6.84 1.045Q6.52 17.48 4.46 16.84A3.5 3.5 0 0 1 5.5 10Z"/>',
    "ubicar": '<circle cx="12" cy="12" r="10"/><line x1="22" y1="12" x2="18" y2="12"/><line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/><line x1="12" y1="22" x2="12" y2="18"/>',
    "descargar": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "externo": '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
    "regalo": '<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>',
    "cambiar": '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "puntos": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    "barras": '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
    "pausa": '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
    "play": '<polygon points="5 3 19 12 5 21 5 3"/>',
    "estrella": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "chispas": '<path d="M12 3l1.9 5.8 5.8 1.9-5.8 1.9L12 18.4l-1.9-5.8-5.8-1.9 5.8-1.9z"/><path d="M19 3v4M17 5h4"/>',
    "alerta": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "cubiertos": '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3zm0 0v7"/>',
    "compartir": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>',
    "menu": '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>',
}
