/* ==========================================================================
 * Callbacks clientside del dashboard.
 *
 * Cada función aquí reemplaza una cadena de JavaScript que vivía dentro de
 * build_dash_app() en main.py. Se registran desde Python con:
 *
 *     from dash import ClientsideFunction
 *     app.clientside_callback(
 *         ClientsideFunction(namespace="dashboard", function_name="<nombre>"),
 *         Output(...), Input(...), ...
 *     )
 *
 * Dash carga solo cualquier .js que esté en assets/, así que este archivo no
 * necesita registrarse en ningún lado.
 *
 * Los dos valores que antes se interpolaban desde Python en la cadena de JS
 * (COLOR_GRIS y ALTO_GRAFICA_EPISODIOS) ahora llegan como datos, dentro del
 * Store 'datos-echarts-episodios': datos.gris y datos.alto_grafica.
 * ========================================================================== */

window.dash_clientside = Object.assign({}, window.dash_clientside, {
    dashboard: {

        /* ── Gráficas de episodios con ECharts ────────────────────────────
         * ECharts se carga por CDN (ver index_string) y se dibuja desde el
         * navegador, no desde Python. El renderer va en 'svg' a propósito: el
         * de canvas, que es el predeterminado, no se captura bien al generar
         * el PDF. */
        barrasEpisodios: function (datos) {
            if (!datos || typeof echarts === 'undefined') {
                return window.dash_clientside.no_update;
            }

            // Texturas por contaminante: el color queda reservado para la
            // severidad, así que los tres se distinguen por trama.
            // idxLeyenda elige de qué año toma su tono el cuadrito de la
            // leyenda: 0 = 2025 (azul marino), 1 = 2026 (aqua).
            function dibujar(idDiv, cfg, idxLeyenda, maxGlobal, animar) {
                const el = document.getElementById(idDiv);
                if (!el) { return; }

                let chart = echarts.getInstanceByDom(el);
                if (!chart) { chart = echarts.init(el, 'montserrat', {renderer: 'svg'}); }

                // Modo compacto para tablet y celular: tipografía y márgenes
                // internos más chicos, que es lo que permite bajar el alto de
                // la caja sin asfixiar los segmentos.
                //
                // Lo decide el CSS a través de la variable --modo-compacto (ver
                // assets/responsive.css), NO una medición del ancho: en
                // escritorio estas dos gráficas van en pareja y miden ~277px,
                // casi lo mismo que en tablet (~232px), así que cualquier
                // umbral de ancho agarraría también al escritorio. Ya se
                // intentó y salió mal.
                //
                // Se lee del body y no de :root para que la regla
                // .capturando-pdf pueda devolver la versión de escritorio
                // mientras se toma la foto del PDF.
                const compacta = getComputedStyle(document.body)
                                    .getPropertyValue('--modo-compacto').trim() === '1';
                el.dataset.compacta = String(compacta);

                // Todas las medidas que cambian entre los dos modos, juntas
                // para poder compararlas de un golpe de vista.
                const med = compacta
                    // gridArriba=96: título ~24px + ~30px de respiro antes del
                    // total (distancia=26). Con 350px de alto, el área de barras
                    // queda en 350-96-24 = 230px, suficiente para 3 segmentos.
                    // gridDerecha chico: los años se acercan y no queda un
                    // hueco muerto a la derecha de la barra de 2026.
                    ? {nombre: 11, valor: 14, salto: 12, total: 14, distancia: 26,
                       titulo: 13, eje: 12, gridArriba: 96, gridAbajo: 24, gridDerecha: 30}
                    : {nombre: 10, valor: 14, salto: 10, total: 17, distancia: 30,
                       titulo: 15, eje: 14, gridArriba: 88, gridAbajo: 28, gridDerecha: 34};

                // El eje lo fija el año con más episodios, así que un
                // segmento chico ocupa la misma fracción por más alta que se
                // haga la gráfica. De ahí el alto mínimo de abajo.
                const maxTotal = Math.max.apply(null, cfg.totales) || 1;
                // Escala visual: en escritorio se comparte entre Precontingencias
                // y Fase I para que las barras sean proporcionales entre gráficas.
                // En móvil y tablet (compacto) se usa la escala local: con escala
                // global, Fase I (max 21) dejaría un ~87 % de espacio vacío sobre
                // Precontingencias (max 162), que en pantalla chica es enorme.
                const POTENCIA_ESCALA = compacta ? 0.55 : 0.65;
                const totalVisual = Math.pow(maxTotal, POTENCIA_ESCALA);
                const escalaGlobalVisual = maxGlobal
                    ? Math.pow(maxGlobal, POTENCIA_ESCALA)
                    : totalVisual;
                // En compacto cada gráfica usa su propio máximo; en escritorio
                // se conserva un eje común con una diferencia visual suavizada.
                const escalaVisual = compacta ? totalVisual : escalaGlobalVisual;

                // Área vertical real donde se dibujan las barras, en píxeles.
                // Sirve para traducir "quiero un piso de N px por segmento" a
                // unidades del eje.
                const areaBarras = Math.max(
                    80, (el.clientHeight || 340) - med.gridArriba - med.gridAbajo);

                // Piso de altura por segmento: TODO episodio se ve, aunque su
                // valor sea diminuto frente al total. Es el mínimo para que
                // quepa el rótulo "Nombre: N" en una línea. Se aplica en
                // unidades del eje para no depender de barMinHeight, que ECharts
                // no respeta bien en barras apiladas.
                const pisoPx = compacta ? 30 : 36;
                const pisoVisual = escalaVisual * pisoPx / areaBarras;

                function valorVisual(valor, total) {
                    if (!valor || !total) { return null; }
                    const v = valor * (Math.pow(total, POTENCIA_ESCALA) / total);
                    return Math.max(v, pisoVisual);
                }

                // Al subir los segmentos chicos al piso, una barra apilada
                // puede rebasar escalaVisual. El eje se estira a la suma real
                // más alta (mismo valor en las dos gráficas de escritorio, que
                // comparten escala, para que la retícula siga alineada).
                const cfgsEje = compacta
                    ? [cfg]
                    : [datos.precontingencias, datos.contingencias_f1];
                let maxApilado = escalaVisual;
                cfgsEje.forEach(function (c) {
                    (c.totales || []).forEach(function (_, j) {
                        let suma = 0;
                        c.series.forEach(function (s) {
                            const val = valorVisual(s.datos[j], c.totales[j]);
                            if (val) { suma += val; }
                        });
                        if (suma > maxApilado) { maxApilado = suma; }
                    });
                });
                const escalaEje = maxApilado * 1.04;

                // Escala de referencia para la retícula punteada: es el total
                // que llena el eje entero (maxGlobal en escritorio, el máximo
                // local en compacto). La retícula es exacta para la barra de
                // ese tamaño; las barras más chicas van dibujadas un poco
                // agrandadas para que sus segmentos se lean, así que contra la
                // retícula se leen "de más" — el número exacto va rotulado
                // dentro de cada segmento. Sirve para comparar de un vistazo
                // cuánto más grande es una gráfica que la otra.
                const totalReferencia = Math.pow(escalaVisual, 1 / POTENCIA_ESCALA);
                function pasoBonito(x) {
                    if (!(x > 0)) { return 1; }
                    const base = Math.pow(10, Math.floor(Math.log10(x)));
                    const n = x / base;
                    return (n >= 5 ? 5 : n >= 2 ? 2 : 1) * base;
                }
                const pasoReal = pasoBonito(totalReferencia / 3);
                const pasoVisual = pasoReal * escalaVisual / totalReferencia;

                const series = cfg.series.map(function (s, i) {
                    return {
                        name: s.nombre,
                        type: 'bar',
                        stack: 'total',
                        // Barra ancha: deja que etiquetas como "PM2.5: 13"
                        // quepan en una línea sin encimarse y acerca las dos
                        // barras para que no quede un hueco muerto entre 2025
                        // y 2026.
                        barWidth: '72%',
                        // El piso de altura por segmento se aplica en unidades
                        // del eje (ver valorVisual / pisoVisual), no con
                        // barMinHeight, porque ECharts no lo respeta bien en
                        // barras apiladas.
                        // Este itemStyle es el que toma el cuadrito de la
                        // leyenda: lleva el tono del año que indique
                        // idxLeyenda, para que la leyenda se lea de claro a
                        // oscuro igual que la barra de ese año.
                        itemStyle: {
                            color: cfg.escalas_anio[idxLeyenda][i],
                            borderColor: cfg.colores_anio[idxLeyenda],
                            borderWidth: 1.2,
                            borderRadius: 4
                        },
                        label: {
                            show: true,
                            position: 'inside',
                            formatter: function (p) {
                                const valorReal = p.data && p.data.rawValue != null
                                    ? p.data.rawValue : p.value;
                                if (!valorReal) { return ''; }
                                // Altura real del segmento en px: con el piso
                                // aplicado, el más chico ya mide pisoPx, así que
                                // SIEMPRE hay rótulo. Solo se decide si el
                                // nombre y el número caben en una línea o dos.
                                const hPx = (p.value / escalaEje) * areaBarras;
                                if (hPx < (compacta ? 40 : 46)) {
                                    return '{n|' + s.nombre + ':}{v| ' + valorReal + '}';
                                }
                                return '{n|' + s.nombre + ':}\n{v|' + valorReal + '}';
                            },
                            // El color del texto lo decide el tono del relleno,
                            // que depende del año y del contaminante: hay tonos
                            // oscuros que piden letra blanca y claros que piden
                            // letra oscura. Aquí se usa el año de la leyenda;
                            // más abajo se reajusta por dato, que es donde se
                            // conoce el año real de cada barra.
                            rich: {
                                n: {fontSize: med.nombre, color: cfg.colores_texto_anio[idxLeyenda][i].nombre, lineHeight: med.salto, align: 'center'},
                                v: {fontSize: med.valor, fontWeight: 'bold', color: cfg.colores_texto_anio[idxLeyenda][i].valor, align: 'center'}
                            }
                        },
                        // hideOverlap NO: preferimos que dos rótulos se rocen
                        // a que uno desaparezca — el requisito es que se vean
                        // TODOS los datos. El piso de altura ya los separa.
                        labelLayout: {hideOverlap: false},
                        emphasis: {focus: 'series'}
                    };
                });

                // Serie invisible de 0 que solo carga la etiqueta del total,
                // para no meter una caja encima de la barra.
                series.push({
                    name: 'total',
                    type: 'bar',
                    stack: 'total',
                    silent: true,
                    itemStyle: {color: 'transparent'},
                    // El total va en el color de su año, para que se lea
                    // junto con la barra que corona.
                    data: cfg.totales.map(function (_, j) {
                        return {value: 0, label: {color: cfg.colores_anio[j]}};
                    }),
                    label: {
                        show: true,
                        position: 'top',
                        formatter: function (p) { return cfg.totales[p.dataIndex]; },
                        fontSize: med.total,
                        fontWeight: 'bold',
                        backgroundColor: 'transparent',
                        borderWidth: 0,
                        padding: 0,
                        // 8 px alcanzaban cuando el segmento de arriba era una
                        // astilla; con el alto mínimo, la caja sube y el total
                        // se le encimaba.
                        distance: med.distancia
                    }
                });

                // Cada segmento toma el tono que le toca dentro de la escala
                // de su año: i elige el contaminante, j elige el año.
                cfg.series.forEach(function (s, i) {
                    series[i].data = s.datos.map(function (v, j) {
                        return {
                            // null (no 0): un contaminante que no activó ningún
                            // episodio no debe ocupar el piso de altura.
                            value: valorVisual(v, cfg.totales[j]),
                            rawValue: v,
                            itemStyle: {
                                color: cfg.escalas_anio[j][i],
                                borderColor: cfg.colores_anio[j],
                                // Ozono (índice 0) con opacidad un poco menor
                                // para que se vea más clarito sin cambiar tonos.
                                opacity: i === 0 ? 0.85 : 1
                            },
                            // Todos los rótulos van adentro; solo se sobreescriben
                            // los ricos para que usen el tono correcto de SU
                            // relleno (el año real de esta barra).
                            label: {
                                rich: {
                                    n: {fontSize: med.nombre, color: cfg.colores_texto_anio[j][i].nombre, lineHeight: med.salto, align: 'center'},
                                    v: {fontSize: med.valor, fontWeight: 'bold', color: cfg.colores_texto_anio[j][i].valor, align: 'center'}
                                }
                            }
                        };
                    });
                });

                chart.setOption({
                    title: {
                        text: cfg.titulo,
                        left: 'center',
                        top: 4,
                        textStyle: {fontSize: med.titulo, fontWeight: 'bold', color: cfg.color_titulo}
                    },
                    grid: {left: 6, right: med.gridDerecha, top: med.gridArriba,
                           bottom: med.gridAbajo, containLabel: true},
                    tooltip: {
                        trigger: 'item',
                        formatter: function (p) {
                            const valor = (p.data && p.data.rawValue != null)
                                ? p.data.rawValue : p.value;
                            let html = '<b>' + p.seriesName + '</b><br/>' +
                                       p.name + ': ' + valor + ' episodios';

                            // Tercera línea: cómo se compara ESTE contaminante
                            // contra el año previo. Solo se muestra en la barra
                            // de 2026 (dataIndex 1) y solo para Ozono y PM10 —
                            // en 2025 no aplica (sería contra sí mismo) y para
                            // PM2.5 se dejó fuera a propósito. La leyenda de la
                            // barra ya da el dato crudo; lo que no se ve de un
                            // vistazo es la variación, y es lo que se busca al
                            // pasar el mouse.
                            const CONTAM_CON_PCT = ['Ozono', 'PM10'];
                            const serie = cfg.series[p.seriesIndex];
                            if (serie && p.dataIndex === 1 &&
                                CONTAM_CON_PCT.indexOf(p.seriesName) !== -1) {
                                const anioPrevio = cfg.anios[0];
                                // Base = año previo (2025). El porcentaje es la
                                // brecha entre años como fracción de ese año.
                                const base = serie.datos[0] || 0;
                                let comp;
                                if (!base) {
                                    // Sin base no hay porcentaje: dividir entre 0
                                    // daría Infinity y "∞% menos" no dice nada.
                                    comp = 'sin episodios en ' + anioPrevio;
                                } else if (valor === base) {
                                    comp = 'igual que en ' + anioPrevio;
                                } else {
                                    const pct = Math.abs(valor - base) / base * 100;
                                    // Un decimal solo por debajo de 10 %, donde
                                    // redondear a entero borra la diferencia.
                                    const txt = pct < 10
                                        ? pct.toFixed(1).replace(/\.0$/, '')
                                        : String(Math.round(pct));
                                    comp = txt + '% ' + (valor > base ? 'más' : 'menos') +
                                           ' comparado al ' + anioPrevio;
                                }
                                html += '<br/>' + comp;
                            }
                            return html;
                        }
                    },
                    legend: {show: false},
                    xAxis: {
                        type: 'category',
                        data: cfg.anios,
                        axisLine: {show: false},
                        axisTick: {show: false},
                        axisLabel: {
                            fontSize: med.eje, fontWeight: 'bold',
                            // Cada año en su color, igual que el encabezado
                            // de la tabla comparativa.
                            color: function (valor, indice) {
                                return cfg.colores_anio[indice] || datos.gris;
                            }
                        }
                    },
                    // Mismo eje (0 a escalaVisual) en Precontingencias y Fase I:
                    // así las barras son proporcionales entre categorías. La
                    // retícula punteada aterriza a la misma altura en las dos
                    // gráficas, de modo que se ve de un vistazo cuánto más
                    // grande es una que la otra. Los rótulos van en episodios
                    // reales de la escala de referencia (ver totalReferencia).
                    yAxis: {
                        type: 'value',
                        max: escalaEje,
                        min: 0,
                        interval: pasoVisual,
                        axisLine: {show: false},
                        axisTick: {show: false},
                        axisLabel: {
                            show: true,
                            showMinLabel: false,
                            showMaxLabel: false,
                            fontSize: Math.max(9, med.eje - 3),
                            color: datos.gris,
                            formatter: function (v) {
                                return Math.round(v * totalReferencia / escalaVisual);
                            }
                        },
                        splitLine: {
                            show: true,
                            lineStyle: {type: 'dashed', color: datos.gris,
                                        opacity: 0.4, width: 1}
                        }
                    },
                    series: series,
                    animationDuration: animar === false ? 0 : 600
                }, true);

                chart.resize();
            }

            // Escala compartida entre Precontingencias y Fase I para que las
            // barras sean proporcionales entre categorías.
            const maxGlobalEpisodios = Math.max(
                Math.max.apply(null, datos.precontingencias.totales) || 1,
                Math.max.apply(null, datos.contingencias_f1.totales) || 1
            );

            // Precontingencias con la leyenda en el azul de 2025 y Fase I con
            // la de 2026, para comparar las dos lecturas lado a lado.
            dibujar('echart-precontingencias', datos.precontingencias, 0, maxGlobalEpisodios);
            dibujar('echart-contingencias-f1', datos.contingencias_f1, 1, maxGlobalEpisodios);

            // El callback del PDF necesita rehacer estas gráficas en su versión
            // de escritorio ANTES de fotografiarlas, y 'dibujar' vive en este
            // cierre. Se expone para que pueda llamarla y esperarla, en vez de
            // disparar un 'resize' y adivinar cuánto tarda.
            window.__redibujarEpisodios = function (animar) {
                dibujar('echart-precontingencias', datos.precontingencias, 0, maxGlobalEpisodios, animar);
                dibujar('echart-contingencias-f1', datos.contingencias_f1, 1, maxGlobalEpisodios, animar);
            };

            // ECharts no se reajusta solo al cambiar el tamaño de la ventana:
            // conserva las medidas que tenía al inicializarse y el SVG se
            // deforma. Este listener le pide recalcular en cada resize. La
            // bandera evita registrarlo varias veces.
            //
            // resize() reajusta medidas pero NO vuelve a aplicar la opción, y
            // la opción sí depende del modo compacto (tipografías, márgenes,
            // barMinHeight). Así que al cruzar el breakpoint hay que redibujar;
            // mientras no se cruce basta con reajustar, que es mucho más barato
            // y no reinicia la animación.
            if (!window.__echartsResizeBound) {
                window.__echartsResizeBound = true;
                window.addEventListener('resize', function () {
                    const modo = getComputedStyle(document.body)
                                    .getPropertyValue('--modo-compacto').trim() === '1';
                    const graficas = [
                        ['echart-precontingencias', datos.precontingencias, 0],
                        ['echart-contingencias-f1', datos.contingencias_f1, 1]
                    ];
                    graficas.forEach(function (g) {
                        const el = document.getElementById(g[0]);
                        if (!el) { return; }
                        const instancia = echarts.getInstanceByDom(el);
                        if (!instancia) { return; }
                        if (el.dataset.compacta !== String(modo)) {
                            dibujar(g[0], g[1], g[2], maxGlobalEpisodios);
                        } else {
                            instancia.resize();
                        }
                    });
                });
            }

            return window.dash_clientside.no_update;
        },

        /* ── Acordeón de la tabla comparativa de episodios ────────────────
         * Los grupos 1 (Precontingencias) y 2 (Contingencias Fase I) tienen
         * sub-filas en la tabla; el toggle alterna display:none ↔
         * table-row-group y rota la flecha ▶ ↔ ▼. Usa paridad de n_clicks:
         * impar=abierto, par=cerrado. */
        toggleAcordeonEpisodios: function (n1, n2) {
            const abierto  = 'table-row-group';
            const cerrado  = 'none';
            const toggle   = (n) => ({display: ((n || 0) % 2 === 1) ? abierto : cerrado});
            const flecha   = (n) => ((n || 0) % 2 === 1) ? '▼' : '▶';
            return [toggle(n1), toggle(n2), flecha(n1), flecha(n2)];
        },

        /* ── Barras horizontales Alertas / Emergencias ───────────────────
         * Mismo estilo visual que las gráficas de episodios: esquinas
         * redondeadas, borde del color del año, rich text con nombre + valor
         * en tamaños distintos, y labelLayout: hideOverlap para segmentos
         * angostos. Dos barras, una por año. Tono tenue = Alertas; tono
         * pleno = Emergencias. */
        barrasAlertas: function (datos) {
            if (!datos || typeof echarts === 'undefined') {
                return window.dash_clientside.no_update;
            }

            const compacta = getComputedStyle(document.body)
                                  .getPropertyValue('--modo-compacto').trim() === '1';
            const fAnio   = compacta ? 10 : 13;
            const fNombre = compacta ?  8 : 11;
            const fValor  = compacta ? 10 : 14;

            function dibujar(divId, anio,
                             valorA, valorE,
                             colorA, colorE,
                             textoA, textoE, maxTotal, previo) {
                const el = document.getElementById(divId);
                if (!el) return;
                let c = echarts.getInstanceByDom(el);
                if (!c) c = echarts.init(el, 'montserrat', {renderer: 'svg'});

                const total = (valorA || 0) + (valorE || 0) || 1;

                // Tooltip solo para la barra que recibe 'previo' (la de 2026):
                // muestra, por segmento, la variación contra el año anterior,
                // con ese año como base —misma cuenta que el tooltip de las
                // barras de episodios—. Para 2025 no se pasa 'previo' y la
                // gráfica va sin tooltip, como antes.
                const anioPrevio = String((+anio) - 1);
                const tooltip = previo
                    ? {
                        trigger: 'item',
                        formatter: function (p) {
                            const nombre = p.seriesIndex === 0 ? 'Alertas' : 'Emergencias';
                            const valor  = p.value || 0;
                            let html = '<b>' + nombre + '</b><br/>' +
                                       anio + ': ' + valor + ' eventos';
                            const base = previo[p.seriesIndex] || 0;
                            let comp;
                            if (!base) {
                                comp = 'sin registro en ' + anioPrevio;
                            } else if (valor === base) {
                                comp = 'igual que en ' + anioPrevio;
                            } else {
                                const pct = Math.abs(valor - base) / base * 100;
                                const txt = pct < 10
                                    ? pct.toFixed(1).replace(/\.0$/, '')
                                    : String(Math.round(pct));
                                comp = txt + '% ' + (valor > base ? 'más' : 'menos') +
                                       ' comparado al ' + anioPrevio;
                            }
                            return html + '<br/>' + comp;
                        }
                    }
                    : {show: false};
                // Segmentos con menos del 20 % del total muestran solo el número;
                // los demás muestran nombre + número (aunque el nombre se corte).
                // En escritorio el umbral baja al 12 % porque la barra es más ancha.
                const fracEstrecha = compacta ? 0.20 : 0.12;

                c.setOption({
                    // La animación tiene que estar PRENDIDA para que el
                    // atenuado al pasar el cursor (emphasis.focus + el foco
                    // cruzado entre años) haga una transición suave en vez de
                    // un salto seco: ECharts apaga 'stateAnimation' junto con
                    // 'animation'. Lo que no queremos es que las barras
                    // vuelvan a crecer en cada redibujo (resize, PDF), así que
                    // la animación de datos se deja en 0 y solo se anima el
                    // cambio de estado, igual que la gráfica de episodios.
                    animation: true,
                    animationDuration: 0,
                    animationDurationUpdate: 0,
                    stateAnimation: {duration: 300, easing: 'cubicOut'},
                    tooltip: tooltip,
                    grid: {top: 8, bottom: 8, left: 8, right: 34, containLabel: true},
                    xAxis: {type: 'value', show: false, max: maxTotal},
                    yAxis: {
                        type: 'category',
                        data: [anio],
                        axisLabel: {color: colorE, fontWeight: 'bold', fontSize: fAnio},
                        axisTick: {show: false},
                        axisLine: {show: false}
                    },
                    series: [
                        {
                            // Alertas – segmento izquierdo
                            type: 'bar', stack: 'total',
                            data: [valorA],
                            barWidth: '72%',
                            barMinHeight: 20,
                            itemStyle: {
                                color: colorA,
                                borderColor: colorE,
                                borderWidth: 1.2,
                                borderRadius: 4
                            },
                            label: {
                                show: !!valorA,
                                position: 'inside',
                                formatter: function(p) {
                                    if (!p.value) return '';
                                    if (p.value / total < fracEstrecha) {
                                        return '{v|' + p.value + '}';
                                    }
                                    return '{n|Alertas}\n{v|' + p.value + '}';
                                },
                                rich: {
                                    n: {fontSize: fNombre, color: textoA, lineHeight: 12, align: 'center'},
                                    v: {fontSize: fValor, fontWeight: 'bold', color: textoA, align: 'center'}
                                }
                            },
                            emphasis: {focus: 'series'}
                        },
                        {
                            // Emergencias – segmento derecho
                            type: 'bar', stack: 'total',
                            data: [valorE],
                            barWidth: '72%',
                            barMinHeight: 20,
                            itemStyle: {
                                color: colorE,
                                borderColor: colorE,
                                borderWidth: 1.2,
                                borderRadius: 4
                            },
                            label: {
                                show: !!valorE,
                                position: 'inside',
                                formatter: function(p) {
                                    if (!p.value) return '';
                                    if (p.value / total < fracEstrecha) {
                                        return '{v|' + p.value + '}';
                                    }
                                    return '{n|Emergencias}\n{v|' + p.value + '}';
                                },
                                rich: {
                                    n: {fontSize: fNombre, color: textoE, lineHeight: 12, align: 'center'},
                                    v: {fontSize: fValor, fontWeight: 'bold', color: textoE, align: 'center'}
                                }
                            },
                            emphasis: {focus: 'series'}
                        }
                    ]
                });
                c.resize();

                // Total pegado al final de la barra.
                const px = c.convertToPixel({xAxisIndex: 0, yAxisIndex: 0}, [total, anio]);
                if (px) {
                    c.setOption({
                        graphic: [{
                            type: 'text',
                            left: px[0] + 6,
                            top: px[1],
                            style: {
                                text: String(total),
                                fill: anio === '2026' ? colorE : '#173d4c',
                                fontSize: fValor,
                                fontWeight: 'bold',
                                textVerticalAlign: 'middle'
                            },
                            z: 10
                        }]
                    });
                }
            }

            const total25 = (datos.alertas_25 || 0) + (datos.emergencias_25 || 0);
            const total26 = (datos.alertas_26 || 0) + (datos.emergencias_26 || 0);
            const maxTotal = Math.max(total25, total26) * 1.15;

            dibujar('echart-barras-alertas-25', '2025',
                    datos.alertas_25, datos.emergencias_25,
                    datos.color_a25, datos.color_e25,
                    datos.texto_a25, datos.texto_e25, maxTotal);
            dibujar('echart-barras-alertas-26', '2026',
                    datos.alertas_26, datos.emergencias_26,
                    datos.color_a26, datos.color_e26,
                    datos.texto_a26, datos.texto_e26, maxTotal,
                    [datos.alertas_25, datos.emergencias_25]);

            // Foco cruzado entre las dos barras (2025 y 2026), que son
            // instancias de ECharts distintas: al posar el cursor sobre
            // "Alertas" en cualquiera de las dos, se resalta "Alertas" y se
            // atenúan las "Emergencias" en AMBOS años, y viceversa. Replica el
            // emphasis.focus:'series' de las barras de episodios, que ahí
            // funciona solo porque los dos años viven en la misma gráfica.
            function enlazarFocoAlertas() {
                const a = echarts.getInstanceByDom(
                    document.getElementById('echart-barras-alertas-25'));
                const b = echarts.getInstanceByDom(
                    document.getElementById('echart-barras-alertas-26'));
                if (!a || !b) { return; }
                [[a, b], [b, a]].forEach(function (par) {
                    const origen = par[0], espejo = par[1];
                    origen.off('mouseover');
                    origen.off('mouseout');
                    origen.on('mouseover', function (p) {
                        if (p.seriesIndex == null) { return; }
                        espejo.dispatchAction({type: 'highlight', seriesIndex: p.seriesIndex});
                    });
                    origen.on('mouseout', function () {
                        espejo.dispatchAction({type: 'downplay'});
                    });
                });
            }
            enlazarFocoAlertas();

            window.removeEventListener('resize', window.__alertasResizeHandler);
            window.__alertasResizeHandler = function () {
                ['echart-barras-alertas-25', 'echart-barras-alertas-26'].forEach(function (id) {
                    const inst = echarts.getInstanceByDom(document.getElementById(id));
                    if (inst) { inst.resize(); }
                });
                dibujar('echart-barras-alertas-25', '2025',
                        datos.alertas_25, datos.emergencias_25,
                        datos.color_a25, datos.color_e25,
                        datos.texto_a25, datos.texto_e25, maxTotal);
                dibujar('echart-barras-alertas-26', '2026',
                        datos.alertas_26, datos.emergencias_26,
                        datos.color_a26, datos.color_e26,
                        datos.texto_a26, datos.texto_e26, maxTotal,
                        [datos.alertas_25, datos.emergencias_25]);
                enlazarFocoAlertas();
            };
            window.addEventListener('resize', window.__alertasResizeHandler);

            return window.dash_clientside.no_update;
        },

        /* ── Serie mensual: cintillo de pastillas solo si hay ancho ──────
         * Las pastillas se dibujan con el ancho en unidades de categoría y el
         * alto en fracción del lienzo, así que al angostarse la gráfica el
         * ancho encoge y el alto no: en un teléfono quedan de 5 px de ancho
         * por 33 de alto, con un número de dos dígitos encima. En vez de
         * deformarlas se quitan, y el dato se sigue consultando al tocar cada
         * punto.
         *
         * Se adapta aquí y no en Python porque el servidor no sabe el ancho de
         * la pantalla; y se hace clientside para no pagar un viaje al servidor
         * cada vez que alguien gira el teléfono. */
        cintilloSerieMensual: function (figuraBase) {
            if (!figuraBase) { return window.dash_clientside.no_update; }

            // Umbral propio de esta gráfica, distinto de los 768px del resto
            // del layout: aquí no manda el acomodo de las tarjetas sino la
            // geometría de la pastilla. Con C = ancho del contenedor y N meses
            // en el eje, la pastilla (0.24 categorías) mide
            // 0.24 × (C − 80) / N píxeles. Un número de dos dígitos a 13px
            // pide ~18px, de donde C ≥ 75 × N + 80.
            //
            // El número de meses es dinámico: crece de 1 a 12 conforme se van
            // capturando registros en 2026. Por eso el umbral se calcula aquí
            // a partir del categoryarray de la figura, en vez de fijarse a 980
            // (que era el valor para los 12 meses de un año completo).
            const nMeses = (figuraBase.layout && figuraBase.layout.xaxis &&
                            figuraBase.layout.xaxis.categoryarray)
                           ? figuraBase.layout.xaxis.categoryarray.length
                           : 12;
            const ANCHO_MINIMO_CINTILLO = 75 * nMeses + 80;

            // Se mide el contenedor y no la ventana por dos razones: es lo que
            // de verdad fija el tamaño de la pastilla, y durante la captura
            // del PDF el layout se ensancha a 1280px SIN que la ventana
            // cambie. Con window.innerWidth, un PDF descargado desde el
            // celular se iría sin cintillo.
            // El cintillo también necesita ALTO: su margen superior se lleva
            // 95px fijos, así que en una caja baja no cabe ni con ancho de
            // sobra. Sin esta guarda, el PDF sacado de un celular salía con la
            // gráfica achatada (ancho forzado a 1280 pero alto compacto).
            const ALTO_MINIMO_CINTILLO = 300;

            function anchoGrafica() {
                const el = document.getElementById('grafico-serie-mensual');
                // En el primer dibujo el nodo puede no estar medido todavía;
                // ahí se cae a la ventana, que peca de ancha y conserva el
                // cintillo en vez de quitarlo de más.
                return (el && el.clientWidth) ? el.clientWidth : window.innerWidth;
            }

            function altoGrafica() {
                const el = document.getElementById('grafico-serie-mensual');
                return (el && el.clientHeight) ? el.clientHeight : 999;
            }

            function cabeElCintillo() {
                return anchoGrafica() >= ANCHO_MINIMO_CINTILLO
                       && altoGrafica() >= ALTO_MINIMO_CINTILLO;
            }

            // El listener de abajo necesita la última figura buena; el
            // refresco periódico la reemplaza cada media hora.
            window.__serieBase = figuraBase;

            function adaptar(fig) {
                // Copia profunda: la figura del Store no se toca, porque es la
                // que se vuelve a usar cuando la pantalla se ensancha.
                const copia = JSON.parse(JSON.stringify(fig));
                if (cabeElCintillo()) { return copia; }

                copia.layout.shapes = [];
                copia.layout.annotations = [];
                // El margen superior de 95 px existía para dejarle lugar al
                // cintillo; sin él es un hueco. Y la leyenda vivía en y=1.30,
                // o sea arriba del cintillo: si solo se recorta el margen,
                // queda fuera del lienzo.
                copia.layout.margin = {l: 46, r: 12, t: 34, b: 50};
                copia.layout.legend = Object.assign({}, copia.layout.legend,
                                                    {y: 1.10, x: 0.5, xanchor: 'center'});
                return copia;
            }

            if (!window.__serieResizeBound) {
                window.__serieResizeBound = true;
                let cabiaAntes = cabeElCintillo();
                window.addEventListener('resize', function () {
                    const cabeAhora = cabeElCintillo();
                    // Solo al cruzar el umbral: redibujar en cada píxel del
                    // arrastre es caro y no cambia nada.
                    if (cabeAhora === cabiaAntes) { return; }
                    cabiaAntes = cabeAhora;
                    window.dash_clientside.set_props(
                        'grafico-serie-mensual',
                        {figure: adaptar(window.__serieBase)});
                });
            }

            return adaptar(figuraBase);
        },

        /* ── Mapa: menos zoom en celular ─────────────────────────────────
         * El zoom de 10.3 con el que se genera el mapa (ver _fig_mapa) se
         * pensó para el ancho de escritorio; en un teléfono, con la mitad del
         * espacio, se ve demasiado cerca y cuesta ubicar las estaciones entre
         * sí. Se ajusta aquí y no en Python porque el servidor no sabe el
         * ancho de la pantalla.
         *
         * Solo aplica en celular (<= 767px), no en tablet: en tablet el mapa
         * ya se ve bien tal cual. Por eso se compara contra window.innerWidth
         * en vez de reusar '--modo-compacto', que se enciende también en
         * tablet.
         *
         * No afecta al PDF: la imagen del mapa que va en el PDF es la que
         * genera Python con kaleido (ver 'mapa-estatico'), siempre al zoom de
         * escritorio, y no pasa por este callback. */
        mapaZoom: function (_disparo) {
            const UMBRAL_CELULAR = 767;
            const ZOOM_ESCRITORIO = 10.3;
            const ZOOM_CELULAR = 9.3;

            function esCelular() { return window.innerWidth <= UMBRAL_CELULAR; }

            // dcc.Graph carga plotly.js de forma diferida, y el estilo del
            // mapa base ('carto-positron') termina de cargar de forma
            // asíncrona AÚN DESPUÉS de que el nodo ya tiene '_fullLayout'.
            // Llamar 'relayout' antes de tiempo truena de varias maneras
            // ("Cannot read properties of undefined (reading '_guiEditing')",
            // "Style is not done loading") y la última pasa DENTRO de una
            // promesa interna de Plotly que nosotros no controlamos, así que
            // ni el try/catch ni el .catch() de la promesa que devuelve
            // relayout() la atrapan — sale como "Uncaught (in promise)" pase
            // lo que pase del lado de acá.
            //
            // La única forma confiable de no pisarle el mandado es preguntarle
            // al mapa mismo (MapLibre GL, que es quien dibuja 'map'/'scattermap')
            // si ya terminó de cargar su estilo, con isStyleLoaded(). Mientras
            // no lo confirme, no se llama a relayout.
            let intentos = 0;
            function nodoMapa() {
                const cont = document.getElementById('mapa-grafico');
                if (!cont) { return null; }
                return cont._fullLayout ? cont : cont.querySelector('.js-plotly-plot');
            }
            function mapaListo() {
                const gd = nodoMapa();
                if (!gd || !gd._fullLayout || !gd._fullLayout.map) { return null; }
                const subplot = gd._fullLayout.map._subplot;
                const mapaInterno = subplot && subplot.map;
                if (!mapaInterno || typeof mapaInterno.isStyleLoaded !== 'function') {
                    return null;
                }
                try {
                    return mapaInterno.isStyleLoaded() ? gd : null;
                } catch (e) {
                    return null;
                }
            }
            function ajustar() {
                if (typeof Plotly === 'undefined') {
                    if (intentos++ < 60) { setTimeout(ajustar, 150); }
                    return;
                }
                const gd = mapaListo();
                if (!gd) {
                    if (intentos++ < 60) { setTimeout(ajustar, 150); }
                    return;
                }
                const zoom = esCelular() ? ZOOM_CELULAR : ZOOM_ESCRITORIO;
                try {
                    Plotly.relayout(gd, {'map.zoom': zoom});
                } catch (e) {
                    // El estilo pudo haberse invalidado justo entre el check
                    // y la llamada (p. ej. la pestaña volvió de segundo plano).
                    // No vale la pena insistir a fuerza: se deja el zoom como
                    // esté y se reintenta en el próximo 'resize'.
                    console.warn('mapaZoom: relayout fallo', e);
                }
            }

            if (!window.__mapaResizeBound) {
                window.__mapaResizeBound = true;
                let eraCelularAntes = esCelular();
                window.addEventListener('resize', function () {
                    const esCelularAhora = esCelular();
                    // Solo al cruzar el umbral, igual que con el cintillo de
                    // la serie mensual: no hace falta redibujar en cada
                    // píxel del arrastre.
                    if (esCelularAhora === eraCelularAntes) { return; }
                    eraCelularAntes = esCelularAhora;
                    intentos = 0;
                    ajustar();
                });
            }

            // Al montar: en escritorio no hay nada que ajustar (ver arriba).
            if (esCelular()) { ajustar(); }
            return window.dash_clientside.no_update;
        },

        /* ── PDF del dashboard: captura y descarga directa ───────────────
         * html2canvas fotografía el DOM y jsPDF arma el archivo, así el clic
         * descarga el PDF sin pasar por el diálogo de impresión.
         *
         * Cada bloque 'pdf-pagina-N' se captura por separado y ocupa una
         * hoja, escalado para caber completo. Así el corte entre páginas cae
         * donde queremos y no a la mitad de una tarjeta, y el mapa se reduce
         * solo lo necesario para el PDF sin afectar la pantalla.
         *
         * Antes de capturar hay que convertir las gráficas a imagen:
         * html2canvas no sabe leer el canvas WebGL de Plotly (el mapa saldría
         * en blanco) ni rasteriza confiablemente el SVG de ECharts.
         *
         * datosEcharts llega del Store 'datos-echarts-episodios' (State):
         * datosEcharts.alto_grafica trae lo que antes se interpolaba desde
         * Python como ALTO_GRAFICA_EPISODIOS. */
        descargarPdf: async function (n_clicks, datosEcharts) {
            if (!n_clicks) { return window.dash_clientside.no_update; }
            if (typeof html2canvas === 'undefined' || typeof jspdf === 'undefined') {
                alert('No se pudieron cargar las librerias de PDF. Revisa tu conexion.');
                return window.dash_clientside.no_update;
            }

            const altoGraficaEpisodios = (datosEcharts && datosEcharts.alto_grafica) || '370px';
            const restaurar = [];

            // Sobrescrituras temporales de estilo en línea, para las
            // gráficas de episodios (ver más abajo). Se guarda [elemento,
            // propiedad, valor original] de cada una, para devolverlas tal
            // cual en el 'finally'.
            const overridesEpisodios = [];
            function forzarEstilo(el, prop, valor) {
                if (!el) { return; }
                overridesEpisodios.push([el, prop, el.style.getPropertyValue(prop)]);
                el.style.setProperty(prop, valor, 'important');
            }

            // El PDF tiene que salir con el layout de escritorio aunque se
            // descargue desde un celular: html2canvas fotografía el DOM vivo,
            // así que si la pantalla es angosta capturaría la versión apilada.
            // La clase impone los 1280px (regla .capturando-pdf del
            // index_string) solo durante la foto.
            //
            // El evento 'resize' es el que despierta a ECharts y a Plotly: los
            // dos escuchan window.resize y recalculan sus medidas solos. Sin
            // él, las gráficas se fotografían con el tamaño que tenían en la
            // pantalla chica aunque el contenedor ya sea más ancho. La espera
            // le da tiempo al navegador de rehacer el acomodo antes de que se
            // midan los contenedores con getBoundingClientRect.
            const anchoForzado = document.body.clientWidth < 1280;
            let overlay = null;
            if (anchoForzado) {
                // Forzar 1280px en el body NO cambia el ancho que ve un
                // '@media query': el viewport real sigue siendo el del
                // celular, así que el acordeón y el carrusel siguen activos
                // en la pantalla real mientras se prepara la foto. Sin este
                // overlay, el usuario ve la pantalla desbordarse y las
                // tarjetas armarse a medias durante ese instante.
                overlay = document.createElement('div');
                overlay.style.position = 'fixed';
                overlay.style.inset = '0';
                overlay.style.zIndex = '999999';
                overlay.style.backgroundColor = '#ffffff';
                overlay.style.display = 'flex';
                overlay.style.alignItems = 'center';
                overlay.style.justifyContent = 'center';
                overlay.style.fontFamily = 'Montserrat, sans-serif';
                overlay.style.fontSize = '16px';
                overlay.style.color = '#465055';
                overlay.textContent = 'Generando PDF...';
                document.body.appendChild(overlay);

                document.body.classList.add('capturando-pdf');

                // La fila de la tabla + gráficas de episodios usa la misma
                // clase 'fila-apilable' que el resto de filas que sí se
                // apilan en celular. El resto del PDF sale bien porque
                // html2canvas vuelve a renderizar esas partes DENTRO de una
                // ventana virtual de 1280px (vía 'windowWidth'), donde el
                // '@media' de celular ya no aplica. Pero estas dos gráficas
                // NO pasan por esa ventana virtual: se convierten a imagen
                // ANTES, midiendo el DOM real — y el DOM real sigue viendo un
                // viewport angosto de verdad (forzar min-width en el body no
                // cambia lo que un '@media query' considera "la pantalla").
                // Ahí sigue activo '.fila-apilable { flex-direction: column }'
                // + '.fila-apilable > * { width: 100% }', así que la gráfica
                // que se mide termina con el ancho de TODA la fila en vez del
                // que le toca junto a la tabla. Se restituyen a mano, con
                // 'important', los mismos valores que trae cada una inline
                // en escritorio (ver el html.Div de episodios más arriba).
                const precontDiv = document.getElementById('echart-precontingencias');
                const contF1Div = document.getElementById('echart-contingencias-f1');
                const parejaGraficas = precontDiv && precontDiv.parentElement;
                const filaEpisodios = parejaGraficas && parejaGraficas.parentElement;
                const tablaEpisodios = filaEpisodios && Array.from(filaEpisodios.children)
                    .find(function (hijo) { return hijo !== parejaGraficas; });

                if (filaEpisodios) { forzarEstilo(filaEpisodios, 'flex-direction', 'row'); }
                if (parejaGraficas) {
                    forzarEstilo(parejaGraficas, 'flex-direction', 'row');
                    forzarEstilo(parejaGraficas, 'flex', '1 1 400px');
                    forzarEstilo(parejaGraficas, 'min-width', '380px');
                    forzarEstilo(parejaGraficas, 'width', 'auto');
                    // Las dos imágenes sustitutas quedan con un ancho fijo
                    // en píxeles (ver 'sustituir'); si el espacio disponible
                    // sobra, sin esto se pegan a la izquierda en vez de
                    // quedar centradas como pareja.
                    forzarEstilo(parejaGraficas, 'justify-content', 'center');
                }
                if (tablaEpisodios) {
                    forzarEstilo(tablaEpisodios, 'flex', '1 1 420px');
                    forzarEstilo(tablaEpisodios, 'min-width', '340px');
                    forzarEstilo(tablaEpisodios, 'width', 'auto');
                }
                [precontDiv, contF1Div].forEach(function (el) {
                    if (!el) { return; }
                    forzarEstilo(el, 'flex', '1');
                    forzarEstilo(el, 'min-width', '190px');
                    forzarEstilo(el, 'width', 'auto');
                    // Mismo problema que el ancho, y misma solución: el alto
                    // (ALTO_GRAFICA_EPISODIOS) depende de que una regla externa
                    // le gane por especificidad a la del '@media' de celular, y
                    // esa carrera no siempre se resuelve antes de que
                    // 'chart.resize()' lea el tamaño del contenedor.
                    forzarEstilo(el, 'height', altoGraficaEpisodios);
                });

                // El 'resize' lo escuchan Plotly y el cintillo de la serie
                // mensual, que se reacomodan solos con él.
                window.dispatchEvent(new Event('resize'));
                // Las de ECharts NO se dejan al listener: se rehacen aquí,
                // explícitamente y sin animación. Confiar en el evento
                // significaba depender de que el redibujo terminara dentro de la
                // espera de abajo, y la animación dura 600ms — más que ella.
                if (typeof window.__redibujarEpisodios === 'function') {
                    window.__redibujarEpisodios(false);
                }
                await new Promise(res => setTimeout(res, 450));
            }

            // Cambia una gráfica por su imagen y espera a que el navegador
            // termine de decodificarla. Dos detalles importantes:
            //
            //  · Se espera a 'onload': sin eso, html2canvas alcanza a
            //    fotografiar la imagen todavía vacía.
            //  · La gráfica se SACA del DOM en vez de ocultarse. html2canvas
            //    clona y lee todos los <canvas> aunque estén ocultos, y el
            //    del mapa está "contaminado" por los iconos que carga desde
            //    unpkg.com sin permiso de origen cruzado; esa lectura falla
            //    y arruina la captura de toda esa zona.
            function sustituir(div, url, medidaExacta) {
                return new Promise(function (resolve) {
                    const img = document.createElement('img');

                    if (medidaExacta) {
                        // Medidas exactas en píxeles, tomadas del div justo
                        // antes de sacarlo del DOM. Es la única forma de
                        // garantizar que la imagen ocupe el mismo espacio que
                        // ocupaba la gráfica: dejarlo en manos de 'width:100%'
                        // + 'height:auto' significa confiar en que el ancho
                        // del contenedor no cambie entre que se mide el
                        // tamaño real (con la gráfica) y que se inserta la
                        // imagen (ya sin ella) — y en la práctica el 'flex'
                        // de alrededor sí se reacomoda entre esos dos
                        // momentos, lo que dejaba la imagen más angosta y,
                        // por 'height:auto', también más baja de lo debido.
                        img.style.width = medidaExacta.ancho + 'px';
                        img.style.height = medidaExacta.alto + 'px';
                        img.style.maxWidth = 'none';
                        img.style.flex = 'none';
                    } else {
                        // Ancho relativo al contenedor y alto automático: con el
                        // ancho en píxeles del nodo de Plotly la imagen se
                        // desbordaba unos pixeles y se encimaba con el panel de
                        // al lado. 'height: auto' conserva la proporción.
                        img.style.width = '100%';
                        img.style.maxWidth = '100%';
                        img.style.height = 'auto';

                        // El div que se retira puede ser un elemento flex: si
                        // la imagen no copia su 'flex', dos imágenes a
                        // width:100% piden cada una el ancho completo y se
                        // aprietan entre sí.
                        const estilo = getComputedStyle(div);
                        if (estilo.display !== 'none' && div.parentNode
                                && getComputedStyle(div.parentNode).display === 'flex') {
                            img.style.flex = estilo.flex;
                            img.style.minWidth = '0';
                            img.style.alignSelf = 'flex-start';
                        }
                    }
                    img.style.display = 'block';
                    img.style.boxSizing = 'border-box';
                    img.onload = function () { resolve(true); };
                    img.onerror = function () {
                        console.warn('La imagen sustituta no cargo');
                        resolve(false);
                    };
                    img.src = url;

                    const padre = div.parentNode;
                    padre.insertBefore(img, div.nextSibling);
                    padre.removeChild(div);
                    restaurar.push([div, img]);
                });
            }

            // Gráficas de Plotly (mapa y serie mensual).
            for (const id of ['mapa-grafico', 'grafico-serie-mensual']) {
                const contenedor = document.getElementById(id);
                if (!contenedor) {
                    console.warn('PDF: no existe el elemento ' + id);
                    continue;
                }

                // dcc.Graph pone el id en un contenedor EXTERNO; el nodo real
                // de Plotly (el que tiene _fullLayout y sabe exportarse) es un
                // hijo con la clase js-plotly-plot. Sin este paso el bucle
                // saltaba ambas gráficas en silencio.
                const div = contenedor._fullLayout
                            ? contenedor
                            : contenedor.querySelector('.js-plotly-plot');
                if (!div) {
                    console.warn('PDF: no se encontro el nodo de Plotly en ' + id);
                    continue;
                }

                const caja = div.getBoundingClientRect();
                const opciones = {
                    format: 'png',
                    width: Math.round(caja.width) || 900,
                    height: Math.round(caja.height) || 400,
                    scale: 1.5
                };
                let url = null;

                // El mapa trae su foto ya lista desde Python (kaleido). Se
                // usa esa: capturarlo desde el navegador no es confiable
                // porque su canvas es WebGL y los mosaicos vienen de otro
                // dominio.
                if (id === 'mapa-grafico') {
                    const estatico = document.getElementById('mapa-estatico');
                    if (estatico && estatico.src && estatico.src.indexOf('data:image') === 0) {
                        url = estatico.src;
                        console.log('PDF: usando la imagen del mapa generada en Python');
                    } else {
                        console.warn('PDF: NO hay imagen del mapa pre-generada. '
                                     + 'Revisa que kaleido este instalado y vuelve a correr '
                                     + 'la celda del codigo y run_full_pipeline().');
                    }
                }

                if (!url) {
                    try {
                        // Para las gráficas normales basta con forzar un
                        // redibujo y esperar dos frames antes de leer.
                        await Plotly.relayout(div, {});
                        await new Promise(res => requestAnimationFrame(() =>
                                                  requestAnimationFrame(res)));
                        url = await Plotly.toImage(div, opciones);
                    } catch (e) {
                        console.warn('Captura directa fallo en ' + id, e);
                    }
                }

                if (url) { await sustituir(div, url); }
            }

            // Gráficas de ECharts (barras de episodios). Las dos se miden y
            // se convierten a imagen ANTES de sustituir ninguna: si se
            // sustituyera una y LUEGO se midiera la otra, la primera ya
            // habría dejado de ser un elemento flex (la imagen tiene ancho
            // fijo), y eso le regala todo el espacio que sobra a la segunda
            // — que es justo por lo que una barra salía de un tamaño y la
            // otra de otro.
            const capturasEpisodios = [];
            for (const id of ['echart-precontingencias', 'echart-contingencias-f1']) {
                const div = document.getElementById(id);
                if (!div) { continue; }
                const inst = echarts.getInstanceByDom(div);
                if (!inst) { continue; }
                try {
                    // Se remide justo antes de fotografiar. Hace falta porque
                    // ECharts no remide solo: el PNG saldría con las medidas
                    // viejas y la imagen se vería estirada.
                    inst.resize();
                    await new Promise(res => requestAnimationFrame(() =>
                                              requestAnimationFrame(res)));
                    // Medida real del div EN ESTE MOMENTO, con la gráfica
                    // todavía puesta: es la que se le copia a la imagen
                    // sustituta, en vez de dejarla calcular su propio tamaño
                    // con 'width:100%' + 'height:auto' (ver 'sustituir').
                    const caja = div.getBoundingClientRect();
                    const url = inst.getDataURL({
                        type: 'png', pixelRatio: 1.5, backgroundColor: '#ffffff'
                    });
                    capturasEpisodios.push({div, url, ancho: caja.width, alto: caja.height});
                } catch (e) { console.warn('ECharts ' + id, e); }
            }
            for (const c of capturasEpisodios) {
                await sustituir(c.div, c.url, {ancho: c.ancho, alto: c.alto});
            }

            // Los botones no tienen sentido en el PDF.
            const botones = Array.from(document.querySelectorAll('button'));
            botones.forEach(b => { b.dataset.vis = b.style.visibility;
                                   b.style.visibility = 'hidden'; });

            await new Promise(res => setTimeout(res, 400));

            try {
                // Se capturan las tres páginas ANTES de armar el PDF, porque
                // la orientación de cada hoja se decide con la forma real de
                // su contenido (ver abajo) y eso hay que conocerlo desde la
                // primera página, no solo desde la segunda en adelante.
                const lienzos = [];
                for (const idPag of ['pdf-pagina-1', 'pdf-pagina-2', 'pdf-pagina-3']) {
                    const bloque = document.getElementById(idPag);
                    if (!bloque) { continue; }
                    lienzos.push(await html2canvas(bloque, {
                        scale: 1.5, backgroundColor: '#ffffff',
                        useCORS: true, logging: false,
                        windowWidth: bloque.scrollWidth,
                        windowHeight: bloque.scrollHeight
                    }));
                }

                const margenX = 8;
                const margenY = 5;
                let pdf = null;
                lienzos.forEach(function (lienzo) {
                    // Todas las hojas en vertical (A4 portrait), con el
                    // contenido alineado arriba para no dejar tanto espacio
                    // en blanco en la parte superior.
                    const orientacion = 'p';

                    if (!pdf) {
                        pdf = new jspdf.jsPDF(orientacion, 'mm', 'a4');
                    } else {
                        pdf.addPage('a4', orientacion);
                    }

                    const anchoPag = pdf.internal.pageSize.getWidth();
                    const altoPag = pdf.internal.pageSize.getHeight();
                    const anchoUtil = anchoPag - margenX * 2;
                    const altoUtil = altoPag - margenY * 2;

                    // Se escala por el lado que primero se topa con el borde,
                    // así el bloque cabe entero en la hoja sin salirse.
                    const escala = Math.min(anchoUtil / lienzo.width,
                                            altoUtil / lienzo.height);
                    const ancho = lienzo.width * escala;
                    const alto = lienzo.height * escala;

                    pdf.addImage(lienzo.toDataURL('image/jpeg', 0.85), 'JPEG',
                                 (anchoPag - ancho) / 2, margenY, ancho, alto);
                });

                if (!pdf) { throw new Error('No hay páginas que exportar.'); }

                const hoy = new Date().toISOString().slice(0, 10);
                pdf.save('Reporte_Calidad_del_Aire_' + hoy + '.pdf');
            } catch (e) {
                console.error('Error al generar el PDF', e);
                alert('No se pudo generar el PDF. Revisa la consola.');
            } finally {
                // Pase lo que pase, se devuelve el dashboard a su estado
                // interactivo: sin esto, un error a media captura lo dejaría
                // con imágenes estáticas hasta recargar.
                botones.forEach(b => { b.style.visibility = b.dataset.vis || ''; });
                // Se regresa cada gráfica a su lugar exacto: se reinserta
                // justo antes de su imagen sustituta y luego se quita esa.
                restaurar.forEach(([div, img]) => {
                    if (img.parentNode) { img.parentNode.insertBefore(div, img); }
                    img.remove();
                });
                // Y se devuelve la pantalla a su ancho real. El 'resize' final
                // es el que reacomoda las gráficas a la vista del teléfono;
                // sin él se quedan dibujadas a 1280px dentro de un contenedor
                // angosto.
                if (anchoForzado) {
                    // Todo lo forzado a mano (fila, anchos, alto) se quita
                    // ANTES del 'resize' de abajo, para que ese evento
                    // redibuje las gráficas ya con las medidas reales de
                    // celular en vez de las de escritorio.
                    overridesEpisodios.forEach(function (par) {
                        const [el, prop, valorOriginal] = par;
                        if (valorOriginal) {
                            el.style.setProperty(prop, valorOriginal);
                        } else {
                            el.style.removeProperty(prop);
                        }
                    });
                    document.body.classList.remove('capturando-pdf');
                    window.dispatchEvent(new Event('resize'));
                    if (typeof window.__redibujarEpisodios === 'function') {
                        window.__redibujarEpisodios(true);
                    }
                }
                if (overlay && overlay.parentNode) { overlay.remove(); }
            }

            return window.dash_clientside.no_update;
        }

    }
});
