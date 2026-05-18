/* Pixie — tiny vanilla helpers (no framework).
 * Exposes window.Pixie with theme/accent/density setters, a swap-hook
 * registrar that fires on first load and every htmx:afterSettle, and a
 * minimal toast helper. No external deps.
 */
(function () {
  "use strict";

  var THEME_KEY = "pixie.theme";
  var ACCENT_KEY = "pixie.accent";
  var DENSITY_KEY = "pixie.density";

  // Theme registry. `variant` tells the accent system which sub-palette
  // (light/dark) to pick from ACCENTS for runtime accent overrides.
  // To add a theme: append an entry here AND a [data-theme="<id>"] block
  // in pixie.css AND the same id to THEME_CHOICES in pixie/routes/settings.py.
  var THEMES = {
    light:              { label: "Light",             variant: "light" },
    dark:               { label: "Dark",              variant: "dark"  },
    bloomberg:          { label: "Bloomberg",         variant: "dark"  },
    "solarized-light":  { label: "Solarized Light",   variant: "light" },
    "solarized-dark":   { label: "Solarized Dark",    variant: "dark"  },
    dracula:            { label: "Dracula",           variant: "dark"  },
    nord:               { label: "Nord",              variant: "dark"  },
    monokai:            { label: "Monokai",           variant: "dark"  },
    "github-dark":      { label: "GitHub Dark",       variant: "dark"  },
    "gruvbox-dark":     { label: "Gruvbox Dark",      variant: "dark"  },
    sepia:              { label: "Sepia",             variant: "light" },
    "high-contrast":    { label: "High Contrast",     variant: "light" },
    "catppuccin-latte": { label: "Catppuccin Latte",  variant: "light" }
  };
  // Mirrors the design's ACCENTS map (DESIGN_SPEC.md s4).
  var ACCENTS = {
    indigo: {
      light: { accent: "oklch(0.54 0.13 268)", accent2: "oklch(0.6 0.13 268)" },
      dark:  { accent: "oklch(0.68 0.14 268)", accent2: "oklch(0.74 0.14 268)" }
    },
    slate: {
      light: { accent: "oklch(0.45 0.04 250)", accent2: "oklch(0.5 0.04 250)" },
      dark:  { accent: "oklch(0.7 0.04 250)",  accent2: "oklch(0.78 0.04 250)" }
    },
    forest: {
      light: { accent: "oklch(0.5 0.11 155)",  accent2: "oklch(0.56 0.11 155)" },
      dark:  { accent: "oklch(0.66 0.12 155)", accent2: "oklch(0.72 0.12 155)" }
    },
    ember: {
      light: { accent: "oklch(0.58 0.16 35)",  accent2: "oklch(0.64 0.16 35)" },
      dark:  { accent: "oklch(0.7 0.16 35)",   accent2: "oklch(0.76 0.16 35)" }
    }
  };

  var Pixie = window.Pixie || {};
  window.Pixie = Pixie;
  Pixie.themes = THEMES;

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "light";
  }
  function themeVariant(theme) {
    var t = THEMES[theme];
    return (t && t.variant) || "light";
  }
  // Treat any registered theme with variant "dark" as dark for code that
  // historically checked `data-theme === "dark"` (CodeMirror, Plotly etc).
  Pixie.isDark = function () {
    return themeVariant(currentTheme()) === "dark";
  };

  Pixie.setTheme = function (theme) {
    if (!THEMES[theme]) return;
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) {}
    // Re-apply accent so the per-theme variant takes effect.
    var accent = Pixie._accent || "indigo";
    Pixie.setAccent(accent);
    document.dispatchEvent(new CustomEvent("pixie:theme-changed", { detail: { theme: theme } }));
  };

  Pixie.setAccent = function (name) {
    var palette = ACCENTS[name];
    if (!palette) return;
    Pixie._accent = name;
    try { localStorage.setItem(ACCENT_KEY, name); } catch (e) {}
    var theme = currentTheme();
    var p = palette[themeVariant(theme)] || palette.light;
    var style = document.getElementById("pixie-accent");
    if (!style) {
      style = document.createElement("style");
      style.id = "pixie-accent";
      document.head.appendChild(style);
    }
    // Build a selector covering every registered theme so the runtime
    // accent override beats the per-theme baseline in pixie.css.
    var selectors = [":root"];
    for (var id in THEMES) {
      if (THEMES.hasOwnProperty(id)) {
        selectors.push('[data-theme="' + id + '"]');
      }
    }
    style.textContent =
      selectors.join(", ") + " {" +
      "  --accent: " + p.accent + ";" +
      "  --accent-2: " + p.accent2 + ";" +
      "}";
  };

  Pixie.setDensity = function (density) {
    if (density !== "compact" && density !== "comfortable" && density !== "airy") return;
    var body = document.body;
    if (body && body.classList.contains("pixie")) {
      body.setAttribute("data-density", density);
    }
    try { localStorage.setItem(DENSITY_KEY, density); } catch (e) {}
  };

  Pixie.toggleTheme = function () {
    var next = Pixie.isDark() ? "light" : "dark";
    Pixie.setTheme(next);
    Pixie.persistPreference("theme", next);
    try { localStorage.setItem("pixieTheme", next); } catch (e) {}
  };

  // Persist a single Appearance preference (theme / accent / density) to the
  // server immediately. Without this the picker only updates the DOM, and the
  // next htmx swap re-applies the stale server value via applyPersistedSettings.
  Pixie.persistPreference = function (key, value) {
    if (!key || value == null) return;
    // Mirror the change into the in-DOM payload script so subsequent htmx
    // swaps (which never replace the payload tag — sidebar swaps target
    // #pixie-main-content only) don't revert to a stale value when
    // applyPersistedSettings re-runs on htmx:afterSettle.
    try {
      var el = document.getElementById("pixie-settings-payload");
      if (el) {
        var payload = {};
        try { payload = JSON.parse(el.textContent || el.innerText || "{}"); } catch (e) {}
        payload[key] = value;
        el.textContent = JSON.stringify(payload);
      }
    } catch (e) {}
    var body = "key=" + encodeURIComponent(key) + "&value=" + encodeURIComponent(value);
    try {
      fetch("/settings/preference", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body,
        credentials: "same-origin",
        keepalive: true,
      });
    } catch (e) {}
  };

  // --- swap-hook registrar -------------------------------------------------
  var swapHandlers = [];
  Pixie.initOnSwap = function (handler) {
    if (typeof handler !== "function") return;
    swapHandlers.push(handler);
    // Run immediately if DOM is already ready.
    if (document.readyState !== "loading") {
      try { handler(document); } catch (e) { console.error(e); }
    }
  };
  function runSwapHandlers(root) {
    for (var i = 0; i < swapHandlers.length; i++) {
      try { swapHandlers[i](root); } catch (e) { console.error(e); }
    }
  }

  // --- toast helper --------------------------------------------------------
  Pixie.toast = function (text, opts) {
    opts = opts || {};
    var type = opts.type || "info";
    var ttl = typeof opts.ttl === "number" ? opts.ttl : 4000;
    var host = document.getElementById("pixie-toasts");
    if (!host) {
      host = document.createElement("div");
      host.id = "pixie-toasts";
      document.body.appendChild(host);
    }
    var el = document.createElement("div");
    el.className = "toast" + (type !== "info" ? " toast--" + type : "");
    el.textContent = text;
    host.appendChild(el);
    if (ttl > 0) {
      setTimeout(function () {
        el.style.transition = "opacity .2s";
        el.style.opacity = "0";
        setTimeout(function () { el.remove(); }, 220);
      }, ttl);
    }
    return el;
  };

  // --- persisted-settings sync (server-rendered payload) -------------------
  // The server writes #pixie-settings-payload as JSON on every full page render.
  // We read it on boot and after every htmx swap, applying theme/accent/density
  // and the dev-mode body attribute. Server is the source of truth; localStorage
  // is the fallback for instant first-paint before the payload script parses.
  Pixie.applyPersistedSettings = function () {
    var el = document.getElementById("pixie-settings-payload");
    if (!el) return;
    var payload;
    try { payload = JSON.parse(el.textContent || el.innerText || "{}"); }
    catch (e) { return; }
    var t = payload.theme;
    if (t === "auto") {
      t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    if (t && THEMES[t]) {
      Pixie.setTheme(t);
    }
    if (payload.accent && ACCENTS[payload.accent]) {
      Pixie.setAccent(payload.accent);
    }
    if (payload.density) {
      Pixie.setDensity(payload.density);
    }
    var body = document.body;
    if (body) {
      body.setAttribute(
        "data-dev-mode", payload.developer_mode ? "true" : "false"
      );
    }
  };

  // Server-driven toast: fired by HX-Trigger headers as {"pixie:toast":{text,kind}}.
  document.addEventListener("pixie:toast", function (evt) {
    if (!evt || !evt.detail) return;
    var detail = evt.detail;
    var text = detail.text || detail.value || detail.message;
    if (!text) return;
    Pixie.toast(text, { type: detail.kind || detail.type || "info" });
  });

  // --- boot ----------------------------------------------------------------
  function boot() {
    // Restore persisted theme / accent / density.
    var savedTheme, savedAccent, savedDensity;
    try { savedTheme = localStorage.getItem(THEME_KEY); } catch (e) {}
    try { savedAccent = localStorage.getItem(ACCENT_KEY); } catch (e) {}
    try { savedDensity = localStorage.getItem(DENSITY_KEY); } catch (e) {}

    if (savedTheme && THEMES[savedTheme]) {
      document.documentElement.setAttribute("data-theme", savedTheme);
    }
    Pixie.setAccent(savedAccent && ACCENTS[savedAccent] ? savedAccent : "indigo");
    if (savedDensity) Pixie.setDensity(savedDensity);

    // Server-rendered payload wins over localStorage.
    Pixie.applyPersistedSettings();

    // Initial pass: run any handlers that were registered before DOMContentLoaded.
    runSwapHandlers(document);
  }

  // Re-apply the payload after every htmx swap so the settings page itself
  // (which posts back to /settings) reflects the updated db values without
  // a hard reload.
  Pixie.initOnSwap(function () { Pixie.applyPersistedSettings(); });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  document.body && document.body.addEventListener
    ? document.body.addEventListener("htmx:afterSettle", function (evt) {
        runSwapHandlers(evt.target || document);
      })
    : document.addEventListener("htmx:afterSettle", function (evt) {
        runSwapHandlers(evt.target || document);
      });

  // Defensive: bind after DOM ready in case the body wasn't there yet.
  document.addEventListener("DOMContentLoaded", function () {
    document.body.addEventListener("htmx:afterSettle", function (evt) {
      runSwapHandlers(evt.target || document);
    });
  });

  // ==========================================================================
  // Output renderers — Plotly theme, Leaflet helpers, table, copy, modal, etc.
  // Every output partial calls into one of these on its first paint AND on
  // every htmx:afterSettle (via Pixie.initOnSwap).
  // ==========================================================================

  function readJsonScript(el) {
    if (!el) return null;
    try { return JSON.parse(el.textContent || el.innerText || "null"); }
    catch (e) { console.warn("pixie: bad JSON in", el, e); return null; }
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim();
  }

  // ----- Plotly theme -------------------------------------------------------
  Pixie.plotlyTheme = function () {
    var fg     = cssVar("--fg")        || "#18181a";
    var bg     = cssVar("--bg")        || "#ffffff";
    var muted  = cssVar("--fg-muted")  || "#6b6b70";
    var border = cssVar("--border-subtle") || "#efeeea";
    var accent = cssVar("--accent")    || "#5b6cd1";
    return {
      paper_bgcolor: bg,
      plot_bgcolor:  bg,
      font: { color: fg, family: "Inter Tight, system-ui, sans-serif", size: 11 },
      colorway: [
        accent,
        "oklch(0.65 0.13 200)",
        "oklch(0.65 0.14 50)",
        "oklch(0.6 0.18 350)",
        "oklch(0.7 0.05 280)",
        "oklch(0.6 0.13 145)",
        "oklch(0.55 0.13 25)"
      ],
      xaxis: { gridcolor: border, linecolor: border, zerolinecolor: border,
               tickfont: { size: 10, color: muted, family: "JetBrains Mono, monospace" } },
      yaxis: { gridcolor: border, linecolor: border, zerolinecolor: border,
               tickfont: { size: 10, color: muted, family: "JetBrains Mono, monospace" } },
      margin: { l: 48, r: 16, t: 14, b: 36 },
      legend: { bgcolor: "rgba(0,0,0,0)", font: { size: 10, color: muted } },
      hoverlabel: { bgcolor: bg, font: { color: fg, family: "Inter Tight" }, bordercolor: border }
    };
  };

  Pixie.plotlyConfig = {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: [
      "lasso2d", "select2d", "autoScale2d", "toggleSpikelines",
      "hoverClosestCartesian", "hoverCompareCartesian"
    ],
    displayModeBar: false,
    toImageButtonOptions: { format: "png", scale: 2 }
  };

  Pixie.charts = Pixie.charts || {};

  Pixie.makeChart = function (el, data, layoutOverride) {
    if (typeof Plotly === "undefined") {
      // Plotly defers; retry once it lands.
      var tries = 0;
      var iv = setInterval(function () {
        if (typeof Plotly !== "undefined" || tries++ > 40) {
          clearInterval(iv);
          if (typeof Plotly !== "undefined") Pixie.makeChart(el, data, layoutOverride);
        }
      }, 100);
      return;
    }
    var layout = Object.assign({}, Pixie.plotlyTheme(), layoutOverride || {});
    Plotly.newPlot(el, data, layout, Pixie.plotlyConfig);
    el.setAttribute("data-pixie-chart", "");
    Pixie.charts[el.id] = { data: data, layout: layoutOverride || {} };
    if (typeof ResizeObserver !== "undefined") {
      var ro = new ResizeObserver(function () {
        try { Plotly.Plots.resize(el); } catch (e) {}
      });
      ro.observe(el);
    }
  };

  document.addEventListener("pixie:theme-changed", function () {
    if (typeof Plotly === "undefined") return;
    document.querySelectorAll("[data-pixie-chart]").forEach(function (el) {
      var stored = Pixie.charts[el.id];
      var layout = Object.assign({}, Pixie.plotlyTheme(), (stored && stored.layout) || {});
      try { Plotly.relayout(el, layout); } catch (e) {}
    });
  });

  // ----- Leaflet map helpers ------------------------------------------------
  Pixie.maps = Pixie.maps || {};

  Pixie.makeMap = function (el, opts) {
    if (typeof L === "undefined") {
      var tries = 0;
      var iv = setInterval(function () {
        if (typeof L !== "undefined" || tries++ > 40) {
          clearInterval(iv);
          if (typeof L !== "undefined") Pixie.makeMap(el, opts);
        }
      }, 100);
      return null;
    }
    if (Pixie.maps[el.id]) {
      try { Pixie.maps[el.id].remove(); } catch (e) {}
      delete Pixie.maps[el.id];
    }
    var map = L.map(el, {
      zoomControl: true,
      scrollWheelZoom: opts.scrollWheelZoom !== false,
      attributionControl: true
    }).setView(opts.center || [51.505, -0.09], opts.zoom || 5);
    Pixie.addBaseTiles(map);
    Pixie.maps[el.id] = map;
    setTimeout(function () { try { map.invalidateSize(); } catch (e) {} }, 60);
    return map;
  };

  Pixie.addBaseTiles = function (map) {
    var dark = Pixie.isDark();
    var url = dark
      ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
      : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
    L.tileLayer(url, {
      subdomains: "abcd", maxZoom: 19, detectRetina: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
    }).addTo(map);
  };

  document.addEventListener("pixie:theme-changed", function () {
    Object.keys(Pixie.maps).forEach(function (id) {
      var map = Pixie.maps[id];
      if (!map) return;
      map.eachLayer(function (layer) {
        if (layer instanceof L.TileLayer) map.removeLayer(layer);
      });
      Pixie.addBaseTiles(map);
    });
  });

  // ----- KaTeX --------------------------------------------------------------
  Pixie.renderLatex = function (el) {
    if (!window.renderMathInElement) {
      // Defer until KaTeX auto-render is loaded.
      var tries = 0;
      var iv = setInterval(function () {
        if (window.renderMathInElement || tries++ > 40) {
          clearInterval(iv);
          if (window.renderMathInElement) Pixie.renderLatex(el);
        }
      }, 100);
      return;
    }
    try {
      window.renderMathInElement(el, {
        delimiters: [
          { left: "$$", right: "$$",   display: true  },
          { left: "\\[", right: "\\]", display: true  },
          { left: "$",  right: "$",    display: false },
          { left: "\\(", right: "\\)", display: false }
        ],
        throwOnError: false,
        errorColor: "var(--error)"
      });
    } catch (e) { console.warn("katex:", e); }
  };

  // ----- Number formatting --------------------------------------------------
  Pixie.formatNumber = function (n, opts) {
    if (n === null || n === undefined || n === "") return "";
    opts = opts || {};
    var num = typeof n === "number" ? n : Number(n);
    if (Number.isNaN(num)) return String(n);
    var fmt = opts.format || "decimal";
    var precision = opts.precision;
    var locale = opts.locale || "en-GB";
    if (fmt === "currency") {
      return new Intl.NumberFormat(locale, {
        style: "currency",
        currency: opts.currency || "GBP",
        maximumFractionDigits: precision == null ? 2 : precision,
        minimumFractionDigits: precision == null ? 2 : precision
      }).format(num);
    }
    if (fmt === "percent") {
      return new Intl.NumberFormat(locale, {
        style: "percent",
        maximumFractionDigits: precision == null ? 1 : precision
      }).format(num);
    }
    if (fmt === "scientific") {
      return new Intl.NumberFormat(locale, {
        notation: "scientific",
        maximumFractionDigits: precision == null ? 3 : precision
      }).format(num);
    }
    return new Intl.NumberFormat(locale, {
      maximumFractionDigits: precision == null ? 6 : precision,
      minimumFractionDigits: precision == null ? 0 : Math.min(precision, 0)
    }).format(num);
  };

  // ----- Table renderer (vanilla, sortable, paginated, downloadable) -------
  Pixie.initTables = function (root) {
    (root || document).querySelectorAll(".output-table:not([data-init])").forEach(function (wrap) {
      wrap.dataset.init = "1";
      var cfg = readJsonScript(wrap.querySelector("script[type='application/json']"));
      if (!cfg) return;
      var columns = (cfg.columns && cfg.columns.length) ? cfg.columns
        : ((cfg.rows && cfg.rows[0]) ? Object.keys(cfg.rows[0]).map(function (k) {
            return { key: k, label: k, type: "text" };
          }) : []);
      var rows = cfg.rows || [];
      var nextCursor = cfg.next_cursor || null;
      var state = { page: 0, pageSize: 25, sortKey: null, sortDir: 1, filter: "" };
      var tbody = wrap.querySelector("tbody");
      var pager = wrap.querySelector(".output-table__pager");
      var filterInput = wrap.querySelector(".output-table__filter");

      function render() {
        var filtered = rows;
        if (state.filter) {
          var q = state.filter.toLowerCase();
          filtered = filtered.filter(function (r) {
            return columns.some(function (c) {
              var v = r[c.key];
              return v != null && String(v).toLowerCase().indexOf(q) >= 0;
            });
          });
        }
        if (state.sortKey) {
          filtered = filtered.slice().sort(function (a, b) {
            var av = a[state.sortKey], bv = b[state.sortKey];
            if (av == null && bv == null) return 0;
            if (av == null) return 1; if (bv == null) return -1;
            var na = Number(av), nb = Number(bv);
            if (!Number.isNaN(na) && !Number.isNaN(nb)) return (na - nb) * state.sortDir;
            return (av < bv ? -1 : av > bv ? 1 : 0) * state.sortDir;
          });
        }
        var start = state.page * state.pageSize;
        var slice = filtered.slice(start, start + state.pageSize);
        tbody.innerHTML = slice.map(function (r) {
          return "<tr>" + columns.map(function (c) {
            var v = r[c.key];
            var formatted = Pixie.fmtCell(v, c.type);
            var cls = (c.type === "number" || c.type === "percent" || c.type === "currency")
              ? "num mono" : "";
            return '<td class="' + cls + '">' + formatted + '</td>';
          }).join("") + "</tr>";
        }).join("");
        var total = filtered.length;
        var pages = Math.max(1, Math.ceil(total / state.pageSize));
        var info = "Showing " + (total === 0 ? 0 : start + 1) + "-" +
                   Math.min(total, start + slice.length) + " of " + total;
        if (pager) {
          pager.innerHTML =
            '<button type="button" class="btn btn--ghost btn--icon btn--sm" data-act="prev" ' +
            (state.page === 0 ? 'disabled' : '') + ' aria-label="Previous">' +
              '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>' +
            '</button>' +
            '<span class="t-meta mono">' + info + '</span>' +
            '<button type="button" class="btn btn--ghost btn--icon btn--sm" data-act="next" ' +
            (state.page >= pages - 1 ? 'disabled' : '') + ' aria-label="Next">' +
              '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>' +
            '</button>';
          if (nextCursor) {
            pager.insertAdjacentHTML("beforeend",
              '<button type="button" class="btn btn--sm" data-act="load-more">Load more</button>');
          }
        }
      }

      if (filterInput) {
        filterInput.addEventListener("input", function (e) {
          state.filter = e.target.value; state.page = 0; render();
        });
      }
      wrap.querySelectorAll("th[data-key]").forEach(function (th) {
        th.addEventListener("click", function () {
          var k = th.dataset.key;
          state.sortDir = (state.sortKey === k) ? -state.sortDir : 1;
          state.sortKey = k;
          wrap.querySelectorAll("th[data-key]").forEach(function (other) {
            other.removeAttribute("data-sort");
          });
          th.dataset.sort = state.sortDir > 0 ? "asc" : "desc";
          render();
        });
      });
      if (pager) {
        pager.addEventListener("click", function (e) {
          var btn = e.target.closest("[data-act]"); if (!btn) return;
          if (btn.dataset.act === "prev") state.page--;
          else if (btn.dataset.act === "next") state.page++;
          else if (btn.dataset.act === "load-more") {
            // Phase 4d wires the actual fetch; surface the intent until then.
            Pixie.toast("Cursor pagination is wired by the run flow.", { ttl: 2400 });
          }
          render();
        });
      }
      var dl = wrap.querySelector("[data-action='download-csv']");
      if (dl) dl.addEventListener("click", function () { Pixie.downloadCsv(columns, rows); });
      render();
    });
  };

  Pixie.fmtCell = function (v, type) {
    if (v === null || v === undefined) return '<span class="t-meta">—</span>';
    if (type === "number") return Pixie.formatNumber(v, { format: "decimal" });
    if (type === "currency") return Pixie.formatNumber(v, { format: "currency" });
    if (type === "percent") return Pixie.formatNumber(v, { format: "percent" });
    if (type === "date") {
      var d = new Date(v);
      return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleDateString("en-GB");
    }
    if (type === "boolean") return v ? "true" : "false";
    var s = String(v);
    return s.replace(/[&<>"']/g, function (c) {
      return ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[c];
    });
  };

  Pixie.downloadCsv = function (columns, rows) {
    var head = columns.map(function (c) { return JSON.stringify(c.label); }).join(",");
    var body = rows.map(function (r) {
      return columns.map(function (c) {
        var v = r[c.key];
        if (v === null || v === undefined) return "";
        var s = String(v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      }).join(",");
    }).join("\n");
    var blob = new Blob([head + "\n" + body], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "table.csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  };

  // ----- Copy helper --------------------------------------------------------
  Pixie.initCopyButtons = function (root) {
    (root || document).querySelectorAll("[data-pixie-copy]:not([data-bound])").forEach(function (btn) {
      btn.dataset.bound = "1";
      btn.addEventListener("click", function () {
        var sel = btn.dataset.pixieCopy;
        var target = sel === "self"
          ? btn.closest(".output-card").querySelector("[data-copy-target]")
          : document.querySelector(sel);
        if (!target) return;
        var text = target.innerText || target.textContent || "";
        if (navigator.clipboard) {
          navigator.clipboard.writeText(text.trim()).then(function () {
            Pixie.toast("Copied.", { ttl: 1200 });
            btn.dataset.justCopied = "1";
            setTimeout(function () { delete btn.dataset.justCopied; }, 1200);
          });
        }
      });
    });
  };

  // ----- Download (file) helper --------------------------------------------
  Pixie.initDownloads = function (root) {
    (root || document).querySelectorAll("[data-pixie-download]:not([data-bound])").forEach(function (btn) {
      btn.dataset.bound = "1";
      btn.addEventListener("click", function () {
        var cfg = readJsonScript(btn.parentElement.querySelector("script[type='application/json']"));
        if (!cfg) return;
        var a = document.createElement("a");
        a.href = cfg.url || cfg.data || "#";
        a.download = cfg.filename || "download";
        document.body.appendChild(a); a.click(); a.remove();
      });
    });
  };

  // ----- "View larger" modal (charts, maps, images, code) ------------------
  Pixie.modal = {
    open: function (contentNode) {
      Pixie.modal.close();
      var overlay = document.createElement("div");
      overlay.className = "pixie-modal";
      overlay.setAttribute("role", "dialog");
      overlay.setAttribute("aria-modal", "true");
      overlay.innerHTML =
        '<div class="pixie-modal__sheet">' +
          '<button type="button" class="btn btn--ghost btn--icon pixie-modal__close" aria-label="Close">' +
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>' +
          '</button>' +
          '<div class="pixie-modal__body"></div>' +
        '</div>';
      overlay.querySelector(".pixie-modal__body").appendChild(contentNode);
      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) Pixie.modal.close();
      });
      overlay.querySelector(".pixie-modal__close").addEventListener("click", Pixie.modal.close);
      document.body.appendChild(overlay);
      Pixie._modalEsc = function (e) { if (e.key === "Escape") Pixie.modal.close(); };
      document.addEventListener("keydown", Pixie._modalEsc);
    },
    close: function () {
      var existing = document.querySelector(".pixie-modal");
      if (existing) existing.remove();
      if (Pixie._modalEsc) {
        document.removeEventListener("keydown", Pixie._modalEsc);
        Pixie._modalEsc = null;
      }
    }
  };

  Pixie.initExpand = function (root) {
    (root || document).querySelectorAll("[data-pixie-expand]:not([data-bound])").forEach(function (btn) {
      btn.dataset.bound = "1";
      btn.addEventListener("click", function () {
        var card = btn.closest(".output-card");
        if (!card) return;
        var clone = card.cloneNode(true);
        clone.classList.add("output-card--expanded");
        clone.querySelectorAll("[data-pixie-expand]").forEach(function (b) { b.remove(); });
        Pixie.modal.open(clone);
        // re-initialise visualisations inside the clone
        Pixie.runOutputInit(clone);
      });
    });
  };

  // ----- CodeMirror read-only (for `code` outputs) -------------------------
  Pixie.initCodeOutputs = function (root) {
    (root || document).querySelectorAll("textarea[data-pixie-code-out]:not([data-init])").forEach(function (ta) {
      ta.dataset.init = "1";
      if (typeof CodeMirror === "undefined") {
        var tries = 0;
        var iv = setInterval(function () {
          if (typeof CodeMirror !== "undefined" || tries++ > 40) {
            clearInterval(iv);
            if (typeof CodeMirror !== "undefined") { delete ta.dataset.init; Pixie.initCodeOutputs(ta.parentElement); }
          }
        }, 100);
        return;
      }
      var lang = ta.dataset.language || "text";
      var modeMap = {
        python: "python", py: "python",
        sql: "text/x-sql", javascript: "javascript", js: "javascript",
        json: { name: "javascript", json: true },
        ts: "javascript", typescript: "javascript",
        html: "htmlmixed", xml: "xml"
      };
      var dark = Pixie.isDark();
      CodeMirror.fromTextArea(ta, {
        mode: modeMap[lang] || "text/plain",
        theme: dark ? "material-darker" : "neo",
        lineNumbers: true,
        readOnly: "nocursor",
        viewportMargin: Infinity,
        lineWrapping: false
      });
    });
  };

  document.addEventListener("pixie:theme-changed", function () {
    var dark = Pixie.isDark();
    document.querySelectorAll(".CodeMirror").forEach(function (cm) {
      if (cm.CodeMirror) cm.CodeMirror.setOption("theme", dark ? "material-darker" : "neo");
    });
  });

  // ----- diff2html ---------------------------------------------------------
  Pixie.initDiffs = function (root) {
    (root || document).querySelectorAll(".output-diff:not([data-init])").forEach(function (el) {
      el.dataset.init = "1";
      var cfg = readJsonScript(el.querySelector("script[type='application/json']"));
      if (!cfg) return;
      var target = el.querySelector(".output-diff__view");
      if (!target) return;
      if (typeof Diff2HtmlUI === "undefined" || typeof Diff === "undefined") {
        target.innerHTML = '<pre class="output-pre">' +
          (cfg.before || "").replace(/[<>&]/g, function (c) { return ({ "<":"&lt;",">":"&gt;","&":"&amp;" })[c]; }) +
          "\n--- diff ---\n" +
          (cfg.after || "").replace(/[<>&]/g, function (c) { return ({ "<":"&lt;",">":"&gt;","&":"&amp;" })[c]; }) +
          '</pre>';
        return;
      }
      var diffStr = Diff.createTwoFilesPatch(
        cfg.filename_before || "before",
        cfg.filename_after  || "after",
        cfg.before || "", cfg.after || ""
      );
      var format = (target.offsetWidth >= 800) ? "side-by-side" : "line-by-line";
      var ui = new Diff2HtmlUI(target, diffStr, {
        drawFileList: false, matching: "lines",
        outputFormat: format, highlight: true
      });
      ui.draw();
    });
  };

  // ----- Log stream ---------------------------------------------------------
  Pixie.initLogs = function (root) {
    (root || document).querySelectorAll(".output-log:not([data-init])").forEach(function (el) {
      el.dataset.init = "1";
      var scroller = el.querySelector(".output-log__lines");
      var follow = true;
      if (scroller) {
        scroller.addEventListener("scroll", function () {
          var near = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 8;
          follow = near;
        });
        // initial scroll to bottom
        scroller.scrollTop = scroller.scrollHeight;
      }
      // expose append for the streaming protocol
      el.pixieAppendLogLines = function (lines) {
        if (!scroller || !lines || !lines.length) return;
        var html = lines.map(Pixie.renderLogLine).join("");
        scroller.insertAdjacentHTML("beforeend", html);
        if (follow) scroller.scrollTop = scroller.scrollHeight;
      };
      // filter select
      var sel = el.querySelector("[data-log-filter]");
      if (sel) sel.addEventListener("change", function () {
        el.setAttribute("data-level", sel.value || "all");
      });
    });
  };
  Pixie.renderLogLine = function (line) {
    var t = line.t ? String(line.t) : "";
    var lvl = (line.level || "info").toUpperCase();
    var msg = String(line.message || "")
      .replace(/[&<>]/g, function (c) { return ({ "&":"&amp;", "<":"&lt;", ">":"&gt;" })[c]; });
    return '<div class="log-line" data-level="' + (line.level || "info").toLowerCase() + '">' +
      '<span class="log-line__t mono">' + t + '</span>' +
      '<span class="log-line__lvl mono">' + lvl + '</span>' +
      '<span class="log-line__msg">' + msg + '</span>' +
      '</div>';
  };

  // ----- Tree view ----------------------------------------------------------
  Pixie.initTrees = function (root) {
    (root || document).querySelectorAll(".output-tree:not([data-init])").forEach(function (el) {
      el.dataset.init = "1";
      el.querySelectorAll("[data-tree-toggle]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var li = btn.closest("li");
          if (li) li.classList.toggle("is-collapsed");
        });
      });
      var bar = el.querySelector(".output-tree__bar");
      if (bar) bar.addEventListener("click", function (e) {
        var act = e.target.closest("[data-tree-act]");
        if (!act) return;
        if (act.dataset.treeAct === "expand") {
          el.querySelectorAll("li.is-collapsed").forEach(function (li) { li.classList.remove("is-collapsed"); });
        } else if (act.dataset.treeAct === "collapse") {
          el.querySelectorAll("li[data-has-children]").forEach(function (li) { li.classList.add("is-collapsed"); });
        }
      });
    });
  };

  // ----- Image compare slider ----------------------------------------------
  Pixie.initImageCompare = function (root) {
    (root || document).querySelectorAll(".output-image-compare:not([data-init])").forEach(function (wrap) {
      wrap.dataset.init = "1";
      var clip = wrap.querySelector(".output-image-compare__clip");
      var handle = wrap.querySelector(".output-image-compare__handle");
      var range = wrap.querySelector(".output-image-compare__range");
      function set(pct) {
        clip.style.width = pct + "%";
        handle.style.left = pct + "%";
      }
      set(50);
      if (range) range.addEventListener("input", function () { set(Number(range.value)); });
    });
  };

  // ----- Markdown (marked.js) -----------------------------------------------
  Pixie.renderMarkdown = function (el) {
    if (typeof window.marked === "undefined") {
      // marked is loaded on demand if a markdown output exists; defer if not yet.
      var tries = 0;
      var iv = setInterval(function () {
        if (typeof window.marked !== "undefined" || tries++ > 40) {
          clearInterval(iv);
          if (typeof window.marked !== "undefined") Pixie.renderMarkdown(el);
        }
      }, 100);
      return;
    }
    var src = el.getAttribute("data-md-source") || el.textContent || "";
    try {
      el.innerHTML = window.marked.parse(src, { gfm: true, breaks: false });
    } catch (e) {
      el.textContent = src;
    }
  };
  Pixie.initMarkdownOutputs = function (root) {
    (root || document).querySelectorAll(".output-md:not([data-init])").forEach(function (el) {
      el.dataset.init = "1";
      Pixie.renderMarkdown(el);
    });
  };

  // ----- Number stat formatting --------------------------------------------
  Pixie.initStats = function (root) {
    (root || document).querySelectorAll(".output-stat:not([data-init])").forEach(function (el) {
      el.dataset.init = "1";
      var raw = el.dataset.statValue;
      if (raw === undefined) return;
      var format = el.dataset.statFormat || "decimal";
      var precision = el.dataset.statPrecision ? Number(el.dataset.statPrecision) : null;
      var unit = el.dataset.statUnit || "";
      var num = Number(raw);
      var target = el.querySelector(".stat__value");
      if (target) target.textContent = Pixie.formatNumber(num, {
        format: format, precision: precision
      }) + (unit ? "" : "");
    });
  };

  // ----- KaTeX init wrapper ------------------------------------------------
  Pixie.initLatex = function (root) {
    (root || document).querySelectorAll(".output-latex:not([data-init])").forEach(function (el) {
      el.dataset.init = "1";
      Pixie.renderLatex(el);
    });
  };

  // ----- Network chart (force layout, ~40 lines, vanilla) ------------------
  Pixie.initNetwork = function (root) {
    (root || document).querySelectorAll(".output-network:not([data-init])").forEach(function (el) {
      el.dataset.init = "1";
      var cfg = readJsonScript(el.querySelector("script[type='application/json']"));
      if (!cfg || !cfg.nodes) return;
      var nodes = cfg.nodes.map(function (n) {
        return Object.assign({ x: 0, y: 0, vx: 0, vy: 0 }, n);
      });
      var edges = (cfg.edges || []).map(function (e) {
        return {
          source: nodes.find(function (n) { return n.id === e.source; }),
          target: nodes.find(function (n) { return n.id === e.target; })
        };
      }).filter(function (e) { return e.source && e.target; });
      // Circular initial layout
      var R = 0.4;
      nodes.forEach(function (n, i) {
        if (n.x == null || n.x === 0) {
          var theta = (i / nodes.length) * Math.PI * 2;
          n.x = 0.5 + R * Math.cos(theta);
          n.y = 0.5 + R * Math.sin(theta);
        }
      });
      // 80 iterations of a tiny spring-electrical layout
      var k = 0.6 / Math.sqrt(nodes.length);
      for (var iter = 0; iter < 80; iter++) {
        nodes.forEach(function (n) {
          n.vx = 0; n.vy = 0;
          nodes.forEach(function (m) {
            if (m === n) return;
            var dx = n.x - m.x, dy = n.y - m.y;
            var d2 = dx * dx + dy * dy + 0.001;
            var f = (k * k) / d2;
            n.vx += dx * f; n.vy += dy * f;
          });
        });
        edges.forEach(function (e) {
          var dx = e.target.x - e.source.x, dy = e.target.y - e.source.y;
          var d = Math.sqrt(dx * dx + dy * dy) + 0.001;
          var f = (d - k) * 0.25;
          var ax = (dx / d) * f, ay = (dy / d) * f;
          e.source.vx += ax; e.source.vy += ay;
          e.target.vx -= ax; e.target.vy -= ay;
        });
        nodes.forEach(function (n) {
          n.x += n.vx * 0.08; n.y += n.vy * 0.08;
          n.x = Math.max(0.05, Math.min(0.95, n.x));
          n.y = Math.max(0.05, Math.min(0.95, n.y));
        });
      }
      // Render to Plotly
      var edgeX = [], edgeY = [];
      edges.forEach(function (e) {
        edgeX.push(e.source.x, e.target.x, null);
        edgeY.push(e.source.y, e.target.y, null);
      });
      var traces = [
        { type: "scatter", mode: "lines", x: edgeX, y: edgeY,
          line: { width: 1, color: "rgba(120,120,128,0.4)" }, hoverinfo: "none", showlegend: false },
        { type: "scatter", mode: "markers+text",
          x: nodes.map(function (n) { return n.x; }),
          y: nodes.map(function (n) { return n.y; }),
          text: nodes.map(function (n) { return n.label || n.id; }),
          textposition: "bottom center",
          marker: { size: 12, color: cssVar("--accent") || "#5b6cd1",
                    line: { width: 1, color: cssVar("--bg") || "#fff" } },
          hovertemplate: "%{text}<extra></extra>", showlegend: false }
      ];
      var layoutOverride = {
        xaxis: { visible: false, range: [0, 1] },
        yaxis: { visible: false, range: [0, 1] },
        margin: { l: 8, r: 8, t: 8, b: 8 }
      };
      var canvas = el.querySelector(".output-network__plot");
      if (canvas) Pixie.makeChart(canvas, traces, layoutOverride);
    });
  };

  // ----- Universal "init this subtree" -------------------------------------
  Pixie.runOutputInit = function (root) {
    try { Pixie.initCopyButtons(root);    } catch (e) { console.warn(e); }
    try { Pixie.initDownloads(root);      } catch (e) { console.warn(e); }
    try { Pixie.initExpand(root);         } catch (e) { console.warn(e); }
    try { Pixie.initStats(root);          } catch (e) { console.warn(e); }
    try { Pixie.initTables(root);         } catch (e) { console.warn(e); }
    try { Pixie.initMarkdownOutputs(root); } catch (e) { console.warn(e); }
    try { Pixie.initLatex(root);          } catch (e) { console.warn(e); }
    try { Pixie.initCodeOutputs(root);    } catch (e) { console.warn(e); }
    try { Pixie.initDiffs(root);          } catch (e) { console.warn(e); }
    try { Pixie.initLogs(root);           } catch (e) { console.warn(e); }
    try { Pixie.initTrees(root);          } catch (e) { console.warn(e); }
    try { Pixie.initImageCompare(root);   } catch (e) { console.warn(e); }
    try { Pixie.initNetwork(root);        } catch (e) { console.warn(e); }
    // Chart / map partials each emit their own init <script>, so they
    // bind themselves on first paint; nothing to do here.
  };

  Pixie.initOnSwap(function (root) { Pixie.runOutputInit(root); });

})();

