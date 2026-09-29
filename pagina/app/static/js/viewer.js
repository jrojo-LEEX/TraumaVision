/*
 * viewer.js — Visor de radiografías.
 *
 * Verificar al modelo mirando la placa ES la tarea del radiólogo, así que la
 * imagen tiene que poder mirarse de verdad: zoom, desplazamiento, 1:1,
 * pantalla completa, inversión de grises y ventana (brillo y contraste).
 *
 * ── Las cajas, como vectores ────────────────────────────────────────────
 * El servidor devuelve un PNG con las cajas QUEMADAS encima, incluida una
 * etiqueta roja "Fractura 76%" sobre la anatomía. Eso hace dos cosas malas:
 * ensucia lo único que el médico vino a mirar, y deja las cajas inertes —
 * no se puede señalar una desde el panel.
 *
 * Cuando este archivo corre, las mismas cajas (las que ya estaban guardadas
 * en `detection_boxes`, no una detección nueva) se redibujan como SVG sobre
 * la placa LIMPIA, y la capa quemada se apaga. Así el panel y la placa
 * quedan ligados en los dos sentidos.
 *
 * Degradación: si el JS no corre, si no hay cajas en el dataset o si algo
 * falla, la capa quemada del servidor queda visible tal cual. Nunca se
 * muestra una placa sin marcas creyendo que está marcada.
 */
