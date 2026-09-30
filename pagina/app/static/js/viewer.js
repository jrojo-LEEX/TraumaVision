/* viewer.js — Visor de radiografías */
(function () {
  'use strict';

  var MIN = 0.05, MAX = 40;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var SVGNS = 'http://www.w3.org/2000/svg';

  function Viewer(root) {
    this.root = root;
    this.viewport = root.querySelector('[data-viewport]');
    this.img = root.querySelector('[data-stage-img]');
    this.base = root.querySelector('[data-stage-base]');
    this.capas = root.querySelectorAll('.stage-img');
    this.svg = root.querySelector('[data-boxlayer]');
    this.zoomOut = root.querySelector('[data-zoom-readout]');
    if (!this.viewport || !this.img) return;

    this.scale = 1; this.tx = 0; this.ty = 0;
    this.fitScale = 1;
    this.lastDrawScale = 0;
    this.showingOriginal = false;
    this.dragging = false;
    this.vector = false;
    this.hot = -1;
    this.pinned = -1;
    this.rects = [];
    this.br = 100; this.ct = 100;

    this.bind();

    var self = this;
    function listo() { self.fit(); self.armarVectores(); self.armarBarrido(); }
    if (this.img.complete && this.img.naturalWidth) listo();
    else this.img.addEventListener('load', listo, { once: true });
  }

  /* Cajas como SVG sobre la placa limpia (si falla, queda la imagen anotada) */
  Viewer.prototype.armarVectores = function () {
    var datos = this.leerCajas();
    if (!datos.length || !this.svg) return;
    var w = this.img.naturalWidth, h = this.img.naturalHeight;
    if (!w || !h) return;

    this.svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    this.svg.setAttribute('width', w);
    this.svg.setAttribute('height', h);
    this.svg.innerHTML = '';
    this.rects = [];

    var capaTrazos = document.createElementNS(SVGNS, 'g');
    var capaNumeros = document.createElementNS(SVGNS, 'g');

    var self = this;
    datos.forEach(function (b, i) {
      var g = document.createElementNS(SVGNS, 'g');
      g.setAttribute('class', 'bx' + (b.low ? ' bx-low' : '') + (b.neutral ? ' bx-neutral' : ''));
      g.setAttribute('data-bx', i);

      var r = document.createElementNS(SVGNS, 'rect');
      r.setAttribute('x', b.x1); r.setAttribute('y', b.y1);
      r.setAttribute('width', Math.max(1, b.x2 - b.x1));
      r.setAttribute('height', Math.max(1, b.y2 - b.y1));
      r.setAttribute('vector-effect', 'non-scaling-stroke');
      g.appendChild(r);

      var tag = document.createElementNS(SVGNS, 'g');
      tag.setAttribute('class', 'bx-tag' + (b.low ? ' bx-low' : '') + (b.neutral ? ' bx-neutral' : ''));
      tag.setAttribute('data-bx', i);
      var etiqueta = b.c.toFixed(2).replace('.', ',');
      var ancho = 12 + etiqueta.length * 7;
      var pill = document.createElementNS(SVGNS, 'rect');
      pill.setAttribute('x', 0); pill.setAttribute('y', -15);
      pill.setAttribute('width', ancho); pill.setAttribute('height', 15);
      pill.setAttribute('rx', 2);
      var t = document.createElementNS(SVGNS, 'text');
      t.setAttribute('x', ancho / 2); t.setAttribute('y', -4);
      t.setAttribute('text-anchor', 'middle');
      t.textContent = etiqueta;
      tag.appendChild(pill); tag.appendChild(t);

      function entra() { self.resaltar(i, false); }
      function sale()  { self.resaltar(-1, false); }
      g.addEventListener('pointerenter', entra);
      g.addEventListener('pointerleave', sale);
      tag.addEventListener('pointerenter', entra);
      tag.addEventListener('pointerleave', sale);

      capaTrazos.appendChild(g);
      capaNumeros.appendChild(tag);
      self.rects.push({ g: g, tag: tag, b: b });
    });

    self.svg.appendChild(capaTrazos);
    self.svg.appendChild(capaNumeros);

    this.svg.removeAttribute('hidden');
    this.vector = true;
    this.img.classList.add('is-off');
    this.root.classList.add('has-vectors');
    this.marcarEstado();
    this.cablearPanel();
    this.apply();
  };

  Viewer.prototype.host = function () {
    return document.querySelector('[data-find-host]');
  };

  /* Cajas del panel visible, marcadas bajo/sobre el umbral */
  Viewer.prototype.leerCajas = function () {
    var host = this.host();
    if (!host) return [];
    var crudo = host.getAttribute('data-boxes');
    if (!crudo) return [];
    if (host.hasAttribute('data-sin-corte')) {
      try {
        var todas = JSON.parse(crudo);
        if (!Array.isArray(todas)) return [];
        return todas.map(function (b) { b.low = false; b.neutral = true; return b; });
      } catch (_) { return []; }
    }
    var umbral = parseFloat(host.getAttribute('data-abnormal-threshold'));
    if (isNaN(umbral)) {
      console.error('[TraumaVision] falta data-abnormal-threshold en el panel: no se dibujan las cajas.');
      return [];
    }
    try {
      var arr = JSON.parse(crudo);
      if (!Array.isArray(arr)) return [];
      return arr.map(function (b) {
        b.low = b.c < umbral;
        return b;
      });
    } catch (_) { return []; }
  };

  /* Vínculo fila del panel <-> caja; se recablea al cambiar de imagen */
  Viewer.prototype.cablearPanel = function () {
    var self = this;

    if (this._panelAbort) this._panelAbort.abort();
    this._panelAbort = new AbortController();
    var señal = this._panelAbort.signal;

    var ambito = document.querySelector('[data-panel-idx]:not([hidden])') || this.host() || document;
    this.filas = Array.prototype.slice.call(ambito.querySelectorAll('[data-find]'));
    if (!this.filas.length) { this.filas = []; return; }

    this.filas.forEach(function (fila, i) {
      var op = { signal: señal };
      fila.addEventListener('pointerenter', function () { self.resaltar(i, false); }, op);
      fila.addEventListener('pointerleave', function () { self.resaltar(-1, false); }, op);
      fila.addEventListener('focus', function () { self.resaltar(i, false); }, op);
      fila.addEventListener('blur', function () { self.resaltar(-1, false); }, op);
      fila.addEventListener('click', function () { self.fijar(i === self.pinned ? -1 : i); }, op);
    });

    var hint = ambito.querySelector ? ambito.querySelector('[data-find-hint]') : null;
    if (hint) hint.hidden = false;
  };

  /* Resaltado pasajero; el fijado gana */
  Viewer.prototype.resaltar = function (i, desdeFijado) {
    if (!desdeFijado && this.pinned !== -1 && i === -1) i = this.pinned;
    if (i === this.hot) return;
    this.hot = i;
    this.svg && this.svg.classList.toggle('has-hot', i !== -1);
    this.rects.forEach(function (r, k) {
      r.g.classList.toggle('is-hot', k === i);
      r.tag.classList.toggle('is-hot', k === i);
    });
    (this.filas || []).forEach(function (f, k) {
      f.classList.toggle('is-hot', k === i);
    });
  };

  /* Fijar un hallazgo: resaltarlo, encuadrarlo y señalarlo con un anillo */
  Viewer.prototype.fijar = function (i) {
    this.pinned = i;
    clearTimeout(this._ping);
    (this.filas || []).forEach(function (f, k) {
      f.setAttribute('aria-pressed', k === i ? 'true' : 'false');
    });
    this.resaltar(i, true);
    if (i === -1 || !this.rects[i]) return;
    var viajo = this.acercarPlaca();
    this.enmarcar(this.rects[i].b);
    if (viajo) {
      var self = this;
      clearTimeout(this._ping);
      this._ping = setTimeout(function () { self.anillar(i); }, 260);
    } else {
      this.anillar(i);
    }
    if (this.filas && this.filas[i]) this.filas[i].focus({ preventScroll: true });
  };

  /* En pantallas angostas, trae la placa a la vista si quedó fuera */
  Viewer.prototype.acercarPlaca = function () {
    if (document.fullscreenElement) return false;
    if (typeof this.viewport.scrollIntoView !== 'function') return false;
    var r = this.viewport.getBoundingClientRect();
    var alto = window.innerHeight || document.documentElement.clientHeight;
    if (r.bottom > 8 && r.top < alto - 8) return false;
    this.viewport.scrollIntoView({
      behavior: reduce ? 'auto' : 'smooth',
      block: 'center'
    });
    return !reduce;
  };

  /* Anillo de localización (GSAP si está, si no WAAPI) */
  Viewer.prototype.anillar = function (i) {
    if (reduce) return;
    var r = this.rects[i];
    if (!r || !this.svg) return;
    var b = r.b;

    if (window.TVMotion && window.TVMotion.movimiento) {
      window.TVMotion.anillar(this.svg, b, this.scale);
      return;
    }

    var ring = document.createElementNS(SVGNS, 'rect');
    ring.setAttribute('class', 'bx-ping');
    ring.setAttribute('x', b.x1);
    ring.setAttribute('y', b.y1);
    ring.setAttribute('width', Math.max(1, b.x2 - b.x1));
    ring.setAttribute('height', Math.max(1, b.y2 - b.y1));
    ring.setAttribute('rx', 2);
    ring.setAttribute('vector-effect', 'non-scaling-stroke');
    if (typeof ring.animate !== 'function') return;
    this.svg.appendChild(ring);

    var lado = Math.max(Math.max(1, b.x2 - b.x1), Math.max(1, b.y2 - b.y1));
    var afuera = 22 / (this.scale || 1);
    var s0 = Math.min(2.2, 1 + (2 * afuera) / lado);
    var a = ring.animate([
      { transform: 'scale(' + s0.toFixed(3) + ')', opacity: 0, offset: 0,
        easing: 'cubic-bezier(.22,.61,.36,1)' },
      { transform: 'scale(' + (1 + (s0 - 1) * .28).toFixed(3) + ')', opacity: 1, offset: .44 },
      { transform: 'scale(1)', opacity: 1, offset: .62, easing: 'linear' },
      { transform: 'scale(1)', opacity: 0, offset: 1 }
    ], { duration: 340, easing: 'linear' });
    function limpiar() { if (ring.parentNode) ring.parentNode.removeChild(ring); }
    a.addEventListener('finish', limpiar);
    a.addEventListener('cancel', limpiar);
  };

  /* Traslado suave de la placa sin GSAP */
  Viewer.prototype.deslizar = function () {
    if (reduce) return;
    var self = this;
    clearTimeout(this._glide);
    this.root.classList.add('is-gliding');
    this._glide = setTimeout(function () {
      self.root.classList.remove('is-gliding');
      self._glide = null;
    }, 300);
  };

  Viewer.prototype.frenar = function () {
    if (window.TVMotion) window.TVMotion.frenar(this);
    if (!this._glide) return;
    clearTimeout(this._glide);
    this._glide = null;
    this.root.classList.remove('is-gliding');
  };

  Viewer.prototype.enmarcar = function (b) {
    var vw = this.viewport.clientWidth, vh = this.viewport.clientHeight;
    var cx = (b.x1 + b.x2) / 2, cy = (b.y1 + b.y2) / 2;
    var sx = cx * this.scale + this.tx, sy = cy * this.scale + this.ty;
    var w = (b.x2 - b.x1) * this.scale, h = (b.y2 - b.y1) * this.scale;
    var margen = 40;
    var dentro = sx - w / 2 > margen && sx + w / 2 < vw - margen &&
                 sy - h / 2 > margen && sy + h / 2 < vh - margen;
    if (dentro) return;

    var destino = { tx: vw / 2 - cx * this.scale, ty: vh / 2 - cy * this.scale };

    if (window.TVMotion && window.TVMotion.movimiento) {
      var self = this;
      window.TVMotion.viajar(this, destino, function () { self.apply(); });
      return;
    }

    this.tx = destino.tx;
    this.ty = destino.ty;
    this.deslizar();
    this.apply();
  };

  Viewer.prototype.siguienteHallazgo = function (paso) {
    if (!this.rects.length) return;
    var i = this.pinned === -1
      ? (paso > 0 ? 0 : this.rects.length - 1)
      : (this.pinned + paso + this.rects.length) % this.rects.length;
    this.fijar(i);
  };

  /* Barrido de apertura: una pasada por imagen */
  Viewer.prototype.armarBarrido = function () {
    if (this._barrido) return;
    this._barrido = true;
    if (reduce) return;
    if (!this.base) return;
    if (document.visibilityState === 'hidden') return;
    var self = this;
    if (this.base.complete && this.base.naturalWidth) this.barrer();
    else this.base.addEventListener('load', function () { self.barrer(); }, { once: true });
  };

  Viewer.prototype.barrer = function () {
    var self = this;

    if (window.TVMotion && window.TVMotion.movimiento) {
      var tl = window.TVMotion.revelar({
        viewport: this.viewport, img: this.img, svg: this.svg,
        capa: this.vector ? this.svg : this.img,
        rects: this.rects, vector: this.vector,
        scale: this.scale, ty: this.ty
      });
      if (tl) {
        var eventos = ['pointerdown', 'wheel', 'keydown'];
        var soltar = function () {
          eventos.forEach(function (ev) { self.viewport.removeEventListener(ev, cortar); });
        };
        var cortar = function () { tl.progress(1); soltar(); };
        eventos.forEach(function (ev) {
          self.viewport.addEventListener(ev, cortar, { passive: true });
        });
        if (tl.then) tl.then(soltar);
        return;
      }
    }

    if (typeof this.img.animate !== 'function') return;
    var vr = this.viewport.getBoundingClientRect();
    var ir = this.img.getBoundingClientRect();
    if (!ir.height || !ir.width) return;

    var capa = this.vector ? this.svg : this.img;
    if (!capa || typeof capa.animate !== 'function') return;

    var ALTO_BANDA = 78;
    var linea = document.createElement('span');
    linea.className = 'scanline';
    linea.style.top = (ir.top - vr.top - ALTO_BANDA) + 'px';
    linea.style.left = (ir.left - vr.left) + 'px';
    linea.style.width = ir.width + 'px';
    this.viewport.appendChild(linea);

    var D = 620, E = 'cubic-bezier(.35,0,.25,1)';
    var recorte = capa.animate(
      [{ clipPath: 'inset(0 0 100% 0)' }, { clipPath: 'inset(0 0 0 0)' }],
      { duration: D, easing: E });
    var pasada = linea.animate([
      { transform: 'translateY(0px)', opacity: 0, offset: 0 },
      { opacity: 1, offset: .05 },
      { opacity: 1, offset: .82 },
      { transform: 'translateY(' + ir.height + 'px)', opacity: 0, offset: 1 }
    ], { duration: D, easing: E });

    var eventos = ['pointerdown', 'wheel', 'keydown'];
    function terminar() {
      try { recorte.finish(); pasada.finish(); } catch (_) {}
      if (linea.parentNode) linea.parentNode.removeChild(linea);
      eventos.forEach(function (ev) { self.viewport.removeEventListener(ev, terminar); });
    }
    pasada.addEventListener('finish', terminar);
    eventos.forEach(function (ev) {
      self.viewport.addEventListener(ev, terminar, { passive: true });
    });
  };

  /* Aplica zoom y desplazamiento; reubica los números para que no se pisen */
  Viewer.prototype.apply = function () {
    var t = 'translate(' + this.tx + 'px,' + this.ty + 'px) scale(' + this.scale + ')';
    for (var i = 0; i < this.capas.length; i++) this.capas[i].style.transform = t;
    if (this.svg) this.svg.style.transform = t;
    if (this.rects.length && this.scale !== this.lastDrawScale) {
      this.lastDrawScale = this.scale;
      var k = 1 / this.scale;
      var ALTO = 17, ANCHO = 16;
      var puestos = [];
      for (var j = 0; j < this.rects.length; j++) {
        var b = this.rects[j].b;
        var piso = 0;
        for (var intento = 0; intento <= puestos.length; intento++) {
          var libre = true;
          for (var q = 0; q < puestos.length; q++) {
            if (puestos[q].piso === piso &&
                Math.abs(puestos[q].x - b.x1) < ANCHO * k &&
                Math.abs(puestos[q].y - b.y1) < ALTO * k) { libre = false; break; }
          }
          if (libre) break;
          piso++;
        }
        puestos.push({ x: b.x1, y: b.y1, piso: piso });
        this.rects[j].tag.setAttribute(
          'transform', 'translate(' + b.x1 + ',' + b.y1 + ') scale(' + k + ')' +
          (piso ? ' translate(0,' + (-piso * ALTO) + ')' : ''));
      }
    }
    if (this.comparing) this.recortarCortina();
    if (this.zoomOut) this.zoomOut.textContent = Math.round(this.scale * 100) + '%';
  };

  var AIRE = 20;

  /* Zoom */
  Viewer.prototype.fit = function () {
    var vw = this.viewport.clientWidth, vh = this.viewport.clientHeight;
    var iw = this.img.naturalWidth, ih = this.img.naturalHeight;
    if (!iw || !ih || !vw || !vh) return;
    var m = Math.min(AIRE, vw * 0.06, vh * 0.06);
    var s = Math.min((vw - m * 2) / iw, (vh - m * 2) / ih);
    this.fitScale = s;
    this.scale = s;
    this.tx = (vw - iw * s) / 2;
    this.ty = (vh - ih * s) / 2;
    this.apply();
  };

  Viewer.prototype.actual = function () {
    var vw = this.viewport.clientWidth, vh = this.viewport.clientHeight;
    var iw = this.img.naturalWidth, ih = this.img.naturalHeight;
    this.scale = 1;
    this.tx = (vw - iw) / 2;
    this.ty = (vh - ih) / 2;
    this.apply();
  };

  Viewer.prototype.zoomAt = function (cx, cy, factor) {
    var r = this.viewport.getBoundingClientRect();
    var px = cx - r.left, py = cy - r.top;
    var next = Math.min(MAX, Math.max(MIN, this.scale * factor));
    if (next === this.scale) return;
    var k = next / this.scale;
    this.tx = px - (px - this.tx) * k;
    this.ty = py - (py - this.ty) * k;
    this.scale = next;
    this.apply();
  };

  Viewer.prototype.zoomCenter = function (factor) {
    var r = this.viewport.getBoundingClientRect();
    this.zoomAt(r.left + r.width / 2, r.top + r.height / 2, factor);
  };

  /* Marcas sí / no */
  Viewer.prototype.toggleOriginal = function (btn) {
    this.showingOriginal = !this.showingOriginal;
    if (this.vector) {
      this.svg.classList.toggle('is-off', this.showingOriginal);
    } else if (this.base && this.base.complete && this.base.naturalWidth) {
      this.img.style.visibility = this.showingOriginal ? 'hidden' : '';
    } else {
      var orig = this.img.dataset.original, annot = this.img.dataset.annotated;
      if (!orig || !annot) return;
      this.img.src = this.showingOriginal ? orig : annot;
    }
    this.sincronizarBotonOriginal();
    this.marcarEstado();
  };

  Viewer.prototype.sincronizarBotonOriginal = function () {
    var btn = this.root.querySelector('[data-act="original"]');
    if (!btn) return;
    btn.setAttribute('aria-pressed', this.showingOriginal ? 'true' : 'false');
    btn.title = this.showingOriginal
      ? 'Mostrar las marcas del sistema (O)'
      : 'Ocultar las marcas del sistema (O)';
  };

  Viewer.prototype.marcarEstado = function () {
    var tag = this.root.querySelector('[data-img-state]');
    if (!tag) return;
    if (this.showingOriginal) tag.textContent = this.vector ? 'SIN MARCAS' : 'ORIGINAL';
    else tag.textContent = this.vector ? 'MARCAS' : 'ANOTADA';
  };

  /* Inversión de grises */
  Viewer.prototype.toggleInvert = function () {
    var on = this.root.classList.toggle('is-inverted');
    var btn = this.root.querySelector('[data-act="invert"]');
    if (btn) btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  };

  /* Cortina de comparación */
  Viewer.prototype.toggleCompare = function (btn) {
    this.comparing = !this.comparing;
    if (btn) btn.setAttribute('aria-pressed', this.comparing ? 'true' : 'false');
    var self = this;
    clearTimeout(this._wipe);

    var cerrar = function () {
      self.root.classList.remove('is-wiping');
      self.root.classList.remove('is-comparing');
      if (self.curtain) self.curtain.hidden = true;
      self.viewport.style.removeProperty('--corte');
      self.viewport.style.removeProperty('--clip');
    };

    if (this.comparing) {
      if (!this.curtain) this.crearCortina();
      this.curtain.hidden = false;
      this.root.classList.add('is-comparing');
      if (reduce) { this.root.classList.remove('is-wiping'); this.setCorte(this.corte || 50); return; }
      this.root.classList.remove('is-wiping');
      this.viewport.style.setProperty('--corte', '0%');
      this.viewport.style.setProperty('--clip', '0%');
      void this.viewport.offsetWidth;
      this.root.classList.add('is-wiping');
      this.setCorte(this.corte || 50);
      this._wipe = setTimeout(function () {
        self.root.classList.remove('is-wiping');
      }, 320);
      return;
    }

    if (reduce || !this.curtain) { cerrar(); return; }
    this.root.classList.add('is-wiping');
    this.viewport.style.setProperty('--corte', '0%');
    this.viewport.style.setProperty('--clip', '0%');
    this._wipe = setTimeout(cerrar, 300);
  };

  Viewer.prototype.crearCortina = function () {
    var self = this;
    var el = document.createElement('div');
    el.className = 'curtain';
    el.setAttribute('role', 'slider');
    el.setAttribute('tabindex', '0');
    el.setAttribute('aria-label', 'Cortina de comparación: sin marcas a la izquierda, con marcas a la derecha');
    el.setAttribute('aria-valuemin', '0');
    el.setAttribute('aria-valuemax', '100');
    el.innerHTML = '<span class="curtain-grip" aria-hidden="true"></span>';
    this.viewport.appendChild(el);
    this.curtain = el;

    function mover(e) {
      var r = self.viewport.getBoundingClientRect();
      self.setCorte(((e.clientX - r.left) / r.width) * 100);
    }
    el.addEventListener('pointerdown', function (e) {
      e.stopPropagation();
      el.setPointerCapture(e.pointerId);
      self.arrastrandoCortina = true;
      clearTimeout(self._wipe);
      self.root.classList.remove('is-wiping');
      el.classList.add('is-grabbed');
    });
    el.addEventListener('pointermove', function (e) {
      if (!self.arrastrandoCortina) return;
      e.stopPropagation();
      mover(e);
    });
    function soltar(e) {
      if (!self.arrastrandoCortina) return;
      self.arrastrandoCortina = false;
      el.classList.remove('is-grabbed');
      try { el.releasePointerCapture(e.pointerId); } catch (_) {}
    }
    el.addEventListener('pointerup', soltar);
    el.addEventListener('pointercancel', soltar);
    el.addEventListener('keydown', function (e) {
      var d = e.key === 'ArrowLeft' ? -4 : (e.key === 'ArrowRight' ? 4 : 0);
      if (!d) return;
      e.preventDefault(); e.stopPropagation();
      self.setCorte((self.corte || 50) + d);
    });
  };

  Viewer.prototype.setCorte = function (pct) {
    pct = Math.min(100, Math.max(0, pct));
    this.corte = pct;
    this.viewport.style.setProperty('--corte', pct + '%');
    if (this.curtain) this.curtain.setAttribute('aria-valuenow', Math.round(pct));
    this.recortarCortina();
  };

  Viewer.prototype.recortarCortina = function () {
    if (!this.comparing) return;
    var iw = this.img.naturalWidth;
    if (!iw) return;
    var xPantalla = (this.corte / 100) * this.viewport.clientWidth;
    var xImagen = (xPantalla - this.tx) / this.scale;
    var frac = Math.min(100, Math.max(0, (xImagen / iw) * 100));
    this.viewport.style.setProperty('--clip', frac + '%');
  };

  /* Ventana: brillo y contraste */
  Viewer.prototype.setVentana = function (br, ct) {
    if (br != null) this.br = br;
    if (ct != null) this.ct = ct;
    this.root.style.setProperty('--img-br', this.br / 100);
    this.root.style.setProperty('--img-ct', this.ct / 100);
    var self = this;
    ['br', 'ct'].forEach(function (k) {
      var out = self.root.querySelector('[data-out="' + k + '"]');
      var inp = self.root.querySelector('[data-win="' + k + '"]');
      var v = k === 'br' ? self.br : self.ct;
      if (out) out.textContent = Math.round(v) + '%';
      if (inp && Number(inp.value) !== v) inp.value = v;
    });
    var btn = this.root.querySelector('[data-act="window"]');
    var tocado = this.br !== 100 || this.ct !== 100;
    if (btn) btn.setAttribute('aria-pressed', tocado ? 'true' : 'false');
  };

  Viewer.prototype.togglePanelVentana = function (forzar) {
    var panel = this.root.querySelector('[data-tool-panel]');
    var btn = this.root.querySelector('[data-act="window"]');
    if (!panel) return;
    var abrir = forzar != null ? forzar : panel.hidden;
    panel.hidden = !abrir;
    if (btn) btn.setAttribute('aria-expanded', abrir ? 'true' : 'false');
  };

  /* Cambiar de imagen dentro de un estudio */
  Viewer.prototype.setSource = function (annotated, original, meta) {
    this.img.dataset.annotated = annotated;
    this.img.dataset.original = original;
    this.showingOriginal = false;
    this.img.style.visibility = '';
    this.img.classList.remove('is-off');
    this.img.src = annotated;
    if (this.base) this.base.src = original;
    if (this.svg) {
      this.svg.setAttribute('hidden', '');
      this.svg.innerHTML = '';
      this.svg.classList.remove('is-off');
    }
    this.vector = false; this.rects = []; this.hot = -1; this.pinned = -1;
    this.lastDrawScale = 0;
    this.root.classList.remove('has-vectors');

    document.querySelectorAll('[data-find][aria-pressed="true"]').forEach(function (f) {
      f.setAttribute('aria-pressed', 'false');
      f.classList.remove('is-hot');
    });

    this.sincronizarBotonOriginal();
    this.marcarEstado();
    var self = this;
    this.img.addEventListener('load', function once() {
      self.img.removeEventListener('load', once);
      self.fit();
      self.armarVectores();
      self._barrido = false;
      self.armarBarrido();
      if (window.TVMotion) {
        var panel = document.querySelector('[data-panel-idx]:not([hidden])')
                 || document.querySelector('[data-find-host]');
        window.TVMotion.encenderPanel(panel);
      }
    });
    if (meta) {
      Object.keys(meta).forEach(function (k) {
        self.root.querySelectorAll('[data-ov="' + k + '"]').forEach(function (el) {
          el.textContent = meta[k];
        });
      });
    }
  };

  /* Ratón, botones de la barra y teclado */
  Viewer.prototype.bind = function () {
    var self = this;

    this.viewport.addEventListener('wheel', function (e) {
      e.preventDefault();
      self.frenar();
      self.zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.12 : 1 / 1.12);
    }, { passive: false });

    this.viewport.addEventListener('pointerdown', function (e) {
      self.frenar();
      if (e.button !== 0) return;
      if (self.arrastrandoCortina) return;
      self.dragging = true;
      self.lastX = e.clientX; self.lastY = e.clientY;
      self.viewport.classList.add('is-panning');
      self.viewport.setPointerCapture(e.pointerId);
    });
    this.viewport.addEventListener('pointermove', function (e) {
      if (!self.dragging) return;
      self.tx += e.clientX - self.lastX;
      self.ty += e.clientY - self.lastY;
      self.lastX = e.clientX; self.lastY = e.clientY;
      self.apply();
    });
    function endDrag(e) {
      if (!self.dragging) return;
      self.dragging = false;
      self.viewport.classList.remove('is-panning');
      try { self.viewport.releasePointerCapture(e.pointerId); } catch (_) {}
    }
    this.viewport.addEventListener('pointerup', endDrag);
    this.viewport.addEventListener('pointercancel', endDrag);

    this.viewport.addEventListener('dblclick', function (e) {
      e.preventDefault();
      if (Math.abs(self.scale - self.fitScale) < 0.001) self.actual();
      else self.fit();
    });

    this.root.querySelectorAll('[data-act]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var a = btn.dataset.act;
        if (a === 'in')        self.zoomCenter(1.3);
        else if (a === 'out')  self.zoomCenter(1 / 1.3);
        else if (a === 'fit')  self.fit();
        else if (a === '1:1')  self.actual();
        else if (a === 'original') self.toggleOriginal(btn);
        else if (a === 'compare')  self.toggleCompare(btn);
        else if (a === 'window')   self.togglePanelVentana();
        else if (a === 'invert')   self.toggleInvert();
        else if (a === 'full') self.fullscreen(btn);
      });
    });

    this.root.querySelectorAll('[data-win]').forEach(function (inp) {
      inp.addEventListener('input', function () {
        var v = Number(inp.value);
        if (inp.dataset.win === 'br') self.setVentana(v, null);
        else self.setVentana(null, v);
      });
    });
    var reset = this.root.querySelector('[data-win-reset]');
    if (reset) reset.addEventListener('click', function () { self.setVentana(100, 100); });

    document.addEventListener('pointerdown', function (e) {
      var pop = self.root.querySelector('[data-tools]');
      if (pop && !pop.contains(e.target)) self.togglePanelVentana(false);
    });

    function esCampo(el) {
      if (!el) return false;
      var t = (el.tagName || '').toLowerCase();
      return t === 'input' || t === 'textarea' || t === 'select' || el.isContentEditable;
    }

    document.addEventListener('keydown', function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (esCampo(e.target)) return;
      var enVisor = self.viewport.contains(e.target) || e.target === self.viewport;
      var step = 40;
      var k = e.key;

      if (k === '+' || k === '=') self.zoomCenter(1.3);
      else if (k === '-' || k === '_') self.zoomCenter(1 / 1.3);
      else if (k === '0') self.fit();
      else if (k === '1') self.actual();
      else if (k === 'o' || k === 'O') self.toggleOriginal(self.root.querySelector('[data-act="original"]'));
      else if (k === 'c' || k === 'C') self.toggleCompare(self.root.querySelector('[data-act="compare"]'));
      else if (k === 'w' || k === 'W') self.togglePanelVentana();
      else if (k === 'r' || k === 'R') self.setVentana(100, 100);
      else if (k === 'f' || k === 'F') self.fullscreen(self.root.querySelector('[data-act="full"]'));
      else if (k === 'i' || k === 'I') self.toggleInvert();
      else if (k === 'n' || k === 'N') self.siguienteHallazgo(1);
      else if (k === 'p' || k === 'P') self.siguienteHallazgo(-1);
      else if (k === 'Escape') { if (self.pinned === -1) return; self.fijar(-1); }
      else if (enVisor && k === 'ArrowLeft')  { self.frenar(); self.tx += step; self.apply(); }
      else if (enVisor && k === 'ArrowRight') { self.frenar(); self.tx -= step; self.apply(); }
      else if (enVisor && k === 'ArrowUp')    { self.frenar(); self.ty += step; self.apply(); }
      else if (enVisor && k === 'ArrowDown')  { self.frenar(); self.ty -= step; self.apply(); }
      else return;
      e.preventDefault();
    });

    window.addEventListener('resize', function () {
      if (self._rt) clearTimeout(self._rt);
      self._rt = setTimeout(function () { self.fit(); }, 120);
    });

    document.addEventListener('fullscreenchange', function () {
      setTimeout(function () { self.fit(); }, 60);
    });
  };

  Viewer.prototype.fullscreen = function (btn) {
    var self = this;
    if (!document.fullscreenElement) {
      if (this.root.requestFullscreen) {
        this.root.requestFullscreen().then(function () {
          if (btn) btn.setAttribute('aria-pressed', 'true');
          setTimeout(function () { self.fit(); }, 60);
        }).catch(function () {});
      }
    } else {
      document.exitFullscreen().then(function () {
        if (btn) btn.setAttribute('aria-pressed', 'false');
      }).catch(function () {});
    }
  };

  /* Tira de miniaturas del estudio */
  function bindFilmstrip(viewer) {
    var strip = document.querySelector('[data-filmstrip]');
    if (!strip || !viewer) return;
    strip.querySelectorAll('.frame').forEach(function (frame) {
      frame.addEventListener('click', function () {
        strip.querySelectorAll('.frame').forEach(function (f) {
          f.setAttribute('aria-current', 'false');
        });
        frame.setAttribute('aria-current', 'true');
        var host = document.querySelector('[data-find-host]');
        if (host && frame.dataset.boxes) host.setAttribute('data-boxes', frame.dataset.boxes);
        document.querySelectorAll('[data-panel-idx]').forEach(function (p) {
          p.hidden = p.dataset.panelIdx !== frame.dataset.idx;
        });
        viewer.setSource(frame.dataset.annotated, frame.dataset.original, {
          idx: frame.dataset.idx,
          name: frame.dataset.name
        });
      });
    });
  }

  window.addEventListener('DOMContentLoaded', function () {
    var root = document.querySelector('[data-viewer]');
    if (!root) return;
    var v = new Viewer(root);
    bindFilmstrip(v);
  });
})();
