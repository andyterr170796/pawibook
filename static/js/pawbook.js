/* Pawbook — interacciones del sitio */
(function () {
  "use strict";

  const $ = (sel, raiz) => (raiz || document).querySelector(sel);
  const $$ = (sel, raiz) => Array.from((raiz || document).querySelectorAll(sel));

  // ------------------------------------------------------------ utilidades
  async function api(url, datos) {
    const opciones = { method: "POST", headers: { "Accept": "application/json" } };
    if (datos !== undefined) {
      opciones.headers["Content-Type"] = "application/json";
      opciones.body = JSON.stringify(datos);
    }
    const r = await fetch(url, opciones);
    if (r.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); throw new Error("401"); }
    const json = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(json.detail || "Ocurrió un error");
    return json;
  }

  function toast(texto, tipo) {
    $$(".toast").forEach((t) => t.remove());
    const t = document.createElement("div");
    t.className = "toast" + (tipo === "error" ? " error" : "");
    t.setAttribute("role", "status");
    t.textContent = texto;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }
  window.pawToast = toast;

  // flash del servidor
  const flash = $(".toast[data-flash]");
  if (flash) {
    setTimeout(() => flash.remove(), 4500);
    const x = $("button", flash);
    if (x) x.addEventListener("click", () => flash.remove());
  }

  // ------------------------------------------------------------ menú de perfil
  const selector = $(".selector");
  if (selector) {
    const boton = $("button", selector), menu = $(".menu", selector);
    boton.addEventListener("click", (e) => {
      e.stopPropagation();
      const abierto = !menu.classList.toggle("oculto");
      boton.setAttribute("aria-expanded", abierto ? "true" : "false");
    });
    document.addEventListener("click", (e) => { if (!selector.contains(e.target)) menu.classList.add("oculto"); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") menu.classList.add("oculto"); });
  }

  // ------------------------------------------------------------ confirmaciones
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (f.matches("form[data-confirmar]") && !confirm(f.dataset.confirmar)) e.preventDefault();
  });

  // ------------------------------------------------------------ me gusta
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-like]");
    if (!b) return;
    e.preventDefault();
    try {
      const r = await api(`/api/publicacion/${b.dataset.like}/like`);
      b.classList.toggle("activa", r.me_gusta);
      b.setAttribute("aria-pressed", r.me_gusta ? "true" : "false");
      $(".n", b).textContent = r.total;
      if (r.me_gusta) { b.classList.add("pop"); setTimeout(() => b.classList.remove("pop"), 250); }
    } catch (err) { if (err.message !== "401") toast(err.message, "error"); }
  });

  // ------------------------------------------------------------ comentarios
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-abrir-comentarios]");
    if (!b) return;
    const pub = b.closest(".publicacion");
    const zona = $(".comentarios", pub);
    zona.classList.remove("oculto");
    const input = $(".form-comentario input", zona);
    if (input) input.focus();
  });

  document.addEventListener("click", (e) => {
    const b = e.target.closest(".ver-mas-coment");
    if (!b) return;
    $$(".comentario.oculto", b.closest(".comentarios")).forEach((c) => c.classList.remove("oculto"));
    b.remove();
  });

  document.addEventListener("submit", async (e) => {
    const f = e.target.closest(".form-comentario");
    if (!f) return;
    e.preventDefault();
    const input = $("input", f);
    const texto = input.value.trim();
    if (!texto) return;
    input.disabled = true;
    try {
      const r = await api(`/api/publicacion/${f.dataset.id}/comentar`, { texto });
      const c = document.createElement("div");
      c.className = "comentario";
      c.innerHTML = r.avatar; // marcado generado por el servidor (escapado)
      const burbuja = document.createElement("div");
      burbuja.className = "comentario-burbuja";
      const a = document.createElement("a");
      a.href = "/p/" + r.handle; a.textContent = r.autor;
      const p = document.createElement("p");
      p.textContent = r.texto;
      burbuja.append(a, p);
      const caja = document.createElement("div");
      caja.append(burbuja);
      c.append(caja);
      f.parentElement.insertBefore(c, f);
      input.value = "";
      const contador = $(`[data-n-comentarios="${f.dataset.id}"]`);
      if (contador) contador.textContent = (parseInt(contador.textContent, 10) || 0) + 1;
    } catch (err) { if (err.message !== "401") toast(err.message, "error"); }
    input.disabled = false;
    input.focus();
  });

  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-borrar-comentario]");
    if (!b || !confirm("¿Eliminar este comentario?")) return;
    try {
      await api(`/api/comentario/${b.dataset.borrarComentario}/eliminar`);
      b.closest(".comentario").remove();
    } catch (err) { toast(err.message, "error"); }
  });

  // ------------------------------------------------------------ seguir
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-seguir]");
    if (!b) return;
    e.preventDefault();
    b.disabled = true;
    try {
      const r = await api(`/api/seguir/${b.dataset.seguir}`);
      b.classList.toggle("siguiendo", r.siguiendo);
      b.classList.toggle("btn-primario", !r.siguiendo);
      $(".txt", b).textContent = r.siguiendo ? "Siguiendo" : "Seguir";
      const n = $("[data-seguidores]");
      if (n && n.dataset.seguidores === b.dataset.seguir) n.textContent = r.seguidores;
    } catch (err) { if (err.message !== "401") toast(err.message, "error"); }
    b.disabled = false;
  });

  // ------------------------------------------------------------ pareja
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-interes]");
    if (!b || b.classList.contains("enviado")) return;
    b.disabled = true;
    try {
      const r = await api(`/api/pareja/interes/${b.dataset.interes}`);
      b.classList.add("enviado");
      $(".txt", b).textContent = r.estado === "match" ? "¡Es un match!" : "Interés enviado";
      toast(r.estado === "match" ? "🎉 ¡Match! Ambos se interesaron." : "💞 Le avisamos que te interesa conocerle.");
    } catch (err) { b.disabled = false; if (err.message !== "401") toast(err.message, "error"); }
  });

  // ------------------------------------------------------------ compartir (avisos de perdidos)
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-compartir]");
    if (!b) return;
    const url = b.dataset.compartir, titulo = b.dataset.titulo || document.title;
    if (navigator.share) {
      try { await navigator.share({ title: titulo, text: titulo, url }); } catch (err) { /* cancelado */ }
      return;
    }
    try { await navigator.clipboard.writeText(url); toast("Enlace copiado. ¡Compártelo en tus grupos del barrio!"); }
    catch (err) { window.prompt("Copia este enlace:", url); }
  });

  // ------------------------------------------------------------ compositor
  const compositor = $(".compositor");
  if (compositor) {
    const area = $("textarea", compositor);
    const archivo = $("input[type=file]", compositor);
    const vista = $(".vista-previa", compositor);
    area.addEventListener("input", () => { area.style.height = "auto"; area.style.height = Math.min(area.scrollHeight, 400) + "px"; });
    archivo.addEventListener("change", () => {
      const f = archivo.files[0];
      if (!f) return;
      if (f.size > 10 * 1024 * 1024) { toast("La imagen supera los 10 MB.", "error"); archivo.value = ""; return; }
      $("img", vista).src = URL.createObjectURL(f);
      vista.classList.remove("oculto");
    });
    $("button", vista).addEventListener("click", () => { archivo.value = ""; vista.classList.add("oculto"); });
  }

  // ------------------------------------------------------------ vista previa de foto de perfil
  $$("input[type=file][data-preview]").forEach((input) => {
    input.addEventListener("change", () => {
      const f = input.files[0];
      const destino = document.getElementById(input.dataset.preview);
      if (!f || !destino) return;
      const url = URL.createObjectURL(f);
      if (destino.tagName === "IMG") destino.src = url;
      else {
        const img = document.createElement("img");
        img.src = url; img.className = destino.className.replace("avatar-emoji", ""); img.id = destino.id;
        img.style.cssText = destino.style.cssText; img.style.background = "none";
        destino.replaceWith(img);
      }
    });
  });

  // ------------------------------------------------------------ contador de palabras
  $$("textarea[data-max-palabras]").forEach((t) => {
    const max = parseInt(t.dataset.maxPalabras, 10);
    const out = document.getElementById(t.dataset.contador);
    const actualizar = () => {
      const n = (t.value.match(/\S+/g) || []).length;
      out.textContent = `${n} / ${max} palabras`;
      out.classList.toggle("excedido", n > max);
    };
    t.addEventListener("input", actualizar);
    actualizar();
  });

  // ------------------------------------------------------------ editor de tags
  $$(".tags-editor").forEach((ed) => {
    const oculto = $("input[type=hidden]", ed);
    const lista = $(".chips", ed);
    const nuevo = $("input[type=text]", ed);
    const leer = () => oculto.value.split(",").map((s) => s.trim()).filter(Boolean);
    const escribir = (tags) => { oculto.value = tags.join(","); };
    const pintar = () => {
      const sel = new Set(leer());
      $$(".chip", lista).forEach((c) => c.classList.toggle("sel", sel.has(c.dataset.tag)));
      // tags personalizados que no están como chip
      sel.forEach((t) => {
        if (!$(`.chip[data-tag="${CSS.escape(t)}"]`, lista)) agregarChip(t, true);
      });
    };
    const agregarChip = (tag, sel) => {
      const c = document.createElement("button");
      c.type = "button"; c.className = "chip" + (sel ? " sel" : ""); c.dataset.tag = tag; c.textContent = "#" + tag;
      lista.appendChild(c);
    };
    lista.addEventListener("click", (e) => {
      const c = e.target.closest(".chip");
      if (!c) return;
      const tags = leer();
      const i = tags.indexOf(c.dataset.tag);
      if (i >= 0) tags.splice(i, 1); else tags.push(c.dataset.tag);
      escribir(tags); pintar();
    });
    nuevo.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== ",") return;
      e.preventDefault();
      const t = nuevo.value.trim().toLowerCase().replace(/^#/, "").slice(0, 25);
      if (!t) return;
      const tags = leer();
      if (!tags.includes(t)) tags.push(t);
      escribir(tags); nuevo.value = ""; pintar();
    });
    pintar();
  });

  // ------------------------------------------------------------ razas sugeridas según especie
  const especie = $("select[name=especie]");
  const razas = $("#lista-razas");
  if (especie && razas && window.PAW_RAZAS) {
    const llenar = () => {
      razas.innerHTML = "";
      (window.PAW_RAZAS[especie.value] || []).forEach((r) => {
        const o = document.createElement("option"); o.value = r; razas.appendChild(o);
      });
    };
    especie.addEventListener("change", llenar);
    llenar();
  }

  // ------------------------------------------------------------ selector de ubicación (Leaflet)
  window.pawMapaSelector = function (idMapa, idLat, idLng, centro) {
    if (!window.L) return;
    const lat = document.getElementById(idLat), lng = document.getElementById(idLng);
    const tiene = lat.value && lng.value;
    const inicio = tiene ? [parseFloat(lat.value), parseFloat(lng.value)] : centro;
    const mapa = L.map(idMapa, { scrollWheelZoom: false }).setView(inicio, tiene ? 15 : 12);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "&copy; OpenStreetMap",
    }).addTo(mapa);
    let marca = tiene ? L.marker(inicio).addTo(mapa) : null;
    const fijar = (ll) => {
      lat.value = ll.lat.toFixed(5); lng.value = ll.lng.toFixed(5);
      if (marca) marca.setLatLng(ll); else marca = L.marker(ll).addTo(mapa);
    };
    mapa.on("click", (e) => fijar(e.latlng));
    const ubicar = document.querySelector(`[data-ubicar="${idMapa}"]`);
    if (ubicar) ubicar.addEventListener("click", () => {
      if (!navigator.geolocation) return toast("Tu navegador no permite obtener la ubicación.", "error");
      navigator.geolocation.getCurrentPosition(
        (pos) => { const ll = L.latLng(pos.coords.latitude, pos.coords.longitude); fijar(ll); mapa.setView(ll, 15); },
        () => toast("No pudimos obtener tu ubicación. Haz clic en el mapa.", "error"),
        { enableHighAccuracy: true, timeout: 8000 });
    });
    const limpiar = document.querySelector(`[data-limpiar="${idMapa}"]`);
    if (limpiar) limpiar.addEventListener("click", () => {
      lat.value = ""; lng.value = ""; if (marca) { mapa.removeLayer(marca); marca = null; }
    });
    setTimeout(() => mapa.invalidateSize(), 200);
    return mapa;
  };

  // ------------------------------------------------------------ Pawi (asistente)
  const pawiBoton = $("#pawi-boton");
  const pawiPanel = $("#pawi-panel");
  if (pawiBoton && pawiPanel) {
    const mensajes = $(".pawi-mensajes", pawiPanel);
    const form = $(".pawi-form", pawiPanel);
    const area = $("textarea", form);
    const enviar = $("button", form);
    const sugerencias = $(".pawi-sugerencias", pawiPanel);
    const CLAVE = "pawi-historial";
    let historial = [];
    let ocupado = false;

    try { historial = JSON.parse(sessionStorage.getItem(CLAVE) || "[]"); } catch (e) { historial = []; }
    const guardar = () => { try { sessionStorage.setItem(CLAVE, JSON.stringify(historial.slice(-20))); } catch (e) { /* sin almacenamiento */ } };

    const md = (texto) => {
      if (window.marked && window.DOMPurify) {
        return DOMPurify.sanitize(marked.parse(texto, { breaks: true }));
      }
      const div = document.createElement("div"); div.textContent = texto;
      return div.innerHTML.replace(/\n/g, "<br>");
    };
    const burbuja = (rol, texto) => {
      const d = document.createElement("div");
      d.className = "msg " + (rol === "user" ? "msg-usuario" : "msg-pawi");
      if (rol === "user") d.textContent = texto; else d.innerHTML = md(texto);
      mensajes.appendChild(d);
      mensajes.scrollTop = mensajes.scrollHeight;
      return d;
    };
    const pintarHistorial = () => {
      $$(".msg:not([data-fijo]), .msg-estado, .msg-accion", mensajes).forEach((n) => n.remove());
      historial.forEach((m) => burbuja(m.role, m.content));
      sugerencias.classList.toggle("oculto", historial.length > 0);
    };

    const abrir = () => {
      pawiPanel.classList.remove("oculto"); pawiBoton.classList.add("oculto");
      pintarHistorial(); setTimeout(() => area.focus(), 50);
    };
    const cerrar = () => { pawiPanel.classList.add("oculto"); pawiBoton.classList.remove("oculto"); };
    pawiBoton.addEventListener("click", abrir);
    $$("[data-abrir-pawi]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); abrir(); }));
    $("[data-cerrar-pawi]", pawiPanel).addEventListener("click", cerrar);
    $("[data-limpiar-pawi]", pawiPanel).addEventListener("click", () => { historial = []; guardar(); pintarHistorial(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pawiPanel.classList.contains("oculto")) cerrar(); });

    sugerencias.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (b) { area.value = b.textContent.trim(); preguntar(); }
    });
    area.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); preguntar(); }
    });
    area.addEventListener("input", () => { area.style.height = "auto"; area.style.height = Math.min(area.scrollHeight, 120) + "px"; });
    form.addEventListener("submit", (e) => { e.preventDefault(); preguntar(); });

    async function preguntar() {
      const texto = area.value.trim();
      if (!texto || ocupado) return;
      ocupado = true; enviar.disabled = true;
      sugerencias.classList.add("oculto");
      area.value = ""; area.style.height = "auto";
      burbuja("user", texto);
      const previo = historial.slice(-12);
      historial.push({ role: "user", content: texto });
      guardar();

      const estado = document.createElement("div");
      estado.className = "msg-estado";
      estado.innerHTML = '<span class="puntos-carga"><span></span> <span></span> <span></span></span> <span class="t">Pensando…</span>';
      mensajes.appendChild(estado);
      mensajes.scrollTop = mensajes.scrollHeight;

      let respuesta = "", nodo = null;
      try {
        const r = await fetch("/api/asistente", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mensaje: texto, historial: previo }),
        });
        if (r.status === 401) { location.href = "/login"; return; }
        if (r.status === 429) {
          // Límite de mensajes: se muestra el aviso, pero no entra al historial de la conversación
          const j = await r.json().catch(() => ({}));
          nodo = burbuja("assistant", j.detail || "Pawi necesita un respiro. Intenta en un momento.");
          return;
        }
        if (!r.ok || !r.body) throw new Error("Error " + r.status);
        const lector = r.body.getReader();
        const dec = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await lector.read();
          if (done) break;
          buffer += dec.decode(value, { stream: true });
          let i;
          while ((i = buffer.indexOf("\n")) >= 0) {
            const linea = buffer.slice(0, i).trim();
            buffer = buffer.slice(i + 1);
            if (!linea) continue;
            let ev;
            try { ev = JSON.parse(linea); } catch (e) { continue; }
            if (ev.tipo === "estado") {
              $(".t", estado).textContent = ev.texto;
              if (!estado.isConnected) mensajes.appendChild(estado);
            } else if (ev.tipo === "texto") {
              respuesta += ev.delta;
              if (!nodo) { estado.remove(); nodo = burbuja("assistant", ""); }
              nodo.innerHTML = md(respuesta);
              mensajes.scrollTop = mensajes.scrollHeight;
            } else if (ev.tipo === "accion") {
              const a = document.createElement("a");
              a.className = "msg-accion"; a.href = ev.enlace; a.textContent = "✅ " + ev.texto + " · Ver calendario";
              mensajes.insertBefore(a, estado.isConnected ? estado : null);
            } else if (ev.tipo === "error") {
              respuesta = respuesta || ev.texto;
              if (!nodo) { estado.remove(); nodo = burbuja("assistant", ""); }
              nodo.innerHTML = md(respuesta);
            }
          }
        }
      } catch (err) {
        respuesta = respuesta || "No pude conectarme. Revisa tu conexión e inténtalo otra vez.";
        if (!nodo) nodo = burbuja("assistant", respuesta);
      } finally {
        estado.remove();
        if (respuesta) { historial.push({ role: "assistant", content: respuesta }); guardar(); }
        ocupado = false; enviar.disabled = false; area.focus();
      }
    }
  }
})();
