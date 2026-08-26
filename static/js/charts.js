/* Dependency-free SVG charts for soleire.
 *
 * Replaces the Chart.js CDN script the site used to load. Two reasons that
 * mattered here: a site whose whole premise is not tracking its contributors
 * should not hand every visitor's IP to a third-party CDN, and a container
 * ought to work without outbound internet access.
 *
 * Data arrives through <script type="application/json"> blocks written by
 * Django's `json_script` filter, so nothing is interpolated into executable
 * JavaScript — which is also what closes the injection hole the old inline
 * template loop had.
 *
 * Every chart is aria-hidden; each one sits next to a real <table> carrying
 * the same numbers, which is the accessible representation.
 */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var SERIES_VARS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4"];

  function el(name, attrs, text) {
    var node = document.createElementNS(NS, name);
    for (var key in attrs) {
      if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, String(attrs[key]));
      }
    }
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function readJSON(id) {
    var node = document.getElementById(id);
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (err) {
      return null;
    }
  }

  function colour(index) {
    var value = getComputedStyle(document.documentElement)
      .getPropertyValue(SERIES_VARS[index % SERIES_VARS.length]);
    return value.trim() || "#2f7d32";
  }

  function cssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return value.trim() || fallback;
  }

  /* Pick a round step so the axis lands on 1/2/5 x 10^n boundaries. */
  function niceTicks(max, count) {
    if (!(max > 0)) return { max: 1, ticks: [0, 1] };
    var raw = max / count;
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var norm = raw / mag;
    var step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
    var top = Math.ceil(max / step) * step;
    var ticks = [];
    for (var v = 0; v <= top + step / 2; v += step) ticks.push(Math.round(v * 1000) / 1000);
    return { max: top, ticks: ticks };
  }

  function format(value) {
    if (value === null || value === undefined) return "—";
    var abs = Math.abs(value);
    if (abs >= 1000000) return (value / 1000000).toFixed(1) + "M";
    if (abs >= 1000) return (value / 1000).toFixed(abs >= 10000 ? 0 : 1) + "k";
    if (abs >= 100) return value.toFixed(0);
    return value.toFixed(abs < 10 ? 1 : 0);
  }

  function frame(width, height, pad) {
    var svg = el("svg", {
      viewBox: "0 0 " + width + " " + height,
      preserveAspectRatio: "xMidYMid meet",
      "aria-hidden": "true",
      focusable: "false",
      role: "presentation"
    });
    return { svg: svg, plot: {
      left: pad.left, top: pad.top,
      right: width - pad.right, bottom: height - pad.bottom,
      width: width - pad.left - pad.right,
      height: height - pad.top - pad.bottom
    } };
  }

  function drawAxes(svg, plot, scale, unit) {
    var grid = cssVar("--chart-grid", "#e2e6dd");
    var muted = cssVar("--text-muted", "#5d6b52");

    scale.ticks.forEach(function (tick) {
      var y = plot.bottom - (tick / scale.max) * plot.height;
      svg.appendChild(el("line", {
        x1: plot.left, x2: plot.right, y1: y, y2: y,
        stroke: grid, "stroke-width": 1
      }));
      svg.appendChild(el("text", {
        x: plot.left - 7, y: y + 3.5, "text-anchor": "end",
        "font-size": 10, fill: muted
      }, format(tick)));
    });

    if (unit) {
      svg.appendChild(el("text", {
        x: plot.left - 7, y: plot.top - 10, "text-anchor": "end",
        "font-size": 9.5, fill: muted
      }, unit));
    }
  }

  /* ------------------------------------------------------------ bar chart */

  function renderBar(container, data) {
    var points = (data.points || []).filter(function (p) {
      return p.value !== null && p.value !== undefined;
    });
    if (!points.length) return empty(container);

    var width = 760;
    var longest = points.reduce(function (acc, p) {
      return Math.max(acc, String(p.label).length);
    }, 0);
    var rotate = points.length > 8 || longest > 8;
    var bottomPad = rotate ? 68 : 34;
    var height = 300 + (rotate ? 20 : 0);

    var f = frame(width, height, { left: 46, right: 12, top: 22, bottom: bottomPad });
    var plot = f.plot;
    var max = Math.max.apply(null, points.map(function (p) { return p.value; }));
    var scale = niceTicks(max, 5);
    drawAxes(f.svg, plot, scale, data.unit);

    var slot = plot.width / points.length;
    var barWidth = Math.max(4, Math.min(52, slot * 0.68));
    var muted = cssVar("--text-muted", "#5d6b52");
    var fill = colour(0);

    points.forEach(function (point, index) {
      var centre = plot.left + slot * (index + 0.5);
      var barHeight = Math.max(1, (point.value / scale.max) * plot.height);
      f.svg.appendChild(el("rect", {
        class: "bar",
        x: centre - barWidth / 2, y: plot.bottom - barHeight,
        width: barWidth, height: barHeight,
        fill: fill, rx: 2
      }));

      if (points.length <= 16) {
        f.svg.appendChild(el("text", {
          x: centre, y: plot.bottom - barHeight - 5,
          "text-anchor": "middle", "font-size": 10, fill: muted
        }, format(point.value)));
      }

      var label = el("text", {
        x: centre, y: plot.bottom + 14,
        "text-anchor": rotate ? "end" : "middle",
        "font-size": 10.5, fill: muted
      }, point.label);
      if (rotate) {
        label.setAttribute("transform", "rotate(-42 " + centre + " " + (plot.bottom + 14) + ")");
      }
      f.svg.appendChild(label);
    });

    f.svg.appendChild(el("line", {
      x1: plot.left, x2: plot.right, y1: plot.bottom, y2: plot.bottom,
      stroke: cssVar("--border", "#dfe3da"), "stroke-width": 1.5
    }));

    container.appendChild(f.svg);
  }

  /* ----------------------------------------------------------- line chart */

  function renderLine(container, data) {
    /* Accepts either the single-series {points:[{label,value}]} shape or the
       multi-series {labels:[], series:[{name, values:[]}]} shape. */
    var labels, series;
    if (data.series) {
      labels = data.labels || [];
      series = data.series;
    } else {
      labels = (data.points || []).map(function (p) { return p.label; });
      series = [{ name: null, values: (data.points || []).map(function (p) { return p.value; }) }];
    }

    var everything = series.reduce(function (acc, s) {
      return acc.concat((s.values || []).filter(function (v) {
        return v !== null && v !== undefined;
      }));
    }, []);
    if (!everything.length) return empty(container);

    var width = 760, height = 300;
    var f = frame(width, height, { left: 46, right: 12, top: 22, bottom: 40 });
    var plot = f.plot;
    var scale = niceTicks(Math.max.apply(null, everything), 5);
    drawAxes(f.svg, plot, scale, data.unit);

    var count = Math.max(labels.length, 1);
    var step = count > 1 ? plot.width / (count - 1) : 0;
    var xAt = function (i) { return count > 1 ? plot.left + step * i : plot.left + plot.width / 2; };
    var yAt = function (v) { return plot.bottom - (v / scale.max) * plot.height; };

    series.forEach(function (entry, sIndex) {
      var stroke = colour(sIndex);
      var values = entry.values || [];
      /* Split on nulls so a suppressed month leaves a visible gap rather than
         a straight line implying data we are not allowed to show. */
      var run = [];
      var flush = function () {
        if (run.length > 1) {
          f.svg.appendChild(el("polyline", {
            class: "series-line",
            points: run.map(function (p) { return p[0] + "," + p[1]; }).join(" "),
            fill: "none", stroke: stroke, "stroke-width": 2,
            "stroke-linejoin": "round", "stroke-linecap": "round"
          }));
        } else if (run.length === 1) {
          f.svg.appendChild(el("circle", { cx: run[0][0], cy: run[0][1], r: 2.5, fill: stroke }));
        }
        run = [];
      };
      values.forEach(function (value, i) {
        if (value === null || value === undefined) { flush(); return; }
        run.push([xAt(i), yAt(value)]);
      });
      flush();

      if (values.length <= 14) {
        values.forEach(function (value, i) {
          if (value === null || value === undefined) return;
          f.svg.appendChild(el("circle", { cx: xAt(i), cy: yAt(value), r: 2.6, fill: stroke }));
        });
      }
    });

    var muted = cssVar("--text-muted", "#5d6b52");
    var every = labels.length > 18 ? Math.ceil(labels.length / 12) : 1;
    /* Roughly 5.6px per character at font-size 10, plus a gap. Tracking the
       last drawn position stops the always-drawn final label landing on top of
       its neighbour, which it did on a 32-month series. */
    var lastRight = -Infinity;
    labels.forEach(function (label, i) {
      var isLast = i === labels.length - 1;
      if (i % every !== 0 && !isLast) return;
      var x = xAt(i);
      var halfWidth = String(label).length * 2.8 + 4;
      if (x - halfWidth < lastRight) return;
      lastRight = x + halfWidth;
      f.svg.appendChild(el("text", {
        x: x, y: plot.bottom + 15, "text-anchor": "middle",
        "font-size": 10, fill: muted
      }, label));
    });

    f.svg.appendChild(el("line", {
      x1: plot.left, x2: plot.right, y1: plot.bottom, y2: plot.bottom,
      stroke: cssVar("--border", "#dfe3da"), "stroke-width": 1.5
    }));
    container.appendChild(f.svg);

    if (series.length > 1) {
      var legend = document.createElement("div");
      legend.className = "chart-legend";
      series.forEach(function (entry, i) {
        var item = document.createElement("span");
        var swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.background = colour(i);
        item.appendChild(swatch);
        item.appendChild(document.createTextNode(entry.name || "Series " + (i + 1)));
        legend.appendChild(item);
      });
      container.appendChild(legend);
    }
  }

  function empty(container) {
    var note = document.createElement("p");
    note.className = "chart-empty";
    note.textContent = "Not enough data to draw this chart yet.";
    container.appendChild(note);
  }

  function draw() {
    var containers = document.querySelectorAll("[data-chart]");
    Array.prototype.forEach.call(containers, function (container) {
      var data = readJSON(container.getAttribute("data-chart"));
      container.innerHTML = "";
      if (!data) return empty(container);
      if (container.getAttribute("data-chart-type") === "line") {
        renderLine(container, data);
      } else {
        renderBar(container, data);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", draw);
  } else {
    draw();
  }

  /* Redraw on colour-scheme change so the palette follows the system theme. */
  if (window.matchMedia) {
    var query = window.matchMedia("(prefers-color-scheme: dark)");
    if (query.addEventListener) query.addEventListener("change", draw);
  }
})();