/* =============================================================
   Pixie Phase 8 additions:
     - data-pixie-copy delegation (clipboard + toast)
     - 12-line fuzzy scorer
     - Cmd/Ctrl+K quick switcher
     - Right-click contextual menu (sidebar, run rows, output cards)
   No external dependencies. Reuses window.Pixie.toast().
   ============================================================= */
(function () {
  "use strict";
  if (!window.Pixie) window.Pixie = {};
  var Pixie = window.Pixie;

  // ---------- Toast back-compat (object API used in templates) -----
  if (typeof Pixie.toast === "function") {
    var legacyToast = Pixie.toast;
    var fn = function (textOrOpts, opts) {
      if (textOrOpts && typeof textOrOpts === "object" && !opts) {
        var o = textOrOpts;
        return legacyToast(o.message || "", { type: o.kind || o.type || "info", ttl: o.timeout || o.ttl });
      }
      return legacyToast(textOrOpts, opts);
    };
    fn.show = function (o) { return fn(o); };
    Pixie.toast = fn;
  }

  // ---------- Clipboard ---------------------------------------------
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text; ta.setAttribute("readonly", "");
        ta.style.position = "absolute"; ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        resolve();
      } catch (e) { reject(e); }
    });
  }
  Pixie.copy = copyText;
  Pixie.copyAndToast = function (text, toastMsg) {
    return copyText(text).then(function () {
      Pixie.toast(toastMsg || "Copied.", { type: "info", ttl: 2400 });
    }).catch(function () {
      Pixie.toast("Copy failed — clipboard blocked.", { type: "error", ttl: 4000 });
    });
  };

  document.addEventListener("click", function (evt) {
    var t = evt.target;
    while (t && t !== document.body) {
      if (t.getAttribute && t.hasAttribute("data-pixie-copy")) {
        evt.preventDefault();
        var text = t.getAttribute("data-pixie-copy");
        var msg = t.getAttribute("data-pixie-copy-toast") || "Copied.";
        Pixie.copyAndToast(text, msg);
        return;
      }
      t = t.parentNode;
    }
  });

  // ---------- Fuzzy scorer (~12 lines, no dependency) --------------
  Pixie.fuzzy = {
    score: function (haystack, needle) {
      if (!needle) return 1;
      var h = String(haystack || "").toLowerCase();
      var n = String(needle).toLowerCase();
      var hi = 0, ni = 0, score = 0, run = 0;
      while (hi < h.length && ni < n.length) {
        if (h.charCodeAt(hi) === n.charCodeAt(ni)) {
          run += 1; score += 1 + run * 2;
          if (hi === 0 || /[\s\-_/.]/.test(h.charAt(hi - 1))) score += 4;
          ni += 1;
        } else { run = 0; }
        hi += 1;
      }
      return ni === n.length ? score : 0;
    }
  };

  // ---------- Tool payload reader ----------------------------------
  function readToolsPayload() {
    var el = document.getElementById("pixie-tools-payload");
    if (!el) return [];
    try { return JSON.parse(el.textContent || "[]"); }
    catch (e) { return []; }
  }
  function refreshToolsPayload() { window.PIXIE_TOOLS = readToolsPayload(); }
  refreshToolsPayload();
  document.addEventListener("htmx:afterSettle", refreshToolsPayload);

  // ---------- Quick switcher (Cmd/Ctrl+K) --------------------------
  var QS = {
    root: null, input: null, list: null,
    items: [], cursor: 0, lastFocus: null,
    init: function () {
      this.root = document.getElementById("pixie-qs");
      if (!this.root) return;
      this.input = document.getElementById("pixie-qs-input");
      this.list = document.getElementById("pixie-qs-list");
      var self = this;
      this.input.addEventListener("input", function () { self.render(); });
      this.input.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown") { e.preventDefault(); self.move(1); }
        else if (e.key === "ArrowUp") { e.preventDefault(); self.move(-1); }
        else if (e.key === "Enter") { e.preventDefault(); self.pick(); }
        else if (e.key === "Escape") { e.preventDefault(); self.close(); }
      });
      this.root.querySelectorAll("[data-pixie-qs-dismiss]").forEach(function (el) {
        el.addEventListener("click", function () { self.close(); });
      });
    },
    open: function () {
      if (!this.root) this.init();
      if (!this.root) return;
      this.lastFocus = document.activeElement;
      this.root.hidden = false;
      this.input.value = "";
      this.cursor = 0;
      this.render();
      var self = this;
      setTimeout(function () { self.input.focus(); }, 0);
    },
    close: function () {
      if (!this.root) return;
      this.root.hidden = true;
      if (this.lastFocus && this.lastFocus.focus) this.lastFocus.focus();
    },
    filtered: function () {
      var q = (this.input.value || "").trim();
      var tools = window.PIXIE_TOOLS || [];
      if (!q) return tools.slice(0, 50);
      var scored = tools.map(function (t) {
        var hay = (t.name || "") + " " + (t.category || "") + " " + (t.id || "");
        return { t: t, s: Pixie.fuzzy.score(hay, q) };
      }).filter(function (x) { return x.s > 0; });
      scored.sort(function (a, b) { return b.s - a.s; });
      return scored.map(function (x) { return x.t; }).slice(0, 50);
    },
    render: function () {
      this.items = this.filtered();
      if (this.cursor >= this.items.length) this.cursor = 0;
      if (this.items.length === 0) {
        this.list.innerHTML = '<li class="pixie-qs__empty">No matches.</li>';
        return;
      }
      var html = "";
      for (var i = 0; i < this.items.length; i++) {
        var t = this.items[i];
        var cls = "pixie-qs__row" + (i === this.cursor ? " is-active" : "");
        var state = t.status || "dormant";
        html += '<li class="' + cls + '" role="option" data-i="' + i + '" data-id="' +
          encodeURIComponent(t.id) + '">' +
          '<span class="dot dot--' + state + '"></span>' +
          '<span>' + escapeHTML(t.name || t.id) + '</span>' +
          '<span class="pixie-qs__row-category mono">' + escapeHTML(t.category || "") + '</span>' +
          '</li>';
      }
      this.list.innerHTML = html;
      var self = this;
      this.list.querySelectorAll(".pixie-qs__row").forEach(function (row) {
        row.addEventListener("mouseenter", function () {
          self.cursor = parseInt(row.getAttribute("data-i"), 10); self.refreshActive();
        });
        row.addEventListener("click", function () { self.pick(); });
      });
    },
    refreshActive: function () {
      var rows = this.list.querySelectorAll(".pixie-qs__row");
      for (var i = 0; i < rows.length; i++) {
        rows[i].classList.toggle("is-active", i === this.cursor);
      }
    },
    move: function (delta) {
      if (!this.items.length) return;
      this.cursor = (this.cursor + delta + this.items.length) % this.items.length;
      this.refreshActive();
      var active = this.list.querySelector(".pixie-qs__row.is-active");
      if (active && active.scrollIntoView) active.scrollIntoView({ block: "nearest" });
    },
    pick: function () {
      var t = this.items[this.cursor];
      if (!t) return;
      var url = "/tool/" + t.id;
      this.close();
      if (window.htmx) {
        window.htmx.ajax("GET", url, { target: "#pixie-main-content", swap: "innerHTML" });
        if (window.history && window.history.pushState) {
          window.history.pushState({}, "", url);
        }
      } else {
        window.location.href = url;
      }
    }
  };
  Pixie.qs = QS;

  function escapeHTML(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  document.addEventListener("keydown", function (e) {
    var k = e.key && e.key.toLowerCase();
    if ((e.metaKey || e.ctrlKey) && k === "k") {
      e.preventDefault();
      if (QS.root && !QS.root.hidden) QS.close(); else QS.open();
    }
  });

  // ---------- Context menu ----------------------------------------
  var CTX = {
    root: null, items: [], cursor: -1, openFor: null,
    init: function () {
      this.root = document.getElementById("pixie-ctxmenu");
      if (!this.root) return;
      var self = this;
      document.addEventListener("click", function (e) {
        if (self.root.hidden) return;
        if (!self.root.contains(e.target)) self.close();
      });
      document.addEventListener("keydown", function (e) {
        if (self.root.hidden) return;
        if (e.key === "Escape") { e.preventDefault(); self.close(); }
        else if (e.key === "ArrowDown") { e.preventDefault(); self.move(1); }
        else if (e.key === "ArrowUp") { e.preventDefault(); self.move(-1); }
        else if (e.key === "Enter") { e.preventDefault(); self.activate(); }
      });
      window.addEventListener("resize", function () { self.close(); });
      window.addEventListener("scroll", function () { self.close(); }, true);
    },
    open: function (x, y, items, originEl) {
      if (!this.root) this.init();
      if (!this.root) return;
      this.items = items || [];
      this.cursor = -1;
      this.openFor = originEl || null;
      var html = "";
      for (var i = 0; i < this.items.length; i++) {
        var it = this.items[i];
        if (it.divider) { html += '<div class="pixie-ctxmenu__divider"></div>'; continue; }
        var cls = "pixie-ctxmenu__item" + (it.danger ? " pixie-ctxmenu__item--danger" : "");
        html += '<button type="button" class="' + cls + '" data-i="' + i +
          '" role="menuitem">' + escapeHTML(it.label) + "</button>";
      }
      this.root.innerHTML = html;
      var self = this;
      this.root.querySelectorAll("[data-i]").forEach(function (el) {
        el.addEventListener("mouseenter", function () {
          self.cursor = parseInt(el.getAttribute("data-i"), 10); self.refresh();
        });
        el.addEventListener("click", function (e) {
          e.preventDefault();
          self.cursor = parseInt(el.getAttribute("data-i"), 10); self.activate();
        });
      });
      this.root.hidden = false;
      // Position, with viewport-edge avoidance
      var w = this.root.offsetWidth || 200;
      var h = this.root.offsetHeight || 100;
      var px = Math.min(x, window.innerWidth - w - 8);
      var py = Math.min(y, window.innerHeight - h - 8);
      this.root.style.left = Math.max(0, px) + "px";
      this.root.style.top = Math.max(0, py) + "px";
    },
    close: function () {
      if (!this.root || this.root.hidden) return;
      this.root.hidden = true;
      this.items = []; this.cursor = -1; this.openFor = null;
    },
    move: function (d) {
      if (!this.items.length) return;
      var n = this.items.length, c = this.cursor;
      for (var step = 0; step < n; step++) {
        c = (c + d + n) % n;
        if (!this.items[c].divider) { this.cursor = c; this.refresh(); return; }
      }
    },
    refresh: function () {
      var rows = this.root.querySelectorAll("[data-i]");
      for (var i = 0; i < rows.length; i++) {
        var idx = parseInt(rows[i].getAttribute("data-i"), 10);
        rows[i].classList.toggle("is-active", idx === this.cursor);
      }
    },
    activate: function () {
      if (this.cursor < 0 || this.cursor >= this.items.length) return;
      var it = this.items[this.cursor];
      this.close();
      if (typeof it.action === "function") it.action();
    }
  };
  Pixie.ctxmenu = CTX;

  // Sidebar tool-row contextmenu wiring (delegated, survives htmx swaps)
  document.addEventListener("contextmenu", function (e) {
    var row = e.target.closest && e.target.closest(".tool-row");
    if (!row) return;
    e.preventDefault();
    var href = row.getAttribute("href") || "";
    var toolId = href.replace(/^\/tool\//, "");
    if (!toolId) return;
    var nameEl = row.querySelector(".tool-row__name");
    var toolName = nameEl ? nameEl.textContent.trim() : toolId;
    CTX.open(e.clientX, e.clientY, [
      {
        label: "Re-validate", action: function () {
          if (window.htmx) {
            window.htmx.ajax("POST", "/api/tools/" + toolId + "/validate", {
              target: "#pixie-main-content", swap: "innerHTML"
            });
          }
          Pixie.toast("Re-validating " + toolName + "…", { type: "info", ttl: 2400 });
        }
      },
      {
        label: "View source", action: function () {
          if (window.htmx) {
            window.htmx.ajax("GET", "/tool/" + toolId + "/settings#schema", {
              target: "#pixie-main-content", swap: "innerHTML"
            });
          } else {
            window.location.href = "/tool/" + toolId + "/settings#schema";
          }
        }
      },
      {
        label: "Settings", action: function () {
          if (window.htmx) {
            window.htmx.ajax("GET", "/tool/" + toolId + "/settings", {
              target: "#pixie-main-content", swap: "innerHTML"
            });
          } else {
            window.location.href = "/tool/" + toolId + "/settings";
          }
        }
      },
      { divider: true },
      {
        label: "Remove via Claude Code…", danger: true, action: function () {
          Pixie.copyAndToast(
            "In Claude Code, run: remove the " + toolId + " Pixie tool.",
            "Prompt copied. Paste into Claude Code."
          );
        }
      }
    ], row);
  });

  // Run-row contextmenu (best-effort — targets future history rows)
  document.addEventListener("contextmenu", function (e) {
    var row = e.target.closest && e.target.closest("[data-run-id]");
    if (!row) return;
    e.preventDefault();
    var runId = row.getAttribute("data-run-id");
    var inputs = row.getAttribute("data-run-inputs") || "{}";
    CTX.open(e.clientX, e.clientY, [
      {
        label: "Copy run ID", action: function () {
          Pixie.copyAndToast(runId, "Run ID copied.");
        }
      },
      {
        label: "Copy inputs as JSON", action: function () {
          Pixie.copyAndToast(inputs, "Inputs copied.");
        }
      },
      { divider: true },
      {
        label: "Delete run", danger: true, action: function () {
          if (window.htmx) {
            window.htmx.ajax("DELETE", row.getAttribute("data-delete-url") || "", {
              swap: "outerHTML", target: "[data-run-id=\"" + runId + "\"]"
            });
          }
        }
      }
    ], row);
  });

  // Output-card contextmenu
  document.addEventListener("contextmenu", function (e) {
    var card = e.target.closest && e.target.closest(".output-card");
    if (!card) return;
    e.preventDefault();
    var copyTarget = card.querySelector("[data-pixie-copy], pre, .output-card__body");
    var text = copyTarget ? (copyTarget.getAttribute("data-pixie-copy") || copyTarget.innerText || "") : "";
    CTX.open(e.clientX, e.clientY, [
      {
        label: "Copy", action: function () {
          Pixie.copyAndToast(text, "Copied.");
        }
      },
      {
        label: "Download as text", action: function () {
          try {
            var blob = new Blob([text], { type: "text/plain" });
            var a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = "pixie-output.txt";
            document.body.appendChild(a); a.click();
            setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
          } catch (err) {
            Pixie.toast("Download failed.", { type: "error" });
          }
        }
      },
      {
        label: "View larger", action: function () {
          var modal = document.getElementById("pixie-output-modal");
          if (modal) {
            modal.removeAttribute("hidden");
          } else {
            // Fallback: open in new window
            var w = window.open("", "_blank");
            if (w) { w.document.write("<pre style=\"font:13px/1.6 monospace; padding:24px;\">" + escapeHTML(text) + "</pre>"); }
          }
        }
      }
    ], card);
  });

})();

