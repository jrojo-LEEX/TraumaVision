/*
 * motion.js — LA CAPA DE MOVIMIENTO.
 *
 * La aplicación ya tenía DOS figuras de movimiento, argumentadas en la hoja
 * de estilos y respetadas acá al pie de la letra:
 *
 *   · EL BARRIDO (§21, §32)  — la máquina leyendo. Largo, casi lineal, lo
 *     decide el sistema y no lo pidió nadie.
 *   · EL SEÑALAMIENTO (§39)  — el instrumento contestándole al médico.
 *     Corto, ease-out, SIEMPRE lo dispara una mano.
 *
 * Este archivo agrega la TERCERA, que es la que faltaba, y eleva las dos que
 * ya estaban usando una sola gramática (GSAP) en lugar de tres motores
 * distintos —keyframes CSS, transiciones CSS y WAAPI a mano— que hasta ahora
 * corrían con relojes separados.
 *
 *   · EL ENCENDIDO (§40) — el instrumento se enciende ALREDEDOR DEL DATO.
 *
 * ── POR QUÉ EL ENCENDIDO ES ESTO Y NO UNA ENTRADA DE PÁGINA ──────────────
 *
 * La restricción más dura del proyecto es la regla del cuadro cero: el
 * veredicto de triage, «no es una probabilidad de fractura» y «confirmar
 * con lectura médica» están LEGIBLES EN EL PRIMER
 * CUADRO, sin transform, sin opacidad inicial y sin retraso. Un médico de
 * guardia no espera por un dato de triage.
 *
 * En la mayoría de los proyectos esa regla es un impuesto que se le paga al
 * movimiento. Acá es al revés: es el movimiento. Si el chasis, el panel, la
 * lista de hallazgos y las acciones se asientan un instante DESPUÉS, entonces
 * el que mira la pantalla ve —sin que nadie se lo explique— que el veredicto
 * ya estaba cuando todo lo demás todavía estaba llegando. La regla deja de
 * ser una limitación que hay que defender y pasa a ser la figura que se
 * defiende. Esa es la firma de movimiento de esta aplicación:
 *
 *      EL DATO NO ENTRA. ENTRA EL INSTRUMENTO, Y EL DATO YA ESTABA.
 *
 * Por eso la regla no se cumple sólo por disciplina: está implementada como
 * una PUERTA (`esCuadroCero`, más abajo). Cualquier animación de este archivo
 * que apunte a una de las cuatro piezas —o a un ancestro que las contenga— se
 * descarta en tiempo de ejecución y se avisa por consola. Un error de dedo no
 * puede tapar un veredicto.
 *
 * ── DEGRADACIÓN ─────────────────────────────────────────────────────────
 *
 * Regla del proyecto: «estado por defecto = estado final». Si este archivo no
 * corre, o si GSAP no cargó, la aplicación queda ENTERA: ningún elemento
 * queda esperando a que el JS lo destape, porque el estado inicial de toda
 * animación lo pone GSAP en tiempo de ejecución (`from`, `set`), nunca la
 * hoja de estilos. La primera línea ejecutable de este archivo es la que se
 * asegura de eso.
 *
 * ── MOVIMIENTO REDUCIDO ─────────────────────────────────────────────────
 *
 * Todo lo que se crea al arrancar vive dentro de un `gsap.matchMedia()` con
 * la consulta `(prefers-reduced-motion: no-preference)`. Con `reduce` esos
 * bloques NO SE EJECUTAN: no hay nada que apagar porque nunca se creó nada, y
 * la página queda pintada en su valor final con la misma información. Lo que
 * se dispara por evento (el revelado, el anillo, el viaje) pregunta por
 * `MOVIMIENTO` antes de tocar nada.
 */
