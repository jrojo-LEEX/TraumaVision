/* motion.js — Capa de movimiento (GSAP) */
(function () {
  'use strict';

  if (!window.gsap) return;

  var gsap = window.gsap;
  var ScrollTrigger = window.ScrollTrigger;
  if (ScrollTrigger) gsap.registerPlugin(ScrollTrigger);

  var MOVIMIENTO = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Curvas y duraciones */
  var E_ASENTAR  = 'expo.out';
  var E_TRASLADO = 'power2.inOut';
  var E_CABEZAL  = 'power1.inOut';

  var D_ACUSE   = 0.16;
  var D_BLOQUE  = 0.26;
  var D_CABEZAL = 0.62;

  gsap.defaults({ duration: D_BLOQUE, ease: E_ASENTAR });

  /* El veredicto y sus salvedades nunca se animan */
  var CUADRO_CERO = [
    '.verdict-strip',
    '.triage',
    '.scope-line',
    '.find-unit',
    '.study-verdict',
    '.domain-flag'
  ].join(',');

  function esCuadroCero(el) {
    if (!el || el.nodeType !== 1) return true;
    if (el.closest && el.closest(CUADRO_CERO)) return true;
    if (el.matches && el.matches(CUADRO_CERO)) return true;
    if (el.querySelector && el.querySelector(CUADRO_CERO)) return true;
    return false;
  }

  /* Lo que representa una cantidad medida no se anima; sus contenedores sólo se funden */
  var MAGNITUDES = ['.find-fill', '.find-cut', '.tally-fill', '.mrow-ic'].join(',');

  function esMagnitud(el) {
    return !!(el && el.matches && el.matches(MAGNITUDES));
  }

  var GEOMETRIA = ['x', 'y', 'xPercent', 'yPercent', 'scale', 'scaleX',
                   'scaleY', 'rotation', 'skewX', 'skewY', 'width', 'height'];

  function llevaMagnitud(el) {
    return !!(el && el.querySelector && el.querySelector(MAGNITUDES));
  }

  /* Separa lo animable de lo protegido */
  function repartir(sel, raiz) {
    var lista = typeof sel === 'string'
      ? (raiz || document).querySelectorAll(sel)
      : (sel && sel.length !== undefined ? sel : (sel ? [sel] : []));
    var libres = [], soloFundido = [], vetados = [];
    Array.prototype.forEach.call(lista, function (el) {
      if (!el || el.nodeType !== 1) return;
      if (esCuadroCero(el)) { vetados.push(['cuadro-0', el]); return; }
      if (esMagnitud(el))   { vetados.push(['magnitud', el]); return; }
      (llevaMagnitud(el) ? soloFundido : libres).push(el);
    });
    if (vetados.length && window.console && console.warn) {
      console.warn('[motion] descartados por la doctrina:', vetados);
    }
    return { libres: libres, soloFundido: soloFundido };
  }

  function bloques(sel, raiz) {
    var r = repartir(sel, raiz);
    return r.libres.concat(r.soloFundido);
  }

  function mezclar(base, extra) {
    var v = {}, k;
    for (k in base) if (base.hasOwnProperty(k)) v[k] = base[k];
    if (extra) for (k in extra) if (extra.hasOwnProperty(k)) v[k] = extra[k];
    return v;
  }

  /* Encendido: los bloques se asientan alrededor del dato */
  function asentar(sel, raiz, extra) {
    var r = repartir(sel, raiz);
    var base = { autoAlpha: 0, y: 6, duration: D_BLOQUE, ease: E_ASENTAR,
                 stagger: 0.055, clearProps: 'opacity,visibility,transform' };
    var vars = mezclar(base, extra);

    if (r.libres.length) gsap.from(r.libres, vars);

    if (r.soloFundido.length) {
      var quietas = mezclar(vars, null);
      GEOMETRIA.forEach(function (p) { delete quietas[p]; });
      quietas.autoAlpha = 0;
      gsap.from(r.soloFundido, quietas);
    }
  }

  /* Overlay de progreso: barrido cíclico sobre la placa */
  function placaEnLectura() {
    var overlay = document.getElementById('progress-overlay');
    if (!overlay) return;
    var placa = overlay.querySelector('[data-scanplate]');
    var banda = overlay.querySelector('.scanplate-band');
    if (!placa || !banda) return;

    var marcas = placa.querySelectorAll('.scanplate-mark');
    var caja = overlay.querySelector('.progress-box');
    var tl = null;

    function tomar() {
      if (tl) { tl.restart(true); return; }
      banda.style.animation = 'none';
      gsap.set(banda, { yPercent: -100, autoAlpha: 0 });

      tl = gsap.timeline();

      if (caja) tl.from(caja, { autoAlpha: 0, y: 10, duration: 0.24 }, 0);
      tl.from(placa, { autoAlpha: 0, duration: 0.28 }, 0.06);
      if (marcas.length) {
        tl.from(marcas, {
          autoAlpha: 0,
          x: function (i) { return (i === 0 || i === 2) ? -10 : 10; },
          y: function (i) { return (i === 0 || i === 1) ? -10 : 10; },
          duration: 0.3, stagger: { each: 0.04, from: 'center' }
        }, 0.16);
      }

      var ciclo = gsap.timeline({ repeat: -1 });
      ciclo
        .set(banda, { yPercent: -100, autoAlpha: 0 })
        .to(banda, { autoAlpha: 1, duration: 0.14, ease: 'none' }, 0)
        .to(banda, { yPercent: 385, duration: 2.4, ease: E_CABEZAL }, 0)
        .to(banda, { autoAlpha: 0, duration: 0.18, ease: 'none' }, 2.22)
        .to(banda, { autoAlpha: 0.6, duration: 0.1, ease: 'none' }, 2.44)
        .to(banda, { yPercent: -100, duration: 0.44, ease: E_TRASLADO }, 2.44)
        .to(banda, { autoAlpha: 0, duration: 0.1, ease: 'none' }, 2.88);

      tl.add(ciclo, 0.42);
    }

    var obs = new MutationObserver(function () {
      if (overlay.classList.contains('open')) tomar();
      else if (tl) { tl.kill(); tl = null; banda.style.removeProperty('animation'); }
    });
    obs.observe(overlay, { attributes: true, attributeFilter: ['class'] });
    if (overlay.classList.contains('open')) tomar();
  }

  /* Barrido del visor: la cabeza de lectura baja por la placa */
  function medioBarrido(ctx) {
    var vr = ctx.viewport.getBoundingClientRect();
    var ir = ctx.img.getBoundingClientRect();
    if (!ir.height || !ir.width) return null;

    var ALTO_BANDA = 78;
    var linea = document.createElement('span');
    linea.className = 'scanline';
    linea.style.top = (ir.top - vr.top - ALTO_BANDA) + 'px';
    linea.style.left = (ir.left - vr.left) + 'px';
    linea.style.width = ir.width + 'px';
    ctx.viewport.appendChild(linea);

    var tl = gsap.timeline();
    var estado = { tl: tl, linea: linea, ir: ir, alPasar: null };

    tl.fromTo(linea, { y: 0 }, {
      y: ir.height, duration: D_CABEZAL, ease: E_CABEZAL,
      onUpdate: function () {
        if (estado.alPasar) estado.alPasar(gsap.getProperty(linea, 'y'));
      }
    }, 0);
    tl.fromTo(linea, { autoAlpha: 0 },
      { autoAlpha: 1, duration: 0.05, ease: 'none' }, 0);
    tl.to(linea, { autoAlpha: 0, duration: 0.14, ease: 'none' }, D_CABEZAL - 0.14);

    return estado;
  }

  /* Deja una caja lista para trazarse cuando la cabeza la cruce */
  function prepararCaja(rect, ir) {
    var r = rect.g.querySelector('rect');
    if (!r) return null;
    r.setAttribute('pathLength', '1');
    gsap.set(r, { strokeDasharray: 1, strokeDashoffset: 1 });
    gsap.set(rect.tag, { autoAlpha: 0 });

    var br = rect.g.getBoundingClientRect();
    var yPlaca = br.top - ir.top;
    return { r: r, tag: rect.tag,
             y: Math.min(ir.height, Math.max(0, yPlaca)), hecha: false };
  }

  /* API que usa viewer.js */
  var API = {
    movimiento: MOVIMIENTO,

    revelar: function (ctx) {
      if (!MOVIMIENTO) return null;
      var base = medioBarrido(ctx);
      if (!base) return null;
      var tl = base.tl;

      if (ctx.vector && ctx.rects && ctx.rects.length) {
        var cajas = [];
        ctx.rects.forEach(function (rc) {
          var p = prepararCaja(rc, base.ir);
          if (p) cajas.push(p);
        });

        base.alPasar = function (y) {
          for (var i = 0; i < cajas.length; i++) {
            var c = cajas[i];
            if (c.hecha || y < c.y) continue;
            c.hecha = true;
            gsap.to(c.r, { strokeDashoffset: 0, duration: 0.2, ease: 'none' });
            gsap.to(c.tag, { autoAlpha: 1, duration: D_ACUSE, delay: 0.2,
                             ease: E_ASENTAR });
          }
        };
        var trazos = cajas.map(function (c) { return c.r; });
        var etiquetas = cajas.map(function (c) { return c.tag; });
        var CIERRE = D_CABEZAL + 0.4;
        tl.call(function () {
          gsap.killTweensOf(trazos.concat(etiquetas));
          trazos.forEach(function (r) {
            r.removeAttribute('pathLength');
            r.style.removeProperty('stroke-dasharray');
            r.style.removeProperty('stroke-dashoffset');
          });
          etiquetas.forEach(function (t) {
            t.style.removeProperty('opacity');
            t.style.removeProperty('visibility');
          });
        }, null, CIERRE);
      } else if (ctx.capa) {
        tl.fromTo(ctx.capa,
          { clipPath: 'inset(0 0 100% 0)' },
          { clipPath: 'inset(0 0 0% 0)', duration: D_CABEZAL, ease: E_CABEZAL }, 0);
        tl.set(ctx.capa, { clearProps: 'clipPath' });
      }
      tl.call(function () {
        if (base.linea.parentNode) base.linea.parentNode.removeChild(base.linea);
      });
      return tl;
    },

    /* Anillo que se cierra sobre la caja fijada */
    anillar: function (svg, b, escala) {
      if (!MOVIMIENTO || !svg) return null;
      var SVGNS = 'http://www.w3.org/2000/svg';
      var ring = document.createElementNS(SVGNS, 'rect');
      ring.setAttribute('class', 'bx-ping');
      ring.setAttribute('x', b.x1);
      ring.setAttribute('y', b.y1);
      ring.setAttribute('width', Math.max(1, b.x2 - b.x1));
      ring.setAttribute('height', Math.max(1, b.y2 - b.y1));
      ring.setAttribute('rx', 2);
      ring.setAttribute('vector-effect', 'non-scaling-stroke');
      svg.appendChild(ring);

      var w = Math.max(1, b.x2 - b.x1), h = Math.max(1, b.y2 - b.y1);
      var lado = Math.max(w, h);
      var cx = b.x1 + w / 2, cy = b.y1 + h / 2;

      var afuera = Math.min(22 / (escala || 1), lado * 0.6);
      var W0 = w + 2 * afuera, H0 = h + 2 * afuera;

      function limpiar() { if (ring.parentNode) ring.parentNode.removeChild(ring); }

      var tl = gsap.timeline({ onComplete: limpiar, onInterrupt: limpiar });
      tl.fromTo(ring,
        { attr: { x: cx - W0 / 2, y: cy - H0 / 2, width: W0, height: H0 },
          autoAlpha: 0 },
        { attr: { x: b.x1, y: b.y1, width: w, height: h },
          autoAlpha: 1, duration: 0.15, ease: 'power2.out' })
        .to(ring, { autoAlpha: 1, duration: 0.06 })
        .to(ring, { autoAlpha: 0, duration: 0.13, ease: 'none' });
      return tl;
    },

    /* Traslado de la placa hasta un hallazgo */
    viajar: function (visor, destino, aplicar) {
      if (!MOVIMIENTO) {
        visor.tx = destino.tx; visor.ty = destino.ty; aplicar();
        return null;
      }
      return gsap.to(visor, {
        tx: destino.tx, ty: destino.ty,
        duration: 0.34, ease: E_TRASLADO,
        overwrite: true,
        onUpdate: aplicar
      });
    },

    frenar: function (visor) { gsap.killTweensOf(visor); },

    /* Encendido del panel al cambiar de imagen */
    encenderPanel: function (raiz) {
      if (!MOVIMIENTO || !raiz) return null;
      return asentar('.rd-top, .find-head, .find-list .find, .scope, .quiet, .rd-actions',
                     raiz, { y: 4, duration: 0.22, stagger: 0.04 });
    }
  };

  window.TVMotion = API;

  /* Animaciones de carga de cada pantalla (sólo sin movimiento reducido) */
  var mm = gsap.matchMedia();

  mm.add('(prefers-reduced-motion: no-preference)', function () {

    asentar('.login-mark, .login-head, .login-card form .field-group, ' +
            '.login-card .btn-lg, .demo-panel', null, { y: 8, stagger: 0.06 });

    asentar('.page-header, .info-card, .dropzone, .metrics-provenance', null,
            { stagger: 0.05 });

    asentar('.page-header, .table-controls, .table-wrap, .table-foot', null);

    asentar('.dash-hero, .page-header, .metrics-head', null);

    asentar('.legal-list > *, .error-box', null, { stagger: 0.04 });

    asentar('.rd-top, .find-head, .scope, .quiet, .rd-actions',
            null, { y: 5, stagger: 0.05 });

    asentar('.find-list .find', null,
            { y: 0, autoAlpha: 0, duration: 0.24, stagger: 0.035, delay: 0.1 });

    asentar('.study-bar-main .meta-line:not(.study-verdict), .study-tally, .filmstrip',
            null, { y: 4, stagger: 0.05 });

    placaEnLectura();

    /* Panel de brillo y contraste */
    var panelVentana = document.querySelector('[data-tool-panel]');
    if (panelVentana) {
      var obsPanel = new MutationObserver(function () {
        if (panelVentana.hidden) return;
        gsap.from(panelVentana, {
          autoAlpha: 0, scale: 0.96, y: -4,
          transformOrigin: 'left top',
          duration: 0.16, ease: E_ASENTAR
        });
      });
      obsPanel.observe(panelVentana, { attributes: true, attributeFilter: ['hidden'] });
    }

    metricas();
    tablaHistorial();
  });

  /* Métricas: cada figura se anima al entrar en pantalla */
  function alEntrar(el, hacer, cuando) {
    if (!ScrollTrigger) { hacer(); return; }
    ScrollTrigger.create({
      trigger: el,
      start: cuando || 'top 88%',
      once: true,
      onEnter: hacer
    });
    setTimeout(function () { if (!el.dataset.tvVisto) hacer(); }, 2500);
  }

  function unaVez(el, fn) {
    return function () {
      if (el.dataset.tvVisto) return;
      el.dataset.tvVisto = '1';
      fn();
    };
  }

  function metricas() {
    var mrows = document.querySelector('.ev-metrics');
    if (mrows) {
      alEntrar(mrows, unaVez(mrows, function () {
        var pistas = bloques('.mrow-track', mrows);
        if (pistas.length) gsap.from(pistas, { autoAlpha: 0, duration: 0.3, ease: E_ASENTAR });
        var puntos = mrows.querySelectorAll('.mrow-dot');
        if (puntos.length) {
          gsap.from(puntos, {
            scale: 0.35, autoAlpha: 0, transformOrigin: 'center center',
            duration: 0.18, ease: E_ASENTAR, delay: 0.16
          });
        }
      }));
    }

    var waffle = document.querySelector('.ev-waffle');
    if (waffle) {
      alEntrar(waffle, unaVez(waffle, function () {
        waffle.classList.add('is-contando');
      }));
    }

    document.querySelectorAll('.chart-box').forEach(function (c) {
      alEntrar(c, unaVez(c, function () {
        gsap.from(c, { autoAlpha: 0, duration: 0.34, ease: E_ASENTAR });
      }));
    });
  }

  /* Historial: las filas viajan al reordenar (FLIP); si el salto es largo, se funden */
  var VIAJE_MAXIMO = 320;

  function tablaHistorial() {
    var tabla = document.getElementById('tabla');
    if (!tabla || !tabla.tBodies[0]) return;
    var cuerpo = tabla.tBodies[0];

    function visibles() {
      return Array.prototype.filter.call(cuerpo.rows, function (r) { return !r.hidden; });
    }

    window.TVFlipTabla = {
      medir: function () {
        if (!MOVIMIENTO) return null;
        var antes = new Map();
        visibles().forEach(function (r) {
          antes.set(r, r.getBoundingClientRect().top);
        });
        return antes;
      },

      animar: function (antes) {
        if (!antes || !MOVIMIENTO) return;
        var viajan = [], aparecen = [];
        visibles().forEach(function (r) {
          var y0 = antes.get(r);
          var y1 = r.getBoundingClientRect().top;
          if (y0 === undefined) { aparecen.push(r); return; }
          var d = y0 - y1;
          if (Math.abs(d) < 1) return;
          if (Math.abs(d) > VIAJE_MAXIMO) { aparecen.push(r); return; }
          viajan.push({ el: r, d: d });
        });

        viajan.forEach(function (v) {
          gsap.fromTo(v.el, { y: v.d },
            { y: 0, duration: 0.24, ease: E_TRASLADO, overwrite: true,
              clearProps: 'transform' });
        });

        if (aparecen.length) {
          gsap.fromTo(aparecen, { autoAlpha: 0 },
            { autoAlpha: 1, duration: D_ACUSE, ease: E_ASENTAR,
              overwrite: true, clearProps: 'opacity,visibility' });
        }
      }
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      if (ScrollTrigger) ScrollTrigger.refresh();
    });
  }
})();