(function () {
  'use strict';

  var MIN = 0.05, MAX = 40;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var SVGNS = 'http://www.w3.org/2000/svg';

  function Viewer(root) {
    this.root = root;
    this.viewport = root.querySelector('[data-viewport]');
    this.img = root.querySelector('[data-stage-img]');
    /* Capa de abajo: la placa sin marcar. Las dos imágenes tienen el mismo
       tamaño natural (el anotado se dibuja SOBRE el original), así que
       comparten transform y quedan pixel a pixel encima. */
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
    this.vector = false;      /* ¿las cajas se están dibujando como SVG? */
    this.hot = -1;            /* hallazgo resaltado, -1 = ninguno */
    this.pinned = -1;         /* hallazgo fijado con click */
    this.boxes = [];
    this.rects = [];
    this.br = 100; this.ct = 100;

    this.bind();

    var self = this;
    function listo() { self.fit(); self.armarVectores(); self.armarBarrido(); }
    if (this.img.complete && this.img.naturalWidth) listo();
    else this.img.addEventListener('load', listo, { once: true });
  }

  /* ── Cajas vectoriales ───────────────────────────────────────────────
     Las coordenadas vienen en el espacio de píxeles de la imagen, así que
     el SVG se dimensiona al tamaño natural y comparte el mismo transform
     que las dos capas de imagen. `non-scaling-stroke` mantiene el trazo en
     ~1,5 px de pantalla a cualquier zoom: una caja de diagnóstico no debe
     engordar cuando el médico se acerca. */
  Viewer.prototype.armarVectores = function () {
    var datos = this.leerCajas();
    if (!datos.length || !this.svg) return;
    var w = this.img.naturalWidth, h = this.img.naturalHeight;
    if (!w || !h) return;

    this.boxes = datos;
    this.svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    this.svg.setAttribute('width', w);
    this.svg.setAttribute('height', h);
    this.svg.innerHTML = '';
    this.rects = [];

    /* DOS capas, no una por caja.
       Antes cada caja era un grupo [rect, número] y los grupos se apilaban
       en orden de dato. En SVG pinta último el que va último, así que una
       caja posterior tapaba el NÚMERO de una anterior cuando se solapaban
       —y se solapan seguido: son detecciones sobre la misma muñeca—. En el
       estudio 517 la caja 4 le pasaba por encima a la etiqueta de la 2.
       Con los números en una capa propia, dibujada después de TODOS los
       trazos, ninguna caja puede tapar un número. El orden entre números
       sigue siendo el de dato, pero son 15x15 px y no se pisan como los
       rectángulos. */
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

      /* El número de la caja es el mismo que el de la fila del panel. Va
         en su propio grupo porque se contra-escala: el trazo puede ser
         invariante al zoom, el texto no lo es solo.

         Lleva `bx-low` propio porque ya no cuelga del grupo de la caja: el
         color del número lo decide su propia clase, no la del ancestro. */
      var tag = document.createElementNS(SVGNS, 'g');
      tag.setAttribute('class', 'bx-tag' + (b.low ? ' bx-low' : '') + (b.neutral ? ' bx-neutral' : ''));
      tag.setAttribute('data-bx', i);
      /* La clave es `c`, no `confidence`: así la serializa `_boxes_json`
         (analysis_routes.py) y así la lee el filtro de `low` de más abajo.
         Leyendo `b.confidence` el valor era `undefined` y toda caja se
         rotulaba «NaN%» sobre la placa. */
      /* Escala 0–1, sin «%»: la misma que la lista de hallazgos. Con el
         signo al lado el score se lee como riesgo, y no es una probabilidad
         de fractura. */
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
      /* El número también responde: es parte de la misma caja para el ojo,
         tiene que serlo para el puntero. */
      tag.addEventListener('pointerenter', entra);
      tag.addEventListener('pointerleave', sale);

      capaTrazos.appendChild(g);
      capaNumeros.appendChild(tag);
      self.rects.push({ g: g, tag: tag, b: b });
    });

    self.svg.appendChild(capaTrazos);
    self.svg.appendChild(capaNumeros);

    /* OJO: SVGElement no hereda HTMLElement.hidden. Asignar `.hidden`
       crea una propiedad JS y NO toca el atributo, así que la regla
       [hidden]{display:none!important} seguía ocultando la capa. */
    this.svg.removeAttribute('hidden');
    this.vector = true;
    /* Recién ahora se apaga la capa quemada: si algo de lo de arriba
       hubiera fallado, la placa anotada seguiría a la vista. */
    this.img.classList.add('is-off');
    this.root.classList.add('has-vectors');
    this.marcarEstado();
    this.cablearPanel();
    this.apply();
  };

  /* OJO con el selector: los cuadros de la tira de miniaturas también
     llevan `data-boxes` (cada uno con las suyas), y en el DOM van ANTES que
     el panel. Un `querySelector('[data-boxes]')` pelado devolvía una
     miniatura, no el panel. El host se marca aparte. */
  Viewer.prototype.host = function () {
    return document.querySelector('[data-find-host]');
  };

  Viewer.prototype.leerCajas = function () {
    var host = this.host();
    if (!host) return [];
    var crudo = host.getAttribute('data-boxes');
    if (!crudo) return [];
    /* El umbral de anormalidad llega del servidor (ABNORMAL_THRESHOLD, vía
       `data-abnormal-threshold`). Acá había un valor de reserva escrito a
       mano: si el atributo faltaba, el visor pintaba las cajas contra un
       umbral que podía no ser el del sistema, en silencio. Sin el dato no
       se adivina: se avisa y no se clasifica ninguna caja. */
    /* Resultado de un modelo que no es el vigente: el corte del vigente no
       le aplica, así que ninguna caja se pinta «sobre» ni «bajo» el corte.
       Van todas en el color neutro (`bx-neutral`). */
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

  /* ── El vínculo panel ↔ placa ────────────────────────────────────────
     Las filas del panel ya son <button>, así que el Tab y el Enter salen
     gratis. Acá sólo se atan hover, foco y click. */
  Viewer.prototype.cablearPanel = function () {
    var self = this;

    /* OJO: acá se vuelve a pasar en CADA cambio de imagen, porque
       `armarVectores` llama a este método y `setSource` llama a
       `armarVectores`. Sin soltar los listeners de la pasada anterior se
       acumulaban sobre las MISMAS filas: al volver a una imagen ya visitada,
       un click disparaba `fijar` dos veces y el segundo —viendo que ahora
       `i === self.pinned`— soltaba lo que el primero acababa de fijar. El pin
       quedaba muerto en todo estudio multi-imagen, que es justo donde hace
       falta.

       El AbortController corta de raíz los de la pasada anterior, así que
       siempre hay exactamente un juego de listeners vivo. */
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

  /* Resalta sin fijar. El resaltado fijado gana sobre el pasajero. */
  Viewer.prototype.resaltar = function (i, desdeFijado) {
    if (!desdeFijado && this.pinned !== -1 && i === -1) i = this.pinned;
    if (i === this.hot) return;
    this.hot = i;
    this.svg && this.svg.classList.toggle('has-hot', i !== -1);
    /* El número vive en otra capa que el trazo (ver armarVectores), así que
       el estado se marca en los dos: si no, al resaltar una caja los números
       de las demás se quedaban a full opacidad sobre las cajas apagadas. */
    this.rects.forEach(function (r, k) {
      r.g.classList.toggle('is-hot', k === i);
      r.tag.classList.toggle('is-hot', k === i);
    });
    (this.filas || []).forEach(function (f, k) {
      f.classList.toggle('is-hot', k === i);
    });
  };

  /* Fija un hallazgo: lo resalta y lo trae al centro de la ventana. Si ya
     se ve entero al zoom actual, no se toca la vista — mover la placa por
     debajo de un médico que está mirando es peor que no hacer nada. */
  Viewer.prototype.fijar = function (i) {
    this.pinned = i;
    /* Un anillo en cola de un hallazgo anterior no debe aparecer sobre el
       nuevo: cada `fijar` cancela el que esté esperando. */
    clearTimeout(this._ping);
    (this.filas || []).forEach(function (f, k) {
      f.setAttribute('aria-pressed', k === i ? 'true' : 'false');
    });
    this.resaltar(i, true);
    if (i === -1 || !this.rects[i]) return;
    var viajo = this.acercarPlaca();
    this.enmarcar(this.rects[i].b);
    /* Si hubo que traer la placa a la pantalla, el anillo espera a que
       llegue: disparado a la vez, se apagaba antes de que la placa
       apareciera y el localizador no localizaba nada. */
    if (viajo) {
      var self = this;
      clearTimeout(this._ping);
      this._ping = setTimeout(function () { self.anillar(i); }, 260);
    } else {
      this.anillar(i);
    }
    if (this.filas && this.filas[i]) this.filas[i].focus({ preventScroll: true });
  };

  /* ── La placa a la vista ─────────────────────────────────────────────
     En una pantalla angosta el visor no es una grilla al lado del panel:
     la placa va arriba y la lista de hallazgos abajo. Leyendo la lista, la
     placa queda ENTERA fuera de pantalla y tocar un hallazgo no produce
     nada visible — ni el resaltado, ni el encuadre, ni el anillo.

     La condición es deliberadamente estricta: sólo se mueve la página si
     de la placa no se ve NI UN PÍXEL, o sea si el toque no tuvo ningún
     efecto observable. Si asoma aunque sea un pedazo, no se toca el
     scroll: correr la página debajo de un médico que está mirando es peor
     que no hacer nada. En escritorio esto nunca se dispara. */
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

  /* ── El anillo de localización ───────────────────────────────────────
     Fijar un hallazgo es un pedido explícito: "llevame ahí". El resaltado
     ya contesta CUÁL, pero el ojo estaba en el panel y la caja puede estar
     en cualquier punto de la placa — y encima la placa se está moviendo.
     El anillo se cierra sobre la caja como una retícula y se apaga ahí
     mismo: termina donde el ojo tiene que quedar. Converge, no irradia: un
     anillo que se expande parece que la caja emite algo; uno que se cierra
     es el instrumento apuntando. Una sola pasada, y se borra del DOM. */
  Viewer.prototype.anillar = function (i) {
    if (reduce) return;
    var r = this.rects[i];
    if (!r || !this.svg) return;
    var b = r.b;

    /* Con capa de movimiento, el anillo lo dibuja motion.js. Lo que se gana
       no es el gesto —es el mismo, con el mismo argumento— sino el
       `overwrite`: recorriendo hallazgos con N/P a ritmo de teclado, el
       anillo anterior se mata en el acto en vez de superponerse con el
       nuevo. Acá abajo queda la ruta WAAPI, viva, para cuando GSAP no
       cargó. */
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

    /* La apertura del anillo se mide en PÍXELES DE PANTALLA, no en una
       fracción de la caja. Con una escala fija, a zoom 1:1 el anillo era
       proporcionado y al 220 % se convertía en un rectángulo azul enorme
       cruzando media placa: dejaba de leerse como una retícula cerrándose
       y pasaba a leerse como algo que apareció. 22 px afuera es un anillo
       reconocible con cualquier caja y a cualquier zoom. */
    var lado = Math.max(Math.max(1, b.x2 - b.x1), Math.max(1, b.y2 - b.y1));
    var afuera = 22 / (this.scale || 1);
    var s0 = Math.min(2.2, 1 + (2 * afuera) / lado);
    /* El reparto del tiempo se hace con `offset` y la curva va en el primer
       tramo, no en el efecto entero: con `--ease` global (que es un
       ease-out muy marcado) el anillo se cerraba en 60 ms sobre la caja y
       lo único que quedaba visible eran 280 ms de un borde apagándose —
       o sea, nada. Ahora el cierre ocupa los primeros 150 ms y se VE
       cerrarse, que es el gesto que dice dónde mirar. */
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

  /* ── El viaje de la placa ────────────────────────────────────────────
     Enciende la transición de `transform` sólo para el traslado que viene
     y la apaga sola. Nunca queda prendida: si estuviera viva durante un
     arrastre, la placa iría 260 ms atrás del dedo. */
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

  /* Cualquier gesto del médico sobre la placa corta el viaje en seco. */
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

    /* Antes esto asignaba el transform de una: la placa teletransportaba y
       el médico perdía la referencia de dónde a dónde se movió, justo
       cuando pidió que lo lleven a un hallazgo. */
    var destino = { tx: vw / 2 - cx * this.scale, ty: vh / 2 - cy * this.scale };

    /* Con capa de movimiento el viaje es un tween sobre las propiedades del
       visor, no una transición de CSS encendida por una clase. Se ganan dos
       cosas que sólo se ven con la mano encima:

       · fijar OTRO hallazgo a mitad del viaje reapunta desde la posición
         actual (`overwrite: true`) en vez de dejar corriendo el `setTimeout`
         del viaje anterior, que podía apagar la clase en medio del segundo;
       · el recorte de la cortina se recalcula DENTRO del mismo `apply()`
         que dibuja la placa, cuadro por cuadro. Antes viajaba en una
         transición paralela, con su propia curva, «clavada» sólo porque los
         números coincidían. Ahora no puede despegarse ni aunque se quiera. */
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

  /* ── El barrido de apertura ──────────────────────────────────────────
     Una sola pasada, una sola vez por página: dice en un gesto de dónde
     salieron esas marcas — el sistema las puso encima de la placa.

     El dato de triage (veredicto, medidor, urgencia) NO participa: está
     legible desde el cuadro cero. Lo único que se revela es la imagen.
     Con vectores, lo que se descubre es la capa SVG. */
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

    /* ── CON CAPA DE MOVIMIENTO: LA CABEZA DEJA LAS CAJAS DIBUJADAS ──────
       Éste es el cambio más grande del visor y sólo se puede hacer ahora que
       las cajas son vectores (§35) y no píxeles quemados en un PNG.

       Antes la cabeza pasaba y un `clip-path` DESCUBRÍA una capa que ya
       estaba dibujada: el gesto decía «acá abajo había algo». Ahora cada
       caja se TRAZA en el momento en que la cabeza cruza su borde superior,
       en el orden que da la coordenada `y1` de cada detección — o sea, el
       orden lo pone el modelo, no la presentación. El gesto pasa a decir
       «esto es lo que el sistema encontró, y acá es donde lo encontró».

       Y no afirma ninguna magnitud falsa: los cuatro vértices de la caja
       están en su posición final desde el primer píxel de trazo, porque lo
       que avanza es el recorrido del perímetro y no la extensión del
       rectángulo. El score, que sí es una magnitud, no participa: vive en la
       barra del panel, que nace a su largo medido. */
    if (window.TVMotion && window.TVMotion.movimiento) {
      var tl = window.TVMotion.revelar({
        viewport: this.viewport, img: this.img, svg: this.svg,
        capa: this.vector ? this.svg : this.img,
        rects: this.rects, vector: this.vector,
        scale: this.scale, ty: this.ty
      });
      if (tl) {
        /* Si el médico toca la imagen, el revelado termina ahí mismo, en su
           estado final. Nadie espera a una animación para empezar a
           trabajar. */
        var eventos = ['pointerdown', 'wheel', 'keydown'];
        var soltar = function () {
          eventos.forEach(function (ev) { self.viewport.removeEventListener(ev, cortar); });
        };
        var cortar = function () { tl.progress(1); soltar(); };
        eventos.forEach(function (ev) {
          self.viewport.addEventListener(ev, cortar, { passive: true });
        });
        /* `.then()` y no `eventCallback('onComplete')`: la timeline ya usa su
           final para retirar la cabeza de lectura del DOM, y engancharse con
           `eventCallback` se lo pisaría. */
        if (tl.then) tl.then(soltar);
        return;
      }
    }

    /* ── SIN CAPA DE MOVIMIENTO: la figura de siempre, con WAAPI ───────── */
    if (typeof this.img.animate !== 'function') return;
    var vr = this.viewport.getBoundingClientRect();
    var ir = this.img.getBoundingClientRect();
    if (!ir.height || !ir.width) return;

    /* Con vectores, la capa que se descubre es el SVG; sin vectores, la
       imagen anotada. Es la misma figura sobre la capa que corresponda. */
    var capa = this.vector ? this.svg : this.img;
    if (!capa || typeof capa.animate !== 'function') return;

    var ALTO_BANDA = 78;
    var linea = document.createElement('span');
    linea.className = 'scanline';
    linea.style.top = (ir.top - vr.top - ALTO_BANDA) + 'px';
    linea.style.left = (ir.left - vr.left) + 'px';
    linea.style.width = ir.width + 'px';
    this.viewport.appendChild(linea);

    /* Misma duración y misma curva en las dos animaciones: la cabeza de
       lectura y el borde del recorte avanzan clavados uno al otro. Un
       cabezal de lectura arranca, viaja parejo y frena, así que la curva
       es casi lineal en el medio y sólo se asienta al final. */
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
    /* Si el médico toca la imagen, el barrido termina ahí mismo. Nadie
       espera a una animación para empezar a trabajar. */
    eventos.forEach(function (ev) {
      self.viewport.addEventListener(ev, terminar, { passive: true });
    });
  };

  Viewer.prototype.apply = function () {
    var t = 'translate(' + this.tx + 'px,' + this.ty + 'px) scale(' + this.scale + ')';
    for (var i = 0; i < this.capas.length; i++) this.capas[i].style.transform = t;
    if (this.svg) this.svg.style.transform = t;
    /* Los números de las cajas se contra-escalan sólo cuando cambió el
       zoom: durante un arrastre puro no hay nada que recalcular. */
    if (this.rects.length && this.scale !== this.lastDrawScale) {
      this.lastDrawScale = this.scale;
      var k = 1 / this.scale;
      /* Dos cajas que arrancan casi en el mismo punto —pasa cuando el
         detector encuadra la misma lesión dos veces— anclaban su número en
         el mismo lugar y uno tapaba al otro: esa caja quedaba sin marcador
         localizable sobre la placa, y su fila del panel apuntaba a nada.

         Cada número que choca con uno ya colocado sube un escalón. El
         escalón va DESPUÉS de la escala invertida, así mide siempre lo
         mismo en pantalla y el apilado no se deshace al hacer zoom. */
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
    /* 100 % = un píxel de imagen por píxel de pantalla. */
    if (this.zoomOut) this.zoomOut.textContent = Math.round(this.scale * 100) + '%';
  };

  /* Un margen de aire alrededor de la placa. Sin él, "ajustar" la pega a los
     cuatro bordes y la placa se lee como recortada, no como una placa sobre
     una mesa. Son 20 px: alcanzan para que se vea el canto. */
  var AIRE = 20;

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

  /* Zoom manteniendo fijo el punto bajo el cursor. */
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

  /* ── Marcas sí / marcas no ───────────────────────────────────────────
     Con vectores es apagar la capa SVG sobre la placa limpia. Sin ellos,
     se cae al comportamiento de siempre: alternar anotada y original. */
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

  /* El botón de marcas tiene DOS cosas que decir sobre su estado: si está
     apretado y qué va a hacer si lo aprietan. Se ponían en dos lugares
     distintos —`toggleOriginal` las dos, `setSource` sólo `aria-pressed`— y
     al cambiar de imagen el botón quedaba sin apretar ofreciendo «Mostrar las
     marcas» con las marcas ya puestas. Un solo lugar, las dos juntas. */
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

  /* ── Cortina de comparación ──────────────────────────────────────────
     Un divisor arrastrable: a la izquierda la placa como salió del equipo,
     a la derecha con lo que marcó el sistema. Es la pregunta que un médico
     le hace a un detector — «¿qué hay ahí debajo?» — hecha gesto.

     Vive en coordenadas de PANTALLA, no de imagen: el médico arrastra
     donde ve, sin importar el zoom. */
  /* ── La cortina entra y sale barriendo ───────────────────────────────
     Aparecer de golpe clavada en el medio de la placa convertía una
     afirmación —esas marcas las puso el sistema— en un corte. La línea
     entra desde el canto izquierdo llevándose las marcas consigo: se ve
     que son una CAPA y se ve de dónde salen. Sale por donde entró, que es
     lo que hace obvio que se puede arrastrar.

     `--clip` y `--corte` son propiedades registradas (@property en la hoja);
     sin registrar no interpolan y esto no sería posible sin JS por cuadro. */
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
      /* Estado de partida sin transición: línea pegada al canto, marcas
         enteras. Recién después se enciende el barrido — si no, arrancaría
         desde el medio y no habría nada que ver. */
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
      /* Si el médico agarra la cortina mientras todavía está entrando, el
         barrido se corta acá: durante un arrastre la línea tiene que ir
         pegada al dedo, no 280 ms atrás. */
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

  /* El tirador vive en coordenadas de PANTALLA; el clip-path de las capas
     marcadas, en coordenadas de la IMAGEN (están escaladas y desplazadas).
     Si se les pasa el mismo porcentaje, la línea y el corte se separan en
     cuanto hay zoom o desplazamiento. Acá se traduce una en la otra, y se
     vuelve a traducir en cada apply(). */
  Viewer.prototype.recortarCortina = function () {
    if (!this.comparing) return;
    var iw = this.img.naturalWidth;
    if (!iw) return;
    var xPantalla = (this.corte / 100) * this.viewport.clientWidth;
    var xImagen = (xPantalla - this.tx) / this.scale;
    var frac = Math.min(100, Math.max(0, (xImagen / iw) * 100));
    this.viewport.style.setProperty('--clip', frac + '%');
  };

  /* ── Ventana: brillo y contraste ─────────────────────────────────────
     Es una radiografía. Mover la ventana es parte de leerla, y hasta ahora
     no se podía. Se compone con la inversión de grises en una sola cadena
     de filtros para que los tres controles convivan. */
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

    /* `pinned` acaba de volver a -1: no hay ningún hallazgo fijado. Las filas
       del panel que se abandona quedaban con `aria-pressed="true"` para
       siempre —`fijar` sólo limpia `this.filas`, que para cuando llega acá ya
       es del panel nuevo—, así que el lector de pantalla anunciaba un
       hallazgo fijado que el visor no tenía. Se limpia en todo el documento,
       que es donde viven los paneles de las otras imágenes. */
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
      /* CAMBIAR DE IMAGEN ES UNA LECTURA NUEVA, Y TIENE QUE VERSE COMO TAL.
         Dos radiografías de muñeca se parecen muchísimo: sin movimiento, el
         estudio multi-imagen reemplaza placa y panel de golpe y el médico no
         tiene ninguna señal de que la pantalla cambió. Se repite el mismo
         gesto que en una carga de página —la cabeza pasa y deja las cajas de
         ESTA imagen dibujadas, y el panel se asienta alrededor— porque es la
         misma cosa: una lectura que llega.

         El veredicto de la imagen nueva NO participa, como siempre: está en
         el primer cuadro. La puerta del cuadro cero de motion.js lo descarta
         aunque alguien lo escribiera en la lista. */
      self._barrido = false;
      self.armarBarrido();
      if (window.TVMotion) {
        var panel = document.querySelector('[data-panel-idx]:not([hidden])')
                 || document.querySelector('[data-find-host]');
        window.TVMotion.encenderPanel(panel);
      }
    });
    if (meta) {
      /* querySelectorAll y no querySelector: el mismo dato puede estar
         espejado en más de un lugar de la pantalla. Con el rediseño, el
         índice de la imagen aparece en el sobreimpreso de la placa Y en el
         pie de figura; con `querySelector` sólo se actualizaba el primero y
         el pie quedaba citando la imagen anterior. */
      Object.keys(meta).forEach(function (k) {
        self.root.querySelectorAll('[data-ov="' + k + '"]').forEach(function (el) {
          el.textContent = meta[k];
        });
      });
    }
  };

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

    /* Botones de la barra */
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
        else if (a === 'invert') {
          var on = self.root.classList.toggle('is-inverted');
          btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        }
        else if (a === 'full') self.fullscreen(btn);
      });
    });

    /* Deslizadores de ventana */
    this.root.querySelectorAll('[data-win]').forEach(function (inp) {
      inp.addEventListener('input', function () {
        var v = Number(inp.value);
        if (inp.dataset.win === 'br') self.setVentana(v, null);
        else self.setVentana(null, v);
      });
    });
    var reset = this.root.querySelector('[data-win-reset]');
    if (reset) reset.addEventListener('click', function () { self.setVentana(100, 100); });

    /* Cierra el panel de ventana al tocar fuera. */
    document.addEventListener('pointerdown', function (e) {
      var pop = self.root.querySelector('[data-tools]');
      if (pop && !pop.contains(e.target)) self.togglePanelVentana(false);
    });

    /* ── Teclado ──────────────────────────────────────────────────────
       Los atajos del visor viven en el documento, no sólo en la ventana:
       un médico que acaba de hacer clic en un hallazgo del panel tiene el
       foco en el panel, y aun así "N" tiene que llevarlo al siguiente. Se
       ignoran cuando se está escribiendo en un campo. */
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
      else if (k === 'i' || k === 'I') {
        var btn = self.root.querySelector('[data-act="invert"]');
        var on = self.root.classList.toggle('is-inverted');
        if (btn) btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      }
      else if (k === 'n' || k === 'N') self.siguienteHallazgo(1);
      else if (k === 'p' || k === 'P') self.siguienteHallazgo(-1);
      else if (k === 'Escape') { if (self.pinned === -1) return; self.fijar(-1); }
      /* Las flechas desplazan la placa sólo si el foco está en el visor:
         si no, son la navegación normal de la página. */
      /* Las flechas se repiten al mantenerlas apretadas: con el traslado
         encendido cada repetición reiniciaría la transición y la placa
         quedaría atrás del teclado. Se frena antes de desplazar. */
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

  /* Tira de miniaturas: cambia la imagen del visor sin recargar la página. */
  function bindFilmstrip(viewer) {
    var strip = document.querySelector('[data-filmstrip]');
    if (!strip || !viewer) return;
    strip.querySelectorAll('.frame').forEach(function (frame) {
      frame.addEventListener('click', function () {
        strip.querySelectorAll('.frame').forEach(function (f) {
          f.setAttribute('aria-current', 'false');
        });
        frame.setAttribute('aria-current', 'true');
        /* El panel de la imagen elegida trae SUS cajas: se publican en el
           nodo que lee leerCajas antes de reconstruir los vectores. */
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
    window.__viewer = v;
    bindFilmstrip(v);
  });
})();
