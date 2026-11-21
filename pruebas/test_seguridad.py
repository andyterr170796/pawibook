"""Pruebas de seguridad de Pawbook (mismo enfoque que la auditoría de la Suite Zoria).

Cada prueba reproduce un ataque o un descuido concreto contra una base SQLite temporal (sin puertos,
sin tocar pawbook.db, sin enviar correos reales) y comprueba que se rechaza.

Ejecutar desde la carpeta del proyecto:   python -m unittest discover -s pruebas -v
"""
import asyncio
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
_temporal = tempfile.TemporaryDirectory(prefix="pawbook-seguridad-", ignore_cleanup_errors=True)
CARPETA = Path(_temporal.name)
# Todo antes de importar la app: cargar_env() no pisa valores ya definidos.
os.environ.update({
    "PAWBOOK_DB": str(CARPETA / "prueba.db"),
    "PAWBOOK_UPLOADS": str(CARPETA / "uploads"),
    "PAWBOOK_LOGS": str(CARPETA / "logs"),
    "PAWBOOK_SECRET_KEY": "clave-de-pruebas-" + "x" * 40,
    "PAWBOOK_DEMO": "0",
    "PAWBOOK_MAX_SUBIDA_MB": "1",
    "PAWBOOK_URL_PUBLICA": "",
    "PAWBOOK_ORIGENES": "",
    "OPENAI_API_KEY": "",
    "RESEND_API_KEY": "",
    "RESEND_FROM": "",
    "RESEND_REPLY_TO": "",
})

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

import correos  # noqa: E402
import main  # noqa: E402
import migrar_bd  # noqa: E402
import seguridad  # noqa: E402
import utilidades  # noqa: E402
from models import Anuncio, Base, Perfil, SessionLocal, TokenRecuperacion, Usuario, engine  # noqa: E402

CLAVE = "ClaveSegura1"
HASH_CLAVE = utilidades.hash_password(CLAVE)  # una sola vez: 600 000 iteraciones no son gratis
MALICIOSO = "https://sitio-malicioso.example"