/* ============================================================== */
/* Library + Save-as helpers (Wave 2)                              */
/* ============================================================== */
(function () {
  if (!window.Pixie) window.Pixie = {};

  function getArtefactIdFor(card) {
    if (!card) return null;
    // Cards rendered live during a run may carry data-artefact-id once
    // the post-run scan completes. Library cards always do.
    if (card.dataset.artefactId) return Number(card.dataset.artefactId);
    return null;
  }

  Pixie.loadSaveAsFormats = async function (card) {
    if (!card) return;
    const button = card.querySelector('[data-pixie-saveas]');
    const menu = card.querySelector('.output-card__saveas-menu');
    if (!button || !menu) return;
    if (menu.dataset.loaded) return;
    const artefactId = getArtefactIdFor(card);
    if (!artefactId) {
      menu.innerHTML = '<span class="t-meta">Run the tool to enable export.</span>';
      menu.dataset.loaded = '1';
      return;
    }
    try {
      const resp = await fetch(`/api/artefacts/${artefactId}/formats`);
      if (!resp.ok) {
        menu.innerHTML = '<span class="t-meta">No exporters available.</span>';
      } else {
        const body = await resp.json();
        const formats = body.supported || [];
        if (!formats.length) {
          menu.innerHTML = '<span class="t-meta">No exporters registered.</span>';
        } else {
          const ul = document.createElement('ul');
          for (const fmt of formats) {
            const li = document.createElement('li');
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn--ghost btn--sm';
            btn.textContent = fmt.toUpperCase();
            btn.addEventListener('click', function () {
              Pixie.saveArtefactAs(artefactId, fmt);
            });
            li.appendChild(btn);
            ul.appendChild(li);
          }
          menu.replaceChildren(ul);
        }
      }
    } catch (err) {
      menu.innerHTML = '<span class="t-meta">Format lookup failed.</span>';
    }
    menu.dataset.loaded = '1';
  };

  Pixie.saveArtefactAs = function (artefactId, fmt) {
    const url = `/api/artefacts/${artefactId}/export?format=${encodeURIComponent(fmt)}`;
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  Pixie.copyArtefact = async function (artefactId) {
    try {
      const resp = await fetch(`/api/clipboard?artefact_id=${artefactId}`);
      if (!resp.ok) return false;
      const text = await resp.text();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      }
      window.dispatchEvent(new CustomEvent('pixie:toast', {
        detail: { message: 'Copied to clipboard.' },
      }));
      return true;
    } catch (err) { return false; }
  };

  // Keyboard shortcuts: Ctrl/Cmd+S = save default; Ctrl/Cmd+Shift+C = copy.
  document.addEventListener('keydown', function (ev) {
    const card = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest('.output-card, .library-card')
      : null;
    if (!card) return;
    const artefactId = getArtefactIdFor(card);
    if (!artefactId) return;
    const isSave = (ev.ctrlKey || ev.metaKey) && !ev.shiftKey && ev.key.toLowerCase() === 's';
    const isCopy = (ev.ctrlKey || ev.metaKey) && ev.shiftKey && ev.key.toLowerCase() === 'c';
    if (isSave) {
      ev.preventDefault();
      fetch(`/api/artefacts/${artefactId}/formats`).then(r => r.json()).then(body => {
        if (body.default) Pixie.saveArtefactAs(artefactId, body.default);
      });
    } else if (isCopy) {
      ev.preventDefault();
      Pixie.copyArtefact(artefactId);
    }
  });

  // Re-fetch the library grid in place without a full page reload.
  // Preserves filters/sort by inspecting the search form on the page.
  Pixie.refreshLibraryGrid = function () {
    const grid = document.getElementById('library-grid');
    if (!grid) return;
    const form = document.querySelector('.library__search');
    const params = new URLSearchParams();
    if (form) {
      form.querySelectorAll('input[name], select[name]').forEach(el => {
        if (el.value !== '' && el.value != null) params.set(el.name, el.value);
      });
    }
    const url = '/library/_grid' + (params.toString() ? `?${params}` : '');
    if (window.htmx) {
      window.htmx.ajax('GET', url, { target: '#library-grid', swap: 'innerHTML' });
    } else {
      fetch(url).then(r => r.text()).then(html => { grid.innerHTML = html; });
    }
  };

  function _libraryToast(msg, kind) {
    window.dispatchEvent(new CustomEvent('pixie:toast', { detail: { message: msg, kind: kind || 'info' }}));
  }

  function _animateCardRemoval(card, done) {
    if (!card) { done && done(); return; }
    card.style.transition = 'opacity .18s ease, transform .18s ease';
    card.style.opacity = '0';
    card.style.transform = 'scale(.96)';
    setTimeout(() => { card.remove(); done && done(); }, 200);
  }

  function _updateLibraryCount(delta) {
    const total = document.getElementById('library-total');
    if (!total) return;
    const n = Math.max(0, (parseInt(total.textContent, 10) || 0) + delta);
    total.textContent = String(n);
  }

  // Library card actions: star + delete -- optimistic, no full reload.
  document.addEventListener('click', function (ev) {
    const target = ev.target.closest('[data-action]');
    if (!target) return;
    const action = target.dataset.action;
    const artefactId = Number(target.dataset.artefactId);
    if (!artefactId) return;
    const card = target.closest('.library-card');

    if (action === 'star') {
      ev.preventDefault();
      const isStarred = card && card.classList.contains('is-starred');
      const endpoint = isStarred ? 'unstar' : 'star';
      // Optimistic flip.
      if (card) {
        card.classList.toggle('is-starred', !isStarred);
        const btn = card.querySelector('.library-card__star-btn');
        if (btn) {
          btn.setAttribute('aria-pressed', String(!isStarred));
          btn.title = isStarred ? 'Star' : 'Unstar';
          btn.querySelector('span').textContent = isStarred ? '☆' : '★';
        }
      }
      fetch(`/api/artefacts/${artefactId}/${endpoint}`, { method: 'POST' })
        .then(r => {
          if (!r.ok) throw new Error('star failed');
          // If we're on a "starred-only" view and we just unstarred, drop the card.
          const onStarredView = new URLSearchParams(window.location.search).get('starred') === 'true';
          if (onStarredView && isStarred) {
            _animateCardRemoval(card, () => {
              _updateLibraryCount(-1);
              if (window.libraryPage) {
                const lp = document.querySelector('.library')?.__x?.$data;
                if (lp) lp.refreshCount && lp.refreshCount();
              }
            });
          }
        })
        .catch(() => {
          _libraryToast('Star failed — reverted.', 'error');
          if (card) {
            card.classList.toggle('is-starred', isStarred);
          }
        });
    } else if (action === 'delete') {
      ev.preventDefault();
      if (!confirm('Move this artefact to trash?')) return;
      fetch(`/api/artefacts/${artefactId}`, { method: 'DELETE' })
        .then(r => {
          if (!r.ok) throw new Error('delete failed');
          _animateCardRemoval(card, () => {
            _updateLibraryCount(-1);
            _libraryToast('Moved to trash.');
            // Refresh grid if it becomes empty so the empty state renders.
            if (!document.querySelector('.library-card')) {
              Pixie.refreshLibraryGrid && Pixie.refreshLibraryGrid();
            }
          });
        })
        .catch(() => _libraryToast('Delete failed.', 'error'));
    }
  });

  // After every HTMX swap on the library page, sync the visible count
  // and drop any stale selection ids whose cards are gone.
  document.body.addEventListener('htmx:afterSwap', function (ev) {
    if (!ev.target || ev.target.id !== 'library-grid') return;
    const total = document.getElementById('library-total');
    if (total) {
      // No-op; total is server-rendered so it stays accurate.
    }
    // Tell Alpine the library page's selection may need pruning.
    window.dispatchEvent(new CustomEvent('pixie:library-grid-swapped'));
  });
})();

