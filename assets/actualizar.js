/* ==========================================================================
 * Tareas desde la URL del dashboard (o escribiéndolas al final de la URL con
 * la página ya abierta):
 *
 *   #actualizar    vuelve a correr el pipeline de la numeralia; al terminar
 *                  recarga la página con los datos nuevos.
 *   #notificacion  manda el reporte diario por correo; al terminar dice si se
 *                  mandó o por qué no (ya se había enviado, datos no listos).
 *
 * Mientras corren se muestra un aviso con barra de avance y al terminar se
 * quita el #... de la URL. El lado del servidor está en
 * src/numeralia/reporte/actualizacion.py.
 * ========================================================================== */

(function () {
    var CADA_MS = 2000;
    var corriendo = false;

    function base() {
        // Dash publica su prefijo en el JSON de configuración; con nginx en
        // medio es '/reporte-diario/', en local suele ser '/'.
        try {
            var cfg = JSON.parse(document.getElementById('_dash-config').textContent);
            if (cfg.requests_pathname_prefix) { return cfg.requests_pathname_prefix; }
        } catch (e) { /* sin config: se cae al path actual */ }
        var p = window.location.pathname;
        return p.slice(0, p.lastIndexOf('/') + 1);
    }

    function quitarHash() {
        history.replaceState(null, '', window.location.pathname + window.location.search);
    }

    var ESTILOS = [
        '#aviso-actualizar{position:fixed;left:50%;top:16px;transform:translateX(-50%);',
        'z-index:10000;width:420px;max-width:calc(100vw - 32px);box-sizing:border-box;',
        'padding:12px 18px 14px;border-radius:10px;background:#1a1d24;color:#fff;',
        'font:600 14px Montserrat,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25)}',
        '#aviso-actualizar.error{background:#b42318}',
        '#aviso-actualizar .fila{display:flex;justify-content:space-between;gap:12px}',
        '#aviso-actualizar .pct{font-variant-numeric:tabular-nums;opacity:.8;white-space:nowrap}',
        '#aviso-actualizar .riel{margin-top:10px;height:6px;border-radius:3px;',
        'background:rgba(255,255,255,.18);overflow:hidden;position:relative}',
        '#aviso-actualizar .avance{height:100%;width:0;border-radius:3px;',
        'background:#2ec4b6;transition:width .8s linear}',
        /* Sin estimación todavía: una franja que va y viene. */
        '#aviso-actualizar .riel.indeterminada .avance{position:absolute;width:35%;',
        'transition:none;animation:aviso-ir-venir 1.4s ease-in-out infinite}',
        '#aviso-actualizar.error .riel{display:none}',
        '@keyframes aviso-ir-venir{0%{left:-35%}100%{left:100%}}',
        '@media (prefers-reduced-motion:reduce){#aviso-actualizar .riel.indeterminada .avance',
        '{animation:none;left:0;width:100%;opacity:.5}}'
    ].join('');

    function aviso() {
        var caja = document.getElementById('aviso-actualizar');
        if (caja) { return caja; }
        var estilo = document.createElement('style');
        estilo.textContent = ESTILOS;
        document.head.appendChild(estilo);

        caja = document.createElement('div');
        caja.id = 'aviso-actualizar';
        caja.setAttribute('role', 'status');
        caja.innerHTML =
            '<div class="fila"><span class="texto"></span><span class="pct"></span></div>' +
            '<div class="riel indeterminada" role="progressbar" aria-valuemin="0" aria-valuemax="100">' +
            '<div class="avance"></div></div>';
        document.body.appendChild(caja);
        return caja;
    }

    /* progreso: número 0-100, o null para la barra indeterminada. */
    function mostrar(texto, esError, progreso, detalle) {
        var caja = aviso();
        caja.classList.toggle('error', !!esError);
        caja.querySelector('.texto').textContent = texto;
        caja.querySelector('.pct').textContent = detalle || '';
        var riel = caja.querySelector('.riel');
        var avance = caja.querySelector('.avance');
        if (progreso === null || progreso === undefined) {
            riel.classList.add('indeterminada');
            riel.removeAttribute('aria-valuenow');
            avance.style.width = '';
        } else {
            riel.classList.remove('indeterminada');
            riel.setAttribute('aria-valuenow', String(Math.round(progreso)));
            avance.style.width = progreso + '%';
        }
    }

    function reloj(seg) {
        seg = Math.max(0, Math.round(seg || 0));
        return Math.floor(seg / 60) + ':' + String(seg % 60).padStart(2, '0');
    }

    /* Avance estimado con lo que tardó la corrida anterior. Se topa en 95%:
     * si esta vez tarda más, la barra espera ahí en vez de llegar a 100% y
     * quedarse llena sin que haya terminado. */
    function avanceEstimado(e) {
        if (!e.duracion_estimada_seg || e.transcurrido_seg === null ||
            e.transcurrido_seg === undefined) { return null; }
        return Math.min(95, 100 * e.transcurrido_seg / e.duracion_estimada_seg);
    }

    var NOMBRES = {actualizar: 'la actualización', notificacion: 'el envío del reporte'};

    /* Al terminar cada tarea: #actualizar recarga con los datos nuevos;
     * #notificacion deja el aviso con lo que respondió el servidor
     * (enviado, ya se había enviado, datos aún no listos). */
    var TAREAS = {
        actualizar: {
            corriendo: 'Actualizando la numeralia…',
            iniciando: 'Iniciando la actualización de la numeralia…',
            error: 'No se pudo actualizar la numeralia: ',
            errorFin: '. El dashboard sigue con los datos anteriores.',
            listo: function () {
                mostrar('Numeralia actualizada. Recargando…', false, 100, '100%');
                window.location.reload();
            }
        },
        notificacion: {
            corriendo: 'Mandando el reporte diario por correo…',
            iniciando: 'Iniciando el envío del reporte diario…',
            error: 'No se pudo mandar el reporte: ',
            errorFin: '.',
            listo: function (e) {
                mostrar(e.mensaje || 'Listo.', false, 100, '');
                cerrarLuego();
            }
        }
    };

    function cerrarLuego() {
        setTimeout(function () {
            var caja = document.getElementById('aviso-actualizar');
            if (caja) { caja.remove(); }
        }, 15000);
    }

    function esperar(tarea) {
        var t = TAREAS[tarea];
        fetch(base() + '_' + tarea + '/estado', {cache: 'no-store'})
            .then(function (r) { return r.json(); })
            .then(function (e) {
                if (e.estado === 'corriendo') {
                    var p = avanceEstimado(e);
                    var detalle = p === null
                        ? reloj(e.transcurrido_seg)
                        : Math.floor(p) + '% · ' + reloj(e.transcurrido_seg) +
                          ' de ~' + reloj(e.duracion_estimada_seg);
                    mostrar(t.corriendo, false, p, detalle);
                    setTimeout(function () { esperar(tarea); }, CADA_MS);
                } else if (e.estado === 'listo') {
                    corriendo = false;
                    quitarHash();
                    t.listo(e);
                } else {
                    corriendo = false;
                    quitarHash();
                    mostrar(t.error + (e.mensaje || e.estado) + t.errorFin, true);
                }
            })
            .catch(function () {
                // Un corte momentáneo (o el servidor ocupado) no cancela la espera.
                setTimeout(function () { esperar(tarea); }, CADA_MS);
            });
    }

    function iniciar() {
        var tarea = window.location.hash.slice(1);
        if (!TAREAS[tarea] || corriendo) { return; }
        corriendo = true;
        mostrar(TAREAS[tarea].iniciando);
        fetch(base() + '_' + tarea, {method: 'POST', cache: 'no-store'})
            .then(function (r) {
                if (r.status === 202) { return esperar(tarea); }
                if (r.status !== 409) { throw new Error('HTTP ' + r.status); }
                return r.json().then(function (e) {
                    if (e.ocupado_por === tarea) {
                        // La misma tarea ya corría (otra pestaña): se espera a esa.
                        esperar(tarea);
                    } else {
                        corriendo = false;
                        quitarHash();
                        mostrar('Ahora mismo está en curso ' + (NOMBRES[e.ocupado_por] || 'otra tarea') +
                                '. Vuelve a intentarlo cuando termine.', true);
                    }
                });
            })
            .catch(function (err) {
                corriendo = false;
                quitarHash();
                mostrar(TAREAS[tarea].error + err.message + '.', true);
            });
    }

    window.addEventListener('hashchange', iniciar);
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
})();