class PruebasSeguridad(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        seguridad.limitador.reiniciar()
        with SessionLocal() as db:
            db.add_all([
                Usuario(id=1, nombre="Ana", email="ana@gmail.com", password_hash=HASH_CLAVE),
                Usuario(id=2, nombre="Beto", email="beto@gmail.com", password_hash=HASH_CLAVE),
                Usuario(id=3, nombre="Cuenta Demo", email=main.DEMO_EMAIL, password_hash=HASH_CLAVE),
            ])
            db.add_all([
                Perfil(id=1, usuario_id=1, tipo="mascota", handle="rocky", nombre="Rocky", especie="perro"),
                Perfil(id=2, usuario_id=2, tipo="entidad", handle="vete", nombre="Vete Beto", categoria="veterinaria"),
                Perfil(id=3, usuario_id=3, tipo="mascota", handle="demo", nombre="Demo", especie="gato"),
            ])
            db.commit()
        self.cliente = TestClient(main.app)
        self.correos = []
        self._parches = [
            patch.object(main.correos, "enviar_en_segundo_plano", side_effect=lambda *a: self.correos.append(a)),
            # Reloj fijo para el limitador: sus ventanas son por minuto y una prueba que cruza el cambio de
            # minuto vería el contador reiniciado.
            patch.object(seguridad, "time", SimpleNamespace(time=lambda: 1_700_000_010.0)),
        ]
        for p in self._parches:
            p.start()

    def tearDown(self):
        for p in self._parches:
            p.stop()
        self.cliente.close()
        engine.dispose()

    def entrar(self, cliente=None, email="ana@gmail.com", password=CLAVE):
        cliente = cliente or self.cliente
        r = cliente.post("/login", data={"email": email, "password": password, "next": "/"},
                         follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text[:300])
        return cliente

    def sesion_activa(self, cliente) -> bool:
        return cliente.get("/cuenta", follow_redirects=False).status_code == 200

    # ------------------------------------------------------------ cabeceras y cookies
    def test_cabeceras_de_seguridad(self):
        h = self.cliente.get("/login").headers
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["x-frame-options"], "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", h["content-security-policy"])
        self.assertIn("object-src 'none'", h["content-security-policy"])
        self.assertEqual(h["referrer-policy"], "strict-origin-when-cross-origin")
        self.assertIn("camera=()", h["permissions-policy"])
        self.assertNotIn("strict-transport-security", h, "HSTS solo por HTTPS")
        with TestClient(main.app, base_url="https://testserver") as seguro:
            self.assertIn("max-age=", seguro.get("/login").headers["strict-transport-security"])

    def test_cookie_de_sesion_segura_por_https(self):
        with TestClient(main.app, base_url="https://testserver") as seguro:
            r = seguro.post("/login", data={"email": "ana@gmail.com", "password": CLAVE}, follow_redirects=False)
            cookie = r.headers["set-cookie"].lower()
            self.assertIn("pawbook_sesion=", cookie)
            self.assertIn("secure", cookie)
            self.assertIn("httponly", cookie)
            self.assertIn("samesite=lax", cookie)
        r = self.cliente.post("/login", data={"email": "ana@gmail.com", "password": CLAVE}, follow_redirects=False)
        self.assertNotIn("secure", r.headers["set-cookie"].lower(), "en http://localhost la cookie debe funcionar")

    def test_clave_de_sesion_corta_se_rechaza(self):
        with patch.dict(os.environ, {"PAWBOOK_SECRET_KEY": "corta"}):
            with self.assertRaises(RuntimeError):
                utilidades.obtener_secret_key()

    # ------------------------------------------------------------ CSRF
    def test_post_desde_otro_sitio_se_rechaza(self):
        self.entrar()
        ataque = self.cliente.post("/api/seguir/2", headers={"Origin": MALICIOSO})
        self.assertEqual(ataque.status_code, 403)
        self.assertEqual(self.cliente.post("/api/seguir/2", headers={"Origin": "null"}).status_code, 403)
        sin_origin = self.cliente.post("/api/seguir/2", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(sin_origin.status_code, 403)
        propio = self.cliente.post("/api/seguir/2", headers={"Origin": "http://testserver"})
        self.assertEqual(propio.status_code, 200, propio.text)
        self.assertTrue(propio.json()["siguiendo"])
        leer = self.cliente.get("/amigos", headers={"Origin": MALICIOSO})
        self.assertEqual(leer.status_code, 200, "leer no cambia datos")

    def test_login_forzado_desde_otro_sitio_se_rechaza(self):
        # Sin cookie previa: un sitio ajeno no puede iniciar tu sesión en la cuenta del atacante.
        r = self.cliente.post("/login", data={"email": "ana@gmail.com", "password": CLAVE},
                              headers={"Origin": MALICIOSO}, follow_redirects=False)
        self.assertEqual(r.status_code, 403)

    def test_cerrar_sesion_solo_por_post(self):
        self.entrar()
        self.cliente.get("/logout", follow_redirects=False)
        self.assertTrue(self.sesion_activa(self.cliente), "un enlace (GET) no debe cerrar la sesión")
        self.cliente.post("/logout", follow_redirects=False)
        self.assertFalse(self.sesion_activa(self.cliente))

    # ------------------------------------------------------------ inicio de sesión
    def test_limite_de_intentos_de_login(self):
        for _ in range(main.LIMITE_LOGIN_POR_MINUTO):
            r = self.cliente.post("/login", data={"email": "ana@gmail.com", "password": "Equivocada1"})
            self.assertEqual(r.status_code, 401)
        bloqueado = self.cliente.post("/login", data={"email": "ana@gmail.com", "password": CLAVE},
                                      follow_redirects=False)
        self.assertEqual(bloqueado.status_code, 429, "ni con la clave correcta mientras dura el bloqueo")
        self.assertIn("Demasiados intentos", bloqueado.text)

    def test_x_forwarded_for_inventado_no_salta_el_limite(self):
        for i in range(main.LIMITE_LOGIN_POR_MINUTO):
            self.cliente.post("/login", data={"email": f"otro{i}@gmail.com", "password": "x"},
                              headers={"X-Forwarded-For": f"10.0.0.{i}"})
        r = self.cliente.post("/login", data={"email": "nuevo@gmail.com", "password": "x"},
                              headers={"X-Forwarded-For": "10.9.9.9"})
        self.assertEqual(r.status_code, 429)

    def test_login_no_revela_si_el_correo_existe(self):
        with patch.object(main, "gastar_verificacion") as senuelo:
            no_existe = self.cliente.post("/login", data={"email": "nadie@gmail.com", "password": "Equivocada1"})
        senuelo.assert_called_once()  # misma demora que una verificación real
        existe = self.cliente.post("/login", data={"email": "ana@gmail.com", "password": "Equivocada1"})
        self.assertEqual(no_existe.status_code, existe.status_code)
        self.assertIn("Correo o contraseña incorrectos.", no_existe.text)
        self.assertIn("Correo o contraseña incorrectos.", existe.text)

    def test_hash_antiguo_se_actualiza_al_entrar(self):
        import hashlib
        sal = "00" * 16
        viejo = f"pbkdf2_sha256$260000${sal}$" + hashlib.pbkdf2_hmac(
            "sha256", CLAVE.encode(), bytes.fromhex(sal), 260000).hex()
        with SessionLocal() as db:
            db.get(Usuario, 1).password_hash = viejo
            db.commit()
        self.entrar()
        with SessionLocal() as db:
            nuevo = db.get(Usuario, 1).password_hash
        self.assertTrue(nuevo.startswith(f"pbkdf2_sha256${utilidades.ITERACIONES_PBKDF2}$"))
        self.assertTrue(utilidades.verificar_password(CLAVE, nuevo))

    # ------------------------------------------------------------ redirecciones
    def test_next_no_permite_saltar_a_otro_dominio(self):
        for malo in ["//evil.example", "/\\evil.example", "/\\/evil.example", "https://evil.example",
                     "/\t/evil.example", "javascript:alert(1)"]:
            self.assertEqual(main.siguiente_seguro(malo), "/", malo)
        self.assertEqual(main.siguiente_seguro("/p/rocky?antes=3"), "/p/rocky?antes=3")
        r = self.cliente.post("/login", data={"email": "ana@gmail.com", "password": CLAVE, "next": "/\\evil.example"},
                              follow_redirects=False)
        self.assertEqual(r.headers["location"], "/")

    def test_referer_de_otro_sitio_no_se_usa_para_volver(self):
        self.entrar()
        r = self.cliente.post("/perfil/activar/1", headers={"Referer": "https://evil.example/?testserver"},
                              follow_redirects=False)
        self.assertEqual(r.headers["location"], "/")
        r = self.cliente.post("/perfil/activar/1", headers={"Referer": "http://testserver/amigos?tab=entidades"},
                              follow_redirects=False)
        self.assertEqual(r.headers["location"], "/amigos?tab=entidades")

    def test_anuncio_sin_aprobar_no_redirige_afuera(self):
        with SessionLocal() as db:
            db.add(Anuncio(id=1, perfil_id=2, tipo="pagado", categoria="promocion", titulo="Oferta",
                           enlace="https://phishing.example/login", estado="pendiente"))
            db.commit()
        r = self.cliente.get("/anuncio/1/ir", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/p/vete")
        with SessionLocal() as db:
            db.get(Anuncio, 1).estado = "activo"
            db.commit()
        r = self.cliente.get("/anuncio/1/ir", follow_redirects=False)
        self.assertEqual(r.headers["location"], "https://phishing.example/login", "aprobado por un admin, sí")

    # ------------------------------------------------------------ contraseñas y sesiones
    def test_politica_de_contrasenas(self):
        for mala in ["Corta1", "sinmayuscula1", "SINMINUSCULA1", "SinNumeros", "Aa1" + "x" * 200]:
            self.assertIsNotNone(seguridad.error_password(mala), mala)
        self.assertIsNone(seguridad.error_password("ClaveSegura1"))
        r = self.cliente.post("/registro", data={"nombre": "Caro", "email": "caro@gmail.com",
                                                 "password": "password", "password2": "password"})
        self.assertIn("mayúscula", r.text)
        with SessionLocal() as db:
            self.assertIsNone(db.query(Usuario).filter(Usuario.email == "caro@gmail.com").first())

    def test_registro_envia_bienvenida(self):
        r = self.cliente.post("/registro", data={"nombre": "Caro", "email": "caro@gmail.com",
                                                 "password": CLAVE, "password2": CLAVE}, follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text[:300])
        self.assertEqual(len(self.correos), 1)
        self.assertEqual(self.correos[0][0], "caro@gmail.com")
        self.assertIn("Bienvenido", self.correos[0][1])

    def test_cambiar_contrasena_cierra_las_otras_sesiones(self):
        a = self.entrar()
        b = self.entrar(TestClient(main.app))
        r = a.post("/cuenta/password", data={"actual": CLAVE, "password": "OtraClave22", "password2": "OtraClave22"},
                   follow_redirects=False)
        self.assertEqual(r.status_code, 303, r.text[:300])
        self.assertTrue(self.sesion_activa(a), "quien cambió la contraseña sigue dentro")
        self.assertFalse(self.sesion_activa(b), "la sesión del otro dispositivo ya no vale")
        self.assertEqual(self.correos[-1][0], "ana@gmail.com")
        self.assertIn("contraseña", self.correos[-1][1])
        b.close()

    def test_cambiar_contrasena_exige_la_actual(self):
        self.entrar()
        r = self.cliente.post("/cuenta/password", data={"actual": "NoEsLaMia1", "password": "OtraClave22",
                                                         "password2": "OtraClave22"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("La contraseña actual no es correcta.", r.text)

    def test_cuenta_demo_no_cambia_contrasena_ni_recibe_correos(self):
        self.entrar(email=main.DEMO_EMAIL)
        r = self.cliente.post("/cuenta/password", data={"actual": CLAVE, "password": "OtraClave22",
                                                         "password2": "OtraClave22"})
        self.assertEqual(r.status_code, 403)
        self.cliente.post("/recuperar", data={"email": main.DEMO_EMAIL})
        self.assertEqual(self.correos, [])

    # ------------------------------------------------------------ recuperación por correo
    def _pedir_enlace(self, email="ana@gmail.com", **kwargs) -> str:
        r = self.cliente.post("/recuperar", data={"email": email}, **kwargs)
        self.assertEqual(r.status_code, 200)
        self.assertIn("te enviamos un enlace", r.text)
        destino, asunto, html_cuerpo, texto = self.correos[-1]
        self.assertEqual(destino, email)
        return next(linea for linea in texto.splitlines() if "/restablecer?token=" in linea)

    def test_recuperacion_completa_y_de_un_solo_uso(self):
        otro = self.entrar(TestClient(main.app))
        enlace = self._pedir_enlace()
        token = parse_qs(urlsplit(enlace).query)["token"][0]
        self.assertIn("Crea tu nueva contraseña", self.cliente.get(f"/restablecer?token={token}").text)
        debil = self.cliente.post("/restablecer", data={"token": token, "password": "debil", "password2": "debil"})
        self.assertIn("al menos 8", debil.text)
        ok = self.cliente.post("/restablecer", data={"token": token, "password": "NuevaClave9", "password2": "NuevaClave9"},
                               follow_redirects=False)
        self.assertEqual(ok.status_code, 303)
        self.assertEqual(ok.headers["location"], "/login")
        self.assertFalse(self.sesion_activa(otro), "restablecer cierra todas las sesiones")
        repetido = self.cliente.post("/restablecer", data={"token": token, "password": "OtraMas123", "password2": "OtraMas123"})
        self.assertIn("ya no sirve", repetido.text)
        self.assertEqual(self.cliente.post("/login", data={"email": "ana@gmail.com", "password": CLAVE}).status_code, 401)
        self.entrar(TestClient(main.app), password="NuevaClave9").close()
        with SessionLocal() as db:
            guardado = db.query(TokenRecuperacion).one()
        self.assertNotIn(token, guardado.token_hash, "solo se guarda el hash del token")
        otro.close()

    def test_enlace_de_recuperacion_no_usa_la_cabecera_host(self):
        enlace = self._pedir_enlace(headers={"Host": "sitio-malicioso.example"})
        self.assertTrue(enlace.startswith(f"http://localhost:{main.PUERTO}/restablecer?token="), enlace)
        with patch.dict(os.environ, {"PAWBOOK_URL_PUBLICA": "https://pawbook.example/"}):
            enlace = self._pedir_enlace()
        self.assertTrue(enlace.startswith("https://pawbook.example/restablecer?token="), enlace)

    def test_pedir_un_enlace_nuevo_anula_el_anterior(self):
        primero = parse_qs(urlsplit(self._pedir_enlace()).query)["token"][0]
        self._pedir_enlace()
        self.assertIn("ya no sirve", self.cliente.get(f"/restablecer?token={primero}").text)

    def test_recuperacion_misma_respuesta_si_el_correo_no_existe(self):
        r = self.cliente.post("/recuperar", data={"email": "nadie@gmail.com"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("te enviamos un enlace", r.text)
        self.assertEqual(self.correos, [])

    def test_enlace_vencido_no_sirve(self):
        with SessionLocal() as db:
            db.add(TokenRecuperacion(usuario_id=1, token_hash=main.hash_token("vencido"),
                                     expira=datetime.now() - timedelta(minutes=1)))
            db.commit()
        self.assertIn("ya no sirve", self.cliente.get("/restablecer?token=vencido").text)

    def test_limite_de_pedidos_de_recuperacion(self):
        for _ in range(3):
            self.cliente.post("/recuperar", data={"email": "ana@gmail.com"})
        self.assertEqual(self.cliente.post("/recuperar", data={"email": "ana@gmail.com"}).status_code, 429)
        self.assertEqual(len(self.correos), 3)

    # ------------------------------------------------------------ correos (Resend)
    def test_no_se_envia_a_dominios_ficticios(self):
        with patch("urllib.request.urlopen") as red:
            for email in ["vecinos@pawbook.demo", "admin@pawbook.local", main.DEMO_EMAIL, "a@example.com", "sin-arroba"]:
                self.assertEqual(correos.enviar(email, "x", "<p>x</p>", "x"), correos.OMITIDO, email)
        red.assert_not_called()
        self.assertTrue(correos.es_destino_entregable("persona@gmail.com"))

    def test_sin_clave_de_resend_no_se_llama_a_la_red(self):
        with patch("urllib.request.urlopen") as red:
            self.assertEqual(correos.enviar("persona@gmail.com", "x", "<p>x</p>", "x"), correos.NO_CONFIGURADO)
        red.assert_not_called()

    def test_peticion_a_resend(self):
        class Respuesta(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch.dict(os.environ, {"RESEND_API_KEY": "re_prueba", "RESEND_FROM": "Pawbook <hola@pawbook.example>",
                                     "RESEND_REPLY_TO": "soporte@pawbook.example"}), \
                patch("urllib.request.urlopen", return_value=Respuesta(b'{"id":"1"}')) as red:
            asunto, html_cuerpo, texto = correos.correo_recuperacion("Ana <b>", "https://pawbook.example/x", 60,
                                                                     "https://pawbook.example")
            self.assertEqual(correos.enviar("persona@gmail.com", asunto, html_cuerpo, texto), correos.ENVIADO)
        peticion = red.call_args[0][0]
        self.assertEqual(peticion.full_url, "https://api.resend.com/emails")
        self.assertEqual(peticion.get_header("Authorization"), "Bearer re_prueba")
        cuerpo = json.loads(peticion.data)
        self.assertEqual(cuerpo["from"], "Pawbook <hola@pawbook.example>")
        self.assertEqual(cuerpo["to"], ["persona@gmail.com"])
        self.assertEqual(cuerpo["reply_to"], "soporte@pawbook.example")
        self.assertIn("Restablece", cuerpo["subject"])
        self.assertIn("Ana &lt;b&gt;", cuerpo["html"], "los datos del usuario se escapan en el HTML")
        self.assertIn("https://pawbook.example/x", cuerpo["text"])

    # ------------------------------------------------------------ Pawi
    def test_limite_de_mensajes_a_pawi(self):
        self.entrar()
        for _ in range(main.LIMITE_PAWI_POR_MINUTO):
            r = self.cliente.post("/api/asistente", json={"mensaje": "hola"})
            self.assertEqual(r.status_code, 200)
        r = self.cliente.post("/api/asistente", json={"mensaje": "hola"})
        self.assertEqual(r.status_code, 429)
        self.assertIn("respiro", r.json()["detail"])

    def test_json_malformado_no_rompe_el_servidor(self):
        self.entrar()
        seguridad.limitador.reiniciar()
        r = self.cliente.post("/api/asistente", content=b"no es json", headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 400)
        r = self.cliente.post("/api/asistente", json=["lista"])
        self.assertEqual(r.status_code, 400)

    # ------------------------------------------------------------ archivos
    def _subir(self, datos: bytes):
        class Archivo:
            filename = "foto.png"

            async def read(self, n=-1):
                return datos

        return asyncio.run(utilidades.guardar_imagen(Archivo(), "pruebas", 600))

    def test_solo_se_aceptan_fotos_comunes(self):
        eps = (b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nnewpath 0 0 moveto 10 10 lineto stroke\n"
               b"showpage\n%%EOF\n")
        with self.assertRaises(ValueError):
            self._subir(eps)
        bmp = io.BytesIO()
        Image.new("RGB", (8, 8)).save(bmp, "BMP")
        with self.assertRaises(ValueError):
            self._subir(bmp.getvalue())
        png = io.BytesIO()
        Image.new("RGB", (40, 30), "orange").save(png, "PNG")
        ruta = self._subir(png.getvalue())
        self.assertTrue(ruta.startswith("/uploads/pruebas/") and ruta.endswith(".webp"))
        self.assertTrue((CARPETA / "uploads" / "pruebas" / Path(ruta).name).exists())

    def test_imagen_con_demasiados_pixeles(self):
        enorme = io.BytesIO()
        Image.new("1", (7000, 7000)).save(enorme, "PNG")  # 49 MP en pocos KB
        with self.assertRaises(ValueError) as e:
            self._subir(enorme.getvalue())
        self.assertIn("píxeles", str(e.exception))
        bomba = io.BytesIO()
        Image.new("1", (12000, 12000)).save(bomba, "PNG")  # 144 MP: "bomba" de descompresión
        with self.assertRaises(ValueError):
            self._subir(bomba.getvalue())

    def test_borrar_archivo_no_sale_de_uploads(self):
        victima = CARPETA / "secreto.txt"
        victima.write_text("no borrar")
        utilidades.borrar_archivo("/uploads/../secreto.txt")
        self.assertTrue(victima.exists())

    def test_envio_demasiado_grande(self):
        # La app completa (con todos sus middlewares), con el tope de 1 MB definido arriba para las pruebas.
        self.entrar()
        foto = {"imagen": ("a.jpg", b"x" * 1_500_000, "image/jpeg")}
        r = self.cliente.post("/publicar", files=foto, data={"texto": "hola"})
        self.assertEqual(r.status_code, 413)
        self.assertIn("El envío es demasiado grande", r.text)
        por_partes = self.cliente.post("/publicar", content=(b"x" * 300_000 for _ in range(5)),  # sin Content-Length
                                       headers={"Content-Type": "multipart/form-data; boundary=abc"})
        self.assertEqual(por_partes.status_code, 413)
        chico = self.cliente.post("/publicar", data={"texto": "Un paseo corto"}, follow_redirects=False)
        self.assertEqual(chico.status_code, 303, "lo normal sigue funcionando")

        async def ruta(request):
            return PlainTextResponse(str(len(await request.body())))

        mini = seguridad.LimiteCuerpo(Starlette(routes=[Route("/subir", ruta, methods=["POST"])]), max_bytes=1000)
        with TestClient(mini) as c:
            self.assertEqual(c.post("/subir", content=(b"x" * 300 for _ in range(3))).text, "900",
                             "un cuerpo por partes dentro del tope llega completo")

    # ------------------------------------------------------------ migración
    def test_migracion_de_una_base_antigua(self):
        engine.dispose()
        with closing(sqlite3.connect(os.environ["PAWBOOK_DB"])) as con:
            con.execute("ALTER TABLE usuarios DROP COLUMN version_sesion")
            con.execute("DROP TABLE tokens_recuperacion")
            con.execute("UPDATE usuarios SET password_hash = ? WHERE email = ?",
                        (utilidades.hash_password(migrar_bd.PASSWORD_DEMO_ANTIGUA), main.DEMO_EMAIL))
            con.commit()
        self.assertTrue(migrar_bd.pendientes())
        respaldos_antes = set(CARPETA.glob("prueba.db-respaldo-*"))
        self.assertTrue(migrar_bd.migrar(silencioso=True))
        self.assertFalse(migrar_bd.pendientes())
        self.assertEqual(len(set(CARPETA.glob("prueba.db-respaldo-*")) - respaldos_antes), 1, "respalda antes")
        with SessionLocal() as db:
            demo = db.query(Usuario).filter(Usuario.email == main.DEMO_EMAIL).one()
            self.assertFalse(utilidades.verificar_password(migrar_bd.PASSWORD_DEMO_ANTIGUA, demo.password_hash))
            self.assertTrue(utilidades.verificar_password(CLAVE, db.get(Usuario, 1).password_hash),
                            "las cuentas reales no se tocan")
        self.assertFalse(migrar_bd.migrar(silencioso=True), "una segunda vez no hace nada")


if __name__ == "__main__":
    unittest.main()