(function () {
  'use strict';

  /* Sin GSAP no hay capa de movimiento — y no hay nada que reparar, porque
     nadie escondió nada. Se sale en silencio: un `console.error` en la
     pantalla de una defensa es peor que la ausencia de una animación. */
  if (!window.gsap) return;

  var gsap = window.gsap;
  var ScrollTrigger = window.ScrollTrigger;
  if (ScrollTrigger) gsap.registerPlugin(ScrollTrigger);

  var MOVIMIENTO = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ══════════════════════════════════════════════════════════════════════
     A. CIMIENTOS
     ══════════════════════════════════════════════════════════════════════ */

  /* LAS DOS CURVAS DE LA HOJA, TRADUCIDAS. No se inventa ninguna curva acá:
     la aplicación tiene dos y sólo dos, declaradas en §2 de style.css, y este
     archivo usa las mismas para que el movimiento de JS y el de CSS no se
     lean como dos sistemas distintos.

       --ease       cubic-bezier(.16,1,.3,1)   = easeOutExpo   -> 'expo.out'
       --ease-move  cubic-bezier(.65,0,.35,1)  = easeInOutCubic-> 'power2.inOut'

     La tercera no es una curva nueva: es la del CABEZAL DE LECTURA, que ya
     existía escrita a mano dentro de viewer.js como cubic-bezier(.35,0,.25,1)
     — «arranca, viaja parejo y frena». Se centraliza acá para que el barrido
     del overlay de inferencia y el revelado del visor usen exactamente la
     misma, que es todo el argumento de §32: son la misma cabeza leyendo. */
  var E_ASENTAR  = 'expo.out';
  var E_TRASLADO = 'power2.inOut';
  var E_CABEZAL  = 'power1.inOut';

  /* El techo de duración de la interfaz. Está en 300 ms porque es el punto
     donde una respuesta empieza a sentirse lenta, y esta aplicación es un
     instrumento de guardia. Lo único que puede pasarse es la lectura de la
     placa, que NO es interfaz: es el sistema trabajando. */
  var D_ACUSE   = 0.16;   /* acuse de recibo */
  var D_BLOQUE  = 0.26;   /* un bloque que se asienta */
  var D_CABEZAL = 0.62;   /* una pasada de la cabeza de lectura sobre la placa */

  gsap.defaults({ duration: D_BLOQUE, ease: E_ASENTAR });

  /* ── LA PUERTA DEL CUADRO CERO ──────────────────────────────────────────
     Las cuatro piezas que no pueden ocultarse, atrasarse ni aparecer, en las
     DOS pantallas donde salen (visor de análisis y estudio multi-imagen).

     Se listan por CONTENEDOR y no por la clase exacta del texto, a propósito:
     lo que hay que proteger no es un selector sino la frase, y las frases se
     mudan de componente (la salvedad ya se mudó una vez, a la franja del
     visor). Bloqueando el contenedor entero queda protegido lo que hay
     adentro hoy y lo que se mude adentro mañana. */
  var CUADRO_CERO = [
    '.verdict-strip',   /* franja del visor: veredicto + salvedades */
    '.triage',          /* panel de lectura: la palabra, el medidor, la salvedad */
    '.gauge',           /* el medidor y su número */
    '.scope-line',      /* «confirmar con lectura médica» */
    '.find-unit',       /* «no es una probabilidad de fractura» */
    '.study-verdict',   /* el veredicto del estudio multi-imagen */
    '.domain-flag'      /* «registro fuera del dominio validado» */
  ].join(',');

  /* Un elemento está protegido si ES una de esas piezas, si vive ADENTRO de
     una, o si CONTIENE una. Las tres direcciones importan: fundir un ancestro
     baja la opacidad de todo lo que cuelga de él, que es exactamente la forma
     accidental de tapar un veredicto (un `gsap.from` sobre `.readout` habría
     atrasado el triage entero sin que el selector lo dijera). */
  function esCuadroCero(el) {
    if (!el || el.nodeType !== 1) return true;      /* en la duda, no se toca */
    if (el.closest && el.closest(CUADRO_CERO)) return true;
    if (el.matches && el.matches(CUADRO_CERO)) return true;
    if (el.querySelector && el.querySelector(CUADRO_CERO)) return true;
    return false;
  }

  /* ── LA PUERTA DE LAS MAGNITUDES ────────────────────────────────────────
     §32.b: ninguna geometría que represente una cantidad medida puede
     animarse en la dimensión que porta esa cantidad. Estos son los objetos
     que PORTAN el dato. GSAP no los toca nunca — ni su largo, ni su opacidad,
     ni nada: el fundido de entrada cuelga de la PISTA que los contiene, que
     es lo que ya hace la hoja de estilos, y así el objeto medido contesta
     `animationName: none` y no tiene ni un estilo en línea que interpretar.

     `.mrow-dot` NO está en esta lista y es la única excepción razonada: en un
     gráfico de puntos la POSICIÓN es el valor, y el punto aparece siempre en
     su posición final. Lo que se anima es su TAMAÑO en el lugar, que §32.b
     autoriza explícitamente. Su centro no se mueve nunca. */
  var MAGNITUDES = [
    '.gauge-fill', '.gauge-pin', '.gauge-cut',
    '.find-fill', '.find-cut',
    '.ece-fill', '.tally-fill', '.mrow-ic',
    '.finding-bar > span'
  ].join(',');

  /* El elemento ES el objeto que porta el dato. No se toca, nunca, con
     ninguna propiedad. */
  function esMagnitud(el) {
    return !!(el && el.matches && el.matches(MAGNITUDES));
  }

  /* El elemento CONTIENE un objeto que porta un dato. Acá la regla no es «no
     se toca» sino una más fina, y es la que la hoja de estilos viene
     aplicando desde §32.b: SE PUEDE FUNDIR, NO SE PUEDE MOVER NI ESCALAR.

     La opacidad de un ancestro no cambia ni un píxel de la geometría del
     relleno que mide: el borde que marca el valor queda donde está y el
     ancho medido es idéntico en el primer cuadro y en el reposo. Un
     `scale`, en cambio, cambia el ancho RENDERIZADO del relleno, que es
     exactamente lo que compara la sonda de `verificar_sala_limpia.py`. Y un
     `y` no cambia el ancho pero mueve una medición por la pantalla, que es
     movimiento sin nada que comunicar.

     Por eso las filas de hallazgos entran sólo con opacidad, y por eso no
     hace falta acordarse: la puerta les saca la geometría sola. */
  var GEOMETRIA = ['x', 'y', 'xPercent', 'yPercent', 'scale', 'scaleX',
                   'scaleY', 'rotation', 'skewX', 'skewY', 'width', 'height'];

  function llevaMagnitud(el) {
    return !!(el && el.querySelector && el.querySelector(MAGNITUDES));
  }

  /* Filtro único por el que pasa TODO lo que este archivo anima. Descarta lo
     intocable, separa lo que sólo puede fundirse, y avisa por consola: si
     mañana alguien agrega una animación sobre una pieza protegida se entera
     en el momento, y no en el informe del tribunal. */
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

  /* Compatibilidad hacia adentro del archivo: donde sólo hace falta la lista
     de lo que se puede tocar con una propiedad que ya es un fundido. */
  function bloques(sel, raiz) {
    var r = repartir(sel, raiz);
    return r.libres.concat(r.soloFundido);
  }

  /* ══════════════════════════════════════════════════════════════════════
     B. §40 · EL ENCENDIDO — el instrumento se enciende alrededor del dato
     ══════════════════════════════════════════════════════════════════════

     Un bloque se asienta: 6 px y opacidad, 260 ms, `expo.out`. Seis píxeles
     no es una entrada, es un ASIENTO — la diferencia entre «esto llegó
     volando» y «esto terminó de encenderse». Nada viaja desde afuera de la
     pantalla, nada escala, nada rebota: es un instrumento médico.

     El escalonado es de 55 ms, que a cuatro bloques da 165 ms de reparto:
     alcanza para que se lea el ORDEN (que es el orden de lectura) y no
     alcanza para que nadie espere.

     La frecuencia manda: abrir una pantalla pasa muchas veces por guardia, y
     a esa frecuencia el movimiento tiene que ser casi imperceptible. Por eso
     el encendido entero termina antes de los 450 ms y por eso NO hay ninguna
     pantalla con más de cinco bloques. */

  function mezclar(base, extra) {
    var v = {}, k;
    for (k in base) if (base.hasOwnProperty(k)) v[k] = base[k];
    if (extra) for (k in extra) if (extra.hasOwnProperty(k)) v[k] = extra[k];
    return v;
  }

  function asentar(sel, raiz, extra) {
    var r = repartir(sel, raiz);
    /* `clearProps` NO es cosmético. Un `from` de GSAP deja el valor final
       escrito en el estilo EN LÍNEA del elemento, y un estilo en línea le
       gana a cualquier regla de la hoja. Sin limpiarlo, un
       `opacity: 1` en línea sobre una fila de hallazgo bloquearía para
       siempre el atenuado de §35 («cuando hay uno resaltado, los demás bajan
       la voz»): el encendido de la página habría roto la interacción más
       importante del visor. Se limpia y la hoja vuelve a mandar. */
    var base = { autoAlpha: 0, y: 6, duration: D_BLOQUE, ease: E_ASENTAR,
                 stagger: 0.055, clearProps: 'opacity,visibility,transform' };
    var vars = mezclar(base, extra);

    if (r.libres.length) gsap.from(r.libres, vars);

    /* Los que llevan una magnitud adentro entran con las MISMAS duración,
       curva y escalonado —para que el encendido se lea como un solo gesto—
       pero sin una sola propiedad de geometría. */
    if (r.soloFundido.length) {
      var quietas = mezclar(vars, null);
      GEOMETRIA.forEach(function (p) { delete quietas[p]; });
      quietas.autoAlpha = 0;
      gsap.from(r.soloFundido, quietas);
    }
  }

  /* ══════════════════════════════════════════════════════════════════════
     C. LA PLACA EN LECTURA — el overlay de inferencia
     ══════════════════════════════════════════════════════════════════════

     Es el momento narrativo del sistema y el único donde el presupuesto de
     movimiento es grande, por una razón de producto y no de gusto: el médico
     YA ESTÁ ESPERANDO. Acá el movimiento no le cuesta tiempo a nadie — es lo
     único que hay mientras el modelo corre en CPU, que puede ser medio minuto.

     Lo que NO cambia, porque es la honestidad de la pantalla: el barrido es
     CÍCLICO E INDETERMINADO. No hay porcentaje ni barra que se llene, porque
     el backend no reporta progreso y fingirlo sería inventar estado del
     sistema. Lo único cuantitativo sigue siendo el cronómetro, que es real.

     Lo que SÍ cambia, y es lo que GSAP agrega:

     1. LA TOMA DEL ENCUADRE. Antes el overlay aparecía entero y la banda ya
        estaba a mitad de camino. Ahora hay una secuencia de 520 ms: la caja
        se asienta, la cama negra se enciende, las cuatro escuadras se cierran
        sobre las esquinas y RECIÉN AHÍ arranca la primera pasada. Es la
        diferencia entre «hay una animación de espera» y «el instrumento tomó
        esta placa». Cuesta medio segundo de una espera de veinte.

     2. EL RETROCESO DEL CABEZAL. La versión en keyframes resolvía la vuelta
        de abajo hacia arriba apagando la opacidad: la banda se teletransporta
        y el fundido lo disimula. Un cabezal de lectura real no se
        teletransporta, VUELVE. Ahora la pasada baja a paso de lectura (2,4 s)
        y la cabeza sola —sin el cuerpo de luz, y tenue— sube en 0,42 s. No es
        un adorno: es sacar un artefacto que estaba tapado con un fundido, y
        de paso el ciclo pasa a leerse como una MÁQUINA (baja leyendo, vuelve
        a buscar la siguiente pasada) en vez de como un loop de spinner.

     3. UNA SOLA LÍNEA DE TIEMPO. Antes eran dos keyframes CSS con relojes
        distintos. Ahora el cuerpo y la cabeza cuelgan de la misma timeline,
        así que no pueden desincronizarse nunca. */

  function placaEnLectura() {
    var overlay = document.getElementById('progress-overlay');
    if (!overlay) return;
    var placa = overlay.querySelector('[data-scanplate]');
    var banda = overlay.querySelector('.scanplate-band');
    if (!placa || !banda) return;

    var marcas = placa.querySelectorAll('.scanplate-mark');
    var caja = overlay.querySelector('.progress-box');
    var tl = null;

    /* La banda deja de estar animada por la hoja: a partir de acá la maneja
       la timeline. Se apaga desde JS y no borrando la regla del CSS, porque
       si este archivo no corre la animación de la hoja tiene que seguir
       siendo la que haga el trabajo. */
    function tomar() {
      if (tl) { tl.restart(true); return; }
      banda.style.animation = 'none';
      /* La banda se apaga ANTES de la secuencia de encuadre. Sin esto queda
         posada arriba de la placa, quieta y encendida, durante los 420 ms que
         tarda el instrumento en tomar el encuadre: una cabeza de lectura
         detenida a la vista se lee como un sistema colgado, que es
         exactamente lo contrario de lo que esta pantalla tiene que decir. La
         cabeza aparece cuando empieza a leer, y no antes. */
      gsap.set(banda, { yPercent: -100, autoAlpha: 0 });

      tl = gsap.timeline();

      /* ── La toma del encuadre ── */
      if (caja) tl.from(caja, { autoAlpha: 0, y: 10, duration: 0.24 }, 0);
      tl.from(placa, { autoAlpha: 0, duration: 0.28 }, 0.06);
      /* Las escuadras se cierran DESDE AFUERA hacia su esquina: el encuadre
         se toma, no aparece. 10 px hacia adentro y opacidad, escalonadas
         desde el centro para que las cuatro lleguen casi juntas. */
      if (marcas.length) {
        tl.from(marcas, {
          autoAlpha: 0,
          x: function (i) { return (i === 0 || i === 2) ? -10 : 10; },
          y: function (i) { return (i === 0 || i === 1) ? -10 : 10; },
          duration: 0.3, stagger: { each: 0.04, from: 'center' }
        }, 0.16);
      }

      /* ── El ciclo de lectura ──
         `-100%` a `385%` son las mismas cotas que tenía la regla de la hoja:
         la banda entra por arriba del canto y sale por abajo. La cabeza va
         adelante del cuerpo porque es el borde inferior del degradado. */
      var ciclo = gsap.timeline({ repeat: -1 });
      ciclo
        /* LA PASADA. 2,4 s es paso de lectura: más rápido se lee como
           spinner y a la tercera pasada el ojo deja de creerle. Casi lineal,
           con asiento sólo al arranque y al final — un cabezal arranca,
           viaja parejo y frena. Las cotas (-100 % y 385 %) son las mismas
           que tenía la regla de la hoja: la banda entra por arriba del canto
           y sale por abajo. */
        .set(banda, { yPercent: -100, autoAlpha: 0 })
        .to(banda, { autoAlpha: 1, duration: 0.14, ease: 'none' }, 0)
        .to(banda, { yPercent: 385, duration: 2.4, ease: E_CABEZAL }, 0)
        .to(banda, { autoAlpha: 0, duration: 0.18, ease: 'none' }, 2.22)

        /* EL RETROCESO. Un cabezal de lectura no se teletransporta: vuelve.
           La versión en keyframes resolvía el salto de abajo hacia arriba
           apagando la opacidad — el artefacto seguía ahí, tapado con un
           fundido.

           Vuelve VISIBLE, y ésa fue la corrección: al 22 % de opacidad, que
           es como estaba primero, sobre una placa negra no se veía nada y el
           gesto no existía. Al 60 % se lee, y no compite con la pasada
           porque lo que las distingue es la VELOCIDAD: 0,44 s contra 2,4 s,
           cinco veces y media más rápido. Eso es lo que hace que se entienda
           como «volver a empezar» y no como una segunda pasada al revés.

           Y no es decoración: es lo que convierte el ciclo en PASADAS
           CONTABLES. Con un fundido en las dos puntas, el que espera no
           puede saber si está viendo un barrido continuo o el sexto de una
           serie; con el retroceso a la vista, sabe que es un proceso que se
           repite sin saber cuánto falta — que es exactamente lo que el
           sistema puede afirmar, porque el backend no reporta progreso. */
        .to(banda, { autoAlpha: 0.6, duration: 0.1, ease: 'none' }, 2.44)
        .to(banda, { yPercent: -100, duration: 0.44, ease: E_TRASLADO }, 2.44)
        .to(banda, { autoAlpha: 0, duration: 0.1, ease: 'none' }, 2.88);

      tl.add(ciclo, 0.42);
    }

    /* El overlay se abre agregando `.open` desde upload.js. Se escucha ese
       cambio en vez de tocar upload.js: la capa de movimiento se engancha a
       la que ya existe y no le agrega responsabilidades. */
    var obs = new MutationObserver(function () {
      if (overlay.classList.contains('open')) tomar();
      else if (tl) { tl.kill(); tl = null; banda.style.removeProperty('animation'); }
    });
    obs.observe(overlay, { attributes: true, attributeFilter: ['class'] });
    if (overlay.classList.contains('open')) tomar();
  }

  /* ══════════════════════════════════════════════════════════════════════
     D. EL REVELADO DEL VISOR Y EL DIBUJADO DE LAS CAJAS
     ══════════════════════════════════════════════════════════════════════

     Ésta es la pieza más importante del archivo, y la que sólo se puede hacer
     ahora que las cajas son VECTORES (§35) y no píxeles quemados en un PNG.

     Antes: la cabeza de lectura pasaba una vez y detrás de ella un
     `clip-path` DESCUBRÍA una capa que ya estaba dibujada. El gesto decía
     «acá abajo había algo». Es una cortina.

     Ahora: la cabeza de lectura pasa, y CADA CAJA SE DIBUJA EN EL MOMENTO EN
     QUE LA CABEZA CRUZA SU BORDE SUPERIOR. La caja se traza por su perímetro,
     desde el vértice de arriba a la izquierda, en 200 ms, y su número aparece
     cuando el trazo cierra. El gesto ya no dice «había algo»: dice
     ESTO ES LO QUE EL SISTEMA ENCONTRÓ, Y ACÁ ES DONDE LO ENCONTRÓ. Es la
     inferencia, vuelta a pasar delante del tribunal.

     El orden no lo elige nadie: sale de la coordenada `y1` de cada caja, o
     sea del modelo. Si dos hallazgos están a la misma altura, se dibujan
     juntos, porque la cabeza los cruza juntos.

     ── POR QUÉ ESTO NO VIOLA §32.b ─────────────────────────────────────────
     Una barra que crece desde cero muestra un largo falso al lado de un
     número verdadero. Una caja que se DIBUJA no: sus cuatro vértices están en
     su posición final desde el primer píxel de trazo, porque lo que avanza es
     el recorrido del perímetro, no la extensión del rectángulo. En ningún
     cuadro se ve una caja más chica que la detectada, ni corrida, ni en otro
     lugar. La geometría afirma siempre lo mismo que afirma el modelo.
     Y el score de cada hallazgo —que sí es una magnitud— no participa: vive
     en la barra del panel, que aparece a su largo medido y sólo se funde.

     El `pathLength="1"` normaliza el perímetro a la unidad, así que un
     `strokeDashoffset` de 1 a 0 dibuja la caja entera sea cual sea su tamaño
     y sea cual sea el zoom. Es el mismo recurso que ya usaba la curva de
     confiabilidad del panel de métricas. Lo pone el JS, nunca la hoja: si
     este archivo no corre, la caja nace entera. */

  function medioBarrido(ctx) {
    /* ctx: { viewport, img, svg, rects, scale, ty, vector } */
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

    /* La cabeza se saca del DOM con un `.call()` AL FINAL DE LA TIMELINE y
       no con un `onComplete`. La diferencia importa: si el médico toca la
       placa a mitad del revelado, viewer.js corta con `progress(1)`, y un
       `.call()` colocado en el tiempo se ejecuta igual al renderizar hasta
       ahí. Un `onComplete` además se lo pisaría cualquiera que quisiera
       engancharse al final desde afuera. */
    var tl = gsap.timeline();
    var estado = { tl: tl, linea: linea, ir: ir, vr: vr, alPasar: null };

    /* LA PASADA. Misma curva que el cabezal del overlay de inferencia: es la
       misma cabeza. Ése es todo el argumento de §32 — lo que leyó la placa es
       lo que ahora muestra lo que encontró.

       EL RECORRIDO Y EL ENCENDIDO VAN EN TWEENS SEPARADOS, y hace falta que
       así sea. Metidos en el mismo tween comparten la curva: con
       `power1.inOut` sobre los 620 ms enteros, a un tercio del camino la
       cabeza estaba al 9 % de opacidad, o sea invisible sobre una placa
       negra. La cabeza tiene que estar ENCENDIDA mientras lee — se enciende
       en 50 ms, lee, y recién se apaga al salir por el canto de abajo. */
    tl.fromTo(linea, { y: 0 }, {
      y: ir.height, duration: D_CABEZAL, ease: E_CABEZAL,
      /* La cabeza informa dónde está, cuadro por cuadro. Quien escucha decide
         qué hacer con eso: en el visor, encender las cajas que acaba de
         cruzar. */
      onUpdate: function () {
        if (estado.alPasar) estado.alPasar(gsap.getProperty(linea, 'y'));
      }
    }, 0);
    tl.fromTo(linea, { autoAlpha: 0 },
      { autoAlpha: 1, duration: 0.05, ease: 'none' }, 0);
    tl.to(linea, { autoAlpha: 0, duration: 0.14, ease: 'none' }, D_CABEZAL - 0.14);

    return estado;
  }

  /* Prepara una caja para ser dibujada y devuelve A QUÉ ALTURA DE LA PLACA
     está su borde de arriba, en los mismos píxeles en los que se mide la
     posición de la cabeza de lectura.

     LA POSICIÓN Y NO EL TIEMPO, Y ES TODA LA DIFERENCIA. La primera versión
     calculaba un retardo: «esta caja está al 44 % de la placa, o sea que se
     dibuja a los 273 ms». Está mal, y se ve: la cabeza NO viaja a velocidad
     constante —arranca, viaja parejo y frena, que es la curva del cabezal—
     así que al 44 % del tiempo no está al 44 % del recorrido. La caja se
     dibujaba antes o después de que la cabeza la cruzara, y con eso se
     pierde exactamente lo único que este gesto tiene para decir: que la
     marca es CONSECUENCIA del paso.

     Ahora no hay retardo que calcular. La cabeza informa su posición cuadro
     por cuadro y cada caja se dispara la primera vez que la cabeza le pasa
     por encima. Si mañana se cambia la curva, sigue siendo exacto. */
  function prepararCaja(rect, ctx, ir, vr) {
    var r = rect.g.querySelector('rect');
    if (!r) return null;
    /* `pathLength="1"` normaliza el perímetro a la unidad: con eso un
       `strokeDashoffset` de 1 a 0 dibuja la caja entera sea cual sea su
       tamaño y sea cual sea el zoom, sin que nadie tenga que medir el
       recorrido. Es el mismo recurso que usa la curva de confiabilidad del
       panel de métricas.
       Lo pone el JS, nunca la hoja: un `stroke-dasharray` suelto en el CSS
       dejaría la caja INVISIBLE el día que este archivo no corriera. */
    r.setAttribute('pathLength', '1');
    gsap.set(r, { strokeDasharray: 1, strokeDashoffset: 1 });
    gsap.set(rect.tag, { autoAlpha: 0 });

    /* SE MIDE, NO SE CALCULA. La primera versión traducía las coordenadas de
       imagen a pantalla a mano (`y1 * escala + ty`) y quedaba atada a cómo
       `viewer.js` arma su transform y a dónde tiene el `transform-origin`.
       Si esa cuenta se corre, las cajas se disparan a destiempo o no se
       disparan nunca — que es exactamente lo que pasó: se dibujaban todas
       juntas al final, de un salto, en vez de una por una al paso de la
       cabeza. El navegador ya sabe dónde terminó dibujada cada caja; se le
       pregunta. */
    var br = rect.g.getBoundingClientRect();
    var yPlaca = br.top - ir.top;
    return { r: r, tag: rect.tag,
             y: Math.min(ir.height, Math.max(0, yPlaca)), hecha: false };
  }

  /* ══════════════════════════════════════════════════════════════════════
     E. LA API QUE CONSUME viewer.js
     ══════════════════════════════════════════════════════════════════════
     viewer.js no sabe nada de GSAP: pregunta si hay capa de movimiento y, si
     la hay, delega. Si no la hay, hace lo que hacía antes (WAAPI y
     transiciones de la hoja). Las dos rutas están vivas y las dos se prueban.
     ══════════════════════════════════════════════════════════════════════ */

  var API = {
    activa: true,
    movimiento: MOVIMIENTO,

    /* ── EL REVELADO ──────────────────────────────────────────────────── */
    revelar: function (ctx) {
      if (!MOVIMIENTO) return null;
      var base = medioBarrido(ctx);
      if (!base) return null;
      var tl = base.tl;

      if (ctx.vector && ctx.rects && ctx.rects.length) {
        /* CON VECTORES: la cabeza pasa y va dejando las cajas dibujadas. */
        var cajas = [];
        ctx.rects.forEach(function (rc) {
          var p = prepararCaja(rc, ctx, base.ir, base.vr);
          if (p) cajas.push(p);
        });

        /* La cabeza dispara cada caja al cruzarle el borde de arriba. El
           trazo se dibuja mientras la cabeza SIGUE BAJANDO: la caja termina
           de cerrarse un poco después de que la cruzó, que es lo que hace
           que se lea como consecuencia del paso y no como algo que apareció
           al mismo tiempo. */
        base.alPasar = function (y) {
          for (var i = 0; i < cajas.length; i++) {
            var c = cajas[i];
            if (c.hecha || y < c.y) continue;
            c.hecha = true;
            gsap.to(c.r, { strokeDashoffset: 0, duration: 0.2, ease: 'none' });
            /* El número entra cuando el trazo cierra. Nunca antes: un número
               flotando sin caja es un dato sin su referencia espacial. */
            gsap.to(c.tag, { autoAlpha: 1, duration: D_ACUSE, delay: 0.2,
                             ease: E_ASENTAR });
          }
        };
        /* ── EL CIERRE: NO ALCANZA CON TERMINAR, HAY QUE DEVOLVER LA PLACA ──
           Tres cosas, y las tres hacen falta.

           1. CINTURÓN. Si el médico corta el revelado tocando la placa, o si
              algo fallara a mitad de camino, todas las cajas quedan enteras
              igual. Nunca se muestra una caja a medio trazar en reposo.

           2. EL `pathLength` SE VA. Es lo más fácil de pasar por alto y lo
              más caro: mientras está puesto, TODAS las medidas de trazo de
              ese rectángulo se leen normalizadas al perímetro. La hoja marca
              los hallazgos POR DEBAJO DEL UMBRAL con `stroke-dasharray: 6 4`
              (§35), y con `pathLength="1"` esos «6 4» pasan a valer seis
              perímetros: la caja ámbar se dibuja MACIZA y pierde el punteado,
              que es justamente el signo de que ese hallazgo no llegó al
              umbral. Sería un cambio de semántica clínica introducido por una
              animación de entrada.

           3. LOS ESTILOS EN LÍNEA SE VAN. Un `opacity: 1` en línea sobre el
              número de una caja le gana a `.boxlayer.has-hot .bx-tag
              { opacity: .32 }` y dejaría encendidos los números de las cajas
              apagadas para siempre — o sea, el revelado habría roto el
              señalamiento, que es la interacción más importante del visor.

           Se hace a mano y no con `clearProps` porque hay que sacar además un
           ATRIBUTO del SVG, que GSAP no administra. */
        var trazos = cajas.map(function (c) { return c.r; });
        var etiquetas = cajas.map(function (c) { return c.tag; });
        /* El cierre va 400 ms DESPUÉS de que la cabeza sale por el canto de
           abajo: una caja que está al pie de la placa arranca su trazo casi
           al final del recorrido y necesita ese margen para cerrarse sola.
           Sin el margen, la última caja se completaba de un salto. */
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
        /* SIN VECTORES: no hay nada que trazar, así que se conserva la figura
           vieja —el recorte que descubre la capa quemada del servidor— con la
           misma curva y la misma duración. */
        tl.fromTo(ctx.capa,
          { clipPath: 'inset(0 0 100% 0)' },
          { clipPath: 'inset(0 0 0% 0)', duration: D_CABEZAL, ease: E_CABEZAL }, 0);
        tl.set(ctx.capa, { clearProps: 'clipPath' });
      }
      /* La cabeza se retira del DOM al final del recorrido, pase lo que
         pase: termine sola o la corte la mano del médico. */
      tl.call(function () {
        if (base.linea.parentNode) base.linea.parentNode.removeChild(base.linea);
      });
      return tl;
    },

    /* ── EL ANILLO DE LOCALIZACIÓN (§39.b) ────────────────────────────────
       Se conserva íntegro el argumento que ya estaba: converge, no irradia;
       una sola pasada; color de INTERACCIÓN y no de hallazgo; y la apertura
       se mide en píxeles de PANTALLA para que a cualquier zoom sea un anillo
       reconocible y no un rectángulo cruzando media placa.

       Lo que cambia al pasar de WAAPI a GSAP es una sola cosa, y es la que
       importa: `overwrite`. Recorriendo hallazgos con N/P a ritmo de teclado,
       el anillo anterior se MATA en el acto en vez de superponerse. Antes
       había que cancelarlo a mano con un `clearTimeout` y aun así dos anillos
       podían convivir un cuadro. */
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

      /* La apertura se mide en PÍXELES DE PANTALLA, no en una fracción de la
         caja. Con una fracción fija, a 1:1 el anillo era proporcionado y al
         220 % se convertía en un rectángulo azul enorme cruzando media
         placa: dejaba de leerse como una retícula cerrándose y pasaba a
         leerse como algo que apareció. 22 px afuera es un anillo
         reconocible con cualquier caja y a cualquier zoom. */
      var afuera = Math.min(22 / (escala || 1), lado * 0.6);
      var W0 = w + 2 * afuera, H0 = h + 2 * afuera;

      /* ── SE CIERRA MOVIENDO SUS PROPIOS CANTOS, NO CON `scale` ──────────
         El anillo tiene que cerrarse CONCÉNTRICO sobre la caja: converge, no
         irradia. Un anillo que se expande parece que la caja emite algo; uno
         que se cierra es el instrumento apuntando (§39.b).

         Con `scale` eso depende de dónde esté el centro de la
         transformación, y ahí hay una trampa que costó encontrar: la hoja lo
         fija con `transform-box: fill-box` + `transform-origin: center`, que
         funciona para la ruta WAAPI porque el navegador anima la PROPIEDAD
         CSS `transform`. GSAP no escribe esa propiedad: escribe el ATRIBUTO
         `transform` del SVG, y ese atributo ignora las dos reglas. Medido, el
         anillo entraba 39 px a la izquierda y 105 px por encima del centro
         de la caja — o sea que en vez de cerrarse sobre el hallazgo se
         deslizaba en diagonal hacia él, que es exactamente el gesto
         equivocado. (`svgOrigin` tampoco lo arregló.)

         Animando los cantos del rectángulo, el centro es (cx, cy) POR
         CONSTRUCCIÓN en todos los cuadros: no hay origen que acertar, y
         medido da 0,0 px de deriva. Es un rectángulo decorativo de la capa
         de interacción, no una magnitud: acá no rige la prohibición de
         animar largos de §32.b, que habla de geometrías que representan una
         cantidad medida. Esta no mide nada — es del color de la INTERACCIÓN
         justamente para decir «vos elegiste ésta», no «acá hay una
         fractura». */
      function limpiar() { if (ring.parentNode) ring.parentNode.removeChild(ring); }

      var tl = gsap.timeline({ onComplete: limpiar, onInterrupt: limpiar });
      /* El cierre ocupa los primeros 150 ms y se VE cerrarse: con la curva
         global (un ease-out muy marcado) el anillo llegaba en 60 ms y lo
         único visible eran 280 ms de un borde apagándose, o sea nada. */
      tl.fromTo(ring,
        { attr: { x: cx - W0 / 2, y: cy - H0 / 2, width: W0, height: H0 },
          autoAlpha: 0 },
        { attr: { x: b.x1, y: b.y1, width: w, height: h },
          autoAlpha: 1, duration: 0.15, ease: 'power2.out' })
        .to(ring, { autoAlpha: 1, duration: 0.06 })
        .to(ring, { autoAlpha: 0, duration: 0.13, ease: 'none' });
      return tl;
    },

    /* ── EL VIAJE DE LA PLACA (§39.c) ─────────────────────────────────────
       Antes esto era una transición de CSS que se encendía con una clase y se
       apagaba con un `setTimeout` de 300 ms. Funcionaba, y tenía dos agujeros
       que sólo se ven con la mano encima:

       · si el médico fijaba OTRO hallazgo a mitad del viaje, la transición
         reapuntaba desde el valor computado pero el `setTimeout` viejo seguía
         corriendo y podía apagar la clase en medio del segundo viaje;
       · el recorte de la cortina viajaba en una transición PARALELA, con su
         propia curva, «clavada» sólo porque los números coincidían.

       Con un tween sobre las propiedades del visor las dos cosas se caen
       solas: `overwrite: true` reapunta desde la posición y la velocidad
       actuales, y el recorte se recalcula en cada cuadro dentro del mismo
       `onUpdate` que dibuja la placa, así que no puede despegarse ni
       aunque se quiera. */
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

    /* Cualquier gesto sobre la placa corta el viaje en seco. Nadie espera a
       una animación para empezar a trabajar. */
    frenar: function (visor) { gsap.killTweensOf(visor); },

    /* ── EL ENCENDIDO DEL PANEL DE UNA IMAGEN ─────────────────────────────
       En el estudio multi-imagen, cambiar de miniatura reemplaza la placa y
       el panel. Sin movimiento, el panel nuevo se sustituye de golpe y no
       queda claro que cambió (dos radiografías de muñeca se parecen mucho).
       El panel se asienta igual que en una carga de página: es el MISMO
       gesto, porque es la misma cosa — una lectura que llega.

       El triage no participa: la puerta del cuadro cero lo descarta, y ése es
       precisamente el punto. Al cambiar de imagen el veredicto de la imagen
       nueva está en el primer cuadro. */
    encenderPanel: function (raiz) {
      if (!MOVIMIENTO || !raiz) return null;
      /* `.find-head` y NO `.finds`: el bloque de hallazgos entero contiene
         `.find-unit` —«el score crudo no es una probabilidad de fractura»—
         que es una de las cuatro piezas del cuadro cero. Fundir el
         contenedor la habría atrasado cada vez que el médico cambia de
         imagen en un estudio. Lo atajó la puerta y se corrige acá. */
      return asentar('.rd-top, .find-head, .find-list .find, .scope, .quiet, .rd-actions',
                     raiz, { y: 4, duration: 0.22, stagger: 0.04 });
    }
  };

  window.TVMotion = API;

  /* ══════════════════════════════════════════════════════════════════════
     F. TODO LO QUE SE CREA AL ARRANCAR
     ══════════════════════════════════════════════════════════════════════
     Vive dentro del matchMedia: con `prefers-reduced-motion: reduce` nada de
     esto se ejecuta, así que no hay nada escondido que haya que destapar.
     ══════════════════════════════════════════════════════════════════════ */

  var mm = gsap.matchMedia();

  mm.add('(prefers-reduced-motion: no-preference)', function () {

    /* ── F.1 El encendido, pantalla por pantalla ────────────────────────
       Cada pantalla nombra sus bloques en orden de lectura. No hay una regla
       genérica que barra toda la página: una lista explícita por pantalla es
       lo que impide que mañana entre un bloque nuevo a la animación sin que
       nadie lo haya decidido. */

    /* Login. Es la única pantalla de la aplicación que se ve una vez por
       sesión, así que es la única donde el encendido puede ser un poco más
       largo. Sigue sin pasar de 400 ms. */
    asentar('.login-mark, .login-head, .login-card form .field-group, ' +
            '.login-card .btn-lg, .demo-panel', null, { y: 8, stagger: 0.06 });

    /* Carga. El orden es el del trabajo: primero qué se sube, después dónde
       se suelta, al final el aviso de alcance. */
    asentar('.page-header, .info-card, .dropzone, .metrics-provenance', null,
            { stagger: 0.05 });

    /* Historial. La TABLA entra como un bloque y no fila por fila: cincuenta
       filas escalonadas es una animación de portfolio, y acá son cincuenta
       registros clínicos. Lo que se escalona son los cuatro muebles. */
    asentar('.page-header, .table-controls, .table-wrap, .table-foot', null);

    /* Métricas y administración. El encabezado y los dos títulos de sección;
       lo de adentro lo maneja el ScrollTrigger de F.4, que es donde
       corresponde porque cae bajo el pliegue. */
    asentar('.dash-hero, .page-header, .ev-head, .metrics-head', null);

    /* Alcance legal y páginas de error. Un bloque, y listo. */
    asentar('.legal-list > *, .error-box', null, { stagger: 0.04 });

    /* Visor y estudio: el panel de lectura. ACÁ ESTÁ LA FIRMA.
       `.triage` no está en la lista y no podría estar aunque se lo escribiera
       —la puerta lo descartaría— así que lo que se ve es el veredicto quieto
       y encendido mientras el membrete, los hallazgos, los plegables y las
       acciones se asientan a su alrededor. */
    asentar('.rd-top, .find-head, .scope, .quiet, .rd-actions',
            null, { y: 5, stagger: 0.05 });

    /* La lista de hallazgos entra SÓLO CON OPACIDAD, sin desplazamiento.
       No es una decisión estética: cada fila contiene `.find-fill`, que es
       una magnitud, y desplazar o escalar un ancestro de una magnitud es
       exactamente lo que la herramienta de verificación mide entre el primer
       cuadro y el reposo. Con opacidad pura el ancho medido del relleno es
       idéntico en los dos. */
    asentar('.find-list .find', null,
            { y: 0, autoAlpha: 0, duration: 0.24, stagger: 0.035, delay: 0.1 });

    /* La barra del estudio multi-imagen y su tira de miniaturas.
       `:not(.study-verdict)` NO es una sutileza: el veredicto del estudio
       —«PRIORITARIO en el estudio»— está construido como una `.meta-line`
       más, así que el selector de arriba lo barría junto con la línea del
       archivo. Es una de las cuatro piezas del cuadro cero.

       Lo encontró la puerta, no yo: escrito sin el `:not`, `repartir()` lo
       descartó en tiempo de ejecución y lo avisó por consola. Ésa es
       exactamente la clase de error que la puerta existe para atajar — un
       selector razonable que se lleva puesto un veredicto sin que se note
       leyéndolo. Se corrige acá igual, para que la consola quede muda en
       operación normal y el aviso siga significando algo. */
    asentar('.study-bar-main .meta-line:not(.study-verdict), .study-tally, .filmstrip',
            null, { y: 4, stagger: 0.05 });

    /* ── F.2 La placa en lectura ─────────────────────────────────────── */
    placaEnLectura();

    /* ── F.3 La ventana de brillo y contraste ────────────────────────────
       Es un popover colgado de su botón, así que crece DESDE el botón: la
       esquina de arriba a la izquierda, que es donde está anclado. 0,96 y no
       0 — nada en el mundo real aparece de la nada — y 160 ms, que es el
       tramo de los popovers chicos.

       Se engancha por observación del atributo `hidden`, que es el que ya
       usa viewer.js: la capa de movimiento no le agrega una responsabilidad
       más al visor. */
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

    /* ── F.4 El panel de métricas ─────────────────────────────────────── */
    metricas();

    /* ── F.5 La tabla del historial ───────────────────────────────────── */
    tablaHistorial();

    /* No hace falta devolver una limpieza: `gsap.matchMedia()` revierte solo
       TODO lo que se creó adentro de este bloque —tweens y ScrollTriggers—
       cuando la consulta deja de coincidir, o sea si el médico enciende
       «reducir movimiento» sin recargar la página. Revertir deja cada
       elemento en el valor que tenía antes de la animación, que por
       construcción es el valor final. */
  });

  /* ══════════════════════════════════════════════════════════════════════
     G. EL PANEL DE MÉTRICAS — el movimiento llega cuando llega el ojo
     ══════════════════════════════════════════════════════════════════════

     ACÁ HABÍA UN DEFECTO REAL, y no de estética.

     Las entradas del panel de métricas estaban escritas como animaciones de
     CSS disparadas por la carga de la página: el intervalo de confianza, el
     punto que aterriza y —sobre todo— las casillas del recall
     (tantas como fracturas se le escapan, derivadas de MODEL_METADATA) que
     se marcan de a una para convertir «N de cada 100» en una cantidad
     enumerada.

     Todo eso pasaba en los primeros 900 ms, y TODO ESO ESTÁ BAJO EL PLIEGUE.
     Para cuando el médico llega scrolleando a la cuadrícula de fallos, el
     conteo ya ocurrió donde nadie lo vio. El argumento más importante del
     panel —cuántas fracturas se le escapan al sistema— se estaba gastando
     contra una pantalla que nadie estaba mirando.

     ScrollTrigger no está acá como efecto de scroll. Está para arreglar
     ESO: cada figura se anima cuando entra en el campo visual, una sola vez
     (`once: true`), y nunca se ata al progreso del scroll — no hay nada que
     recorra con el dedo, porque nada de esto es un paseo.

     Y la doctrina no se toca: el fundido cuelga de la PISTA (`.mrow-track`,
     `.ece-bar`, `.tally-bar`), nunca del relleno que mide; el punto crece en
     su lugar sin mover su centro; y las marcas del recall y las dos curvas siguen
     siendo keyframes de la hoja —auditables, fuera del hilo principal— a las
     que GSAP sólo les decide el CUÁNDO con una clase. */

  function alEntrar(el, hacer, cuando) {
    if (!ScrollTrigger) { hacer(); return; }
    ScrollTrigger.create({
      trigger: el,
      start: cuando || 'top 88%',
      once: true,
      onEnter: hacer
    });
    /* CINTURÓN. Si por lo que fuera el disparador no llegara a correr, a los
       2,5 s se ejecuta igual. Nada de este panel puede quedarse escondido
       esperando un scroll que tal vez no ocurra: son las métricas de
       validación del modelo. */
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
    /* Las tres filas del gráfico de puntos con bigotes. Llegan JUNTAS y no
       escalonadas: son UNA lectura que se lee comparando las tres entre sí, y
       escalonarlas dejaba dos pistas vacías al lado de su número. */
    var mrows = document.querySelector('.ev-metrics');
    if (mrows) {
      alEntrar(mrows, unaVez(mrows, function () {
        var pistas = bloques('.mrow-track', mrows);
        if (pistas.length) gsap.from(pistas, { autoAlpha: 0, duration: 0.3, ease: E_ASENTAR });
        /* El punto aterriza DENTRO del intervalo ya abierto: la incertidumbre
           está, y la medición cae adentro. Crece en su lugar —su centro no se
           mueve ni un píxel— que es lo único que §32.b autoriza para un punto
           cuya posición ES el valor. */
        var puntos = mrows.querySelectorAll('.mrow-dot');
        if (puntos.length) {
          gsap.from(puntos, {
            scale: 0.35, autoAlpha: 0, transformOrigin: 'center center',
            duration: 0.18, ease: E_ASENTAR, delay: 0.16
          });
        }
      }));
    }

    /* La cuadrícula del recall: las casillas de fallo (tantas como dice
       MODEL_METADATA) marcadas de a una. Las 100
       casillas, el número de 46 px y la frase están enteros desde el primer
       cuadro; lo que llega de a una es LA MARCA, que es la que convierte el
       número en cantidad. La clase enciende los keyframes de la hoja. */
    var waffle = document.querySelector('.ev-waffle');
    if (waffle) {
      alEntrar(waffle, unaVez(waffle, function () {
        waffle.classList.add('is-contando');
      }));
    }

    /* La proporción del uso propio de la cuenta. Misma regla: la pista. */
    document.querySelectorAll('.act-props .prop').forEach(function (p) {
      alEntrar(p, unaVez(p, function () {
        var pista = bloques('.tally-bar', p);
        if (pista.length) gsap.from(pista, { autoAlpha: 0, duration: 0.36, ease: E_ASENTAR });
      }));
    });

    /* Los tres gráficos de Chart.js. Chart.js pinta sus barras a su largo
       medido desde el primer cuadro (ver dashboard.html: la animación de la
       librería está apagada, porque hacía crecer las barras desde cero al
       lado de un eje con valores reales). Lo que entra es el LIENZO ENTERO,
       fundido: la misma figura que una pista, aplicada a un canvas. */
    document.querySelectorAll('.chart-box').forEach(function (c) {
      alEntrar(c, unaVez(c, function () {
        gsap.from(c, { autoAlpha: 0, duration: 0.34, ease: E_ASENTAR });
      }));
    });
  }

  /* ══════════════════════════════════════════════════════════════════════
     H. LA TABLA DEL HISTORIAL — que las filas viajen, no que salten
     ══════════════════════════════════════════════════════════════════════

     Ordenar por «score crudo» o filtrar por «anormales» reescribe el cuerpo
     de la tabla con `appendChild`: las filas TELETRANSPORTAN a su lugar
     nuevo. El médico que acaba de ordenar por score no tiene forma de seguir
     dónde quedó la fila que estaba mirando, y ése es justamente el momento en
     que le importa.

     Se mide dónde estaba cada fila antes del cambio y dónde quedó después, y
     se anima la diferencia. Es continuidad espacial pura: la información no
     cambia, cambia el lugar donde está, y eso es exactamente lo que el
     movimiento tiene que decir.

     240 ms y `power2.inOut` —la curva de traslado, no la de asiento— porque
     esto es un DESPLAZAMIENTO y no una entrada. Las que entran y salen por el
     filtro sólo se funden: una fila que aparece no viene de ningún lado.

     §32.b: acá no se anima ninguna magnitud. Lo que se mueve es la POSICIÓN
     de la fila. Las barras de score que viven adentro conservan su ancho
     exacto durante todo el recorrido, porque lo único que se toca es `y` y
     estas filas no cambian de tamaño al reordenarse. */

  /* CUÁNTO PUEDE VIAJAR UNA FILA. Ésta es la decisión de fondo de este
     bloque, y es la razón por la que el trabajo se hace a mano en vez de con
     el plugin Flip de GSAP, que fue la primera versión.

     Flip hace lo que promete: mide antes, mide después y anima la
     diferencia. El problema es la POLÍTICA por defecto — anima TODOS los
     desplazamientos, del tamaño que sean. Medido en esta tabla: al ordenar
     por score, una fila viajaba 778 px en 240 ms. Eso no es continuidad
     espacial, es un proyectil: nadie puede seguir con el ojo una fila que
     cruza la pantalla entera, y proyectado en un aula se lee como un error.

     La regla honesta se cae sola de para qué existe el movimiento: está
     para que el médico no PIERDA la fila que estaba mirando. Si la fila
     venía de fuera de la pantalla, no hay ninguna continuidad que preservar
     porque el ojo nunca la vio ahí. Entonces:

       · desplazamiento corto  -> la fila VIAJA (es seguible);
       · desplazamiento largo, o fila que entra de la nada -> se FUNDE.

     320 px son unas cinco filas. Es el límite en el que el ojo todavía
     puede seguir un objeto que se mueve en 240 ms sin perderlo. */
  var VIAJE_MAXIMO = 320;

  function tablaHistorial() {
    var tabla = document.getElementById('tabla');
    if (!tabla || !tabla.tBodies[0]) return;
    var cuerpo = tabla.tBodies[0];

    function visibles() {
      return Array.prototype.filter.call(cuerpo.rows, function (r) { return !r.hidden; });
    }

    window.TVFlipTabla = {
      /* ANTES del reordenamiento: dónde está cada fila. Se guarda contra la
         fila misma (un Map) y no por índice, porque el índice es
         justamente lo que va a cambiar. */
      medir: function () {
        if (!MOVIMIENTO) return null;
        var antes = new Map();
        visibles().forEach(function (r) {
          antes.set(r, r.getBoundingClientRect().top);
        });
        return antes;
      },

      /* DESPUÉS: cada fila se entera de cuánto se movió y decide. */
      animar: function (antes) {
        if (!antes || !MOVIMIENTO) return;
        var viajan = [], aparecen = [];
        visibles().forEach(function (r) {
          var y0 = antes.get(r);
          var y1 = r.getBoundingClientRect().top;
          if (y0 === undefined) { aparecen.push(r); return; }
          var d = y0 - y1;
          if (Math.abs(d) < 1) return;                 /* no se movió */
          if (Math.abs(d) > VIAJE_MAXIMO) { aparecen.push(r); return; }
          viajan.push({ el: r, d: d });
        });

        viajan.forEach(function (v) {
          /* `fromTo` desde el desplazamiento medido hasta cero: la fila sale
             de donde ESTABA y llega a donde le tocó. Es la técnica FLIP
             hecha a mano — invertir el cambio y dejar que se resuelva.
             Sólo `y`: nada de escala. Una fila que se estira cambiaría el
             ancho renderizado de la barra de score que lleva adentro, que es
             una magnitud (§32.b). */
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

  /* ══════════════════════════════════════════════════════════════════════
     I. ARRANQUE
     ══════════════════════════════════════════════════════════════════════ */

  /* Los bloques de F sólo pueden mirar el DOM cuando el DOM está. Este
     archivo va con `defer`, así que en la práctica ya está — pero el
     `readyState` cubre el caso de que alguien lo mueva. */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      if (ScrollTrigger) ScrollTrigger.refresh();
    });
  }
})();