/* ============================================================
 * Scale features — sidebar virtualisation, hover-prewarm,
 * workspace switcher hooks, /tools grid Alpine state.
 * RESEARCH_scale.md s2.3, s2.6, s6.6.
 * ============================================================ */
(function () {
  if (!window.Pixie) window.Pixie = {};

  /* ---- Sidebar virtualisation ----
   * Only activate when the scroll container has data-pixie-virtualise="1"
   * (server sets this when total tool count > 30). Hides off-screen
   * sections via display:none until they enter the viewport ± 400px.
   */
  Pixie.sidebarVirtualise = function () {
    var scrollers = document.querySelectorAll('.sidebar__scroll[data-pixie-virtualise="1"]');
    scrollers.forEach(function (root) {
      if (root.dataset.pixieVirtualised === '1') return;
      root.dataset.pixieVirtualised = '1';
      var sections = root.querySelectorAll('.sidebar__section');
      if (!sections.length || sections.length <= 4) return;
      sections.forEach(function (section, idx) {
        if (idx < 2) return; // first two stay always-mounted
        var body = section.querySelector('.sidebar__section-body');
        if (!body) return;
        body.dataset.pixieVirtualHidden = '1';
        body.style.display = 'none';
      });
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          var section = entry.target;
          var body = section.querySelector('.sidebar__section-body');
          if (!body) return;
          if (entry.isIntersecting) {
            body.style.display = '';
          } else {
            // Only re-hide if scrolled well clear (1000px buffer via rootMargin).
            body.style.display = 'none';
          }
        });
      }, { root: root, rootMargin: '400px 0px 1000px 0px', threshold: 0 });
      sections.forEach(function (section, idx) {
        if (idx >= 2) observer.observe(section);
      });
    });
  };

  /* ---- Hover-prewarm ----
   * Fire-and-forget POST to /api/tools/{id}/prewarm after 400ms hover.
   * Only active when body[data-dev-mode="true"]. Per-tool throttle of 30s.
   */
  var prewarmThrottle = {};
  Pixie.hoverPrewarm = function () {
    var dev = document.body && document.body.getAttribute('data-dev-mode') === 'true';
    if (!dev) return;
    var rows = document.querySelectorAll('.tool-row[data-tool-id]');
    rows.forEach(function (row) {
      if (row.dataset.pixiePrewarmBound === '1') return;
      row.dataset.pixiePrewarmBound = '1';
      var timer = null;
      row.addEventListener('mouseenter', function () {
        var toolId = row.getAttribute('data-tool-id');
        if (!toolId) return;
        var now = Date.now();
        if (prewarmThrottle[toolId] && now - prewarmThrottle[toolId] < 30000) return;
        timer = setTimeout(function () {
          prewarmThrottle[toolId] = Date.now();
          fetch('/api/tools/' + encodeURIComponent(toolId) + '/prewarm', {
            method: 'POST', credentials: 'same-origin',
          }).catch(function () { /* hover errors stay silent */ });
        }, 400);
      });
      row.addEventListener('mouseleave', function () {
        if (timer) { clearTimeout(timer); timer = null; }
      });
    });
  };

  /* ---- Workspace switcher (no-op wrapper for future enhancements) ---- */
  Pixie.workspaceSwitcher = function () {
    // Alpine handles the dropdown open/close declaratively in the
    // template. This hook exists so future enhancements (hotkey,
    // analytics) can attach without template churn.
  };

  /* ---- /tools grid Alpine state ---- */
  Pixie.toolsGridState = function () {
    return {
      selected: [],
      toggleSelect: function (toolId) {
        var idx = this.selected.indexOf(toolId);
        if (idx >= 0) this.selected.splice(idx, 1);
        else this.selected.push(toolId);
      },
      bulkClear: function () { this.selected = []; },
      bulkArchive: function () {
        var ids = this.selected.slice();
        var self = this;
        Promise.all(ids.map(function (id) {
          return fetch('/api/tools/' + encodeURIComponent(id) + '/archive', {
            method: 'POST', credentials: 'same-origin',
          });
        })).then(function () {
          self.selected = [];
          var filter = document.querySelector('.tools-grid__filters select');
          if (filter) filter.dispatchEvent(new Event('change'));
        });
      },
      bulkUnarchive: function () {
        var ids = this.selected.slice();
        var self = this;
        Promise.all(ids.map(function (id) {
          return fetch('/api/tools/' + encodeURIComponent(id) + '/unarchive', {
            method: 'POST', credentials: 'same-origin',
          });
        })).then(function () {
          self.selected = [];
          var filter = document.querySelector('.tools-grid__filters select');
          if (filter) filter.dispatchEvent(new Event('change'));
        });
      },
    };
  };

  function applyScaleFeatures() {
    Pixie.sidebarVirtualise();
    Pixie.hoverPrewarm();
    Pixie.workspaceSwitcher();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyScaleFeatures);
  } else {
    applyScaleFeatures();
  }
  if (Pixie.initOnSwap) {
    Pixie.initOnSwap(applyScaleFeatures);
  } else {
    document.body.addEventListener('htmx:afterSettle', applyScaleFeatures);
  }
})();
