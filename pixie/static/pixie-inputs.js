/* Pixie — input renderers.
 * Per-input JS helpers: CodeMirror editor inits for json/code,
 * Leaflet map binders for map_*, file/image/audio Alpine factories,
 * autocomplete factory, byte formatter, and a markdown render-string
 * helper used by the markdown input partial preview pane.
 *
 * Booted via Pixie.initOnSwap so every htmx swap re-initialises new
 * inputs without leaking old listeners.
 */
(function () {
  "use strict";

  if (!window.Pixie) window.Pixie = {};
  var Pixie = window.Pixie;

  // -------------------------------------------------------------------------
  // Tiny helpers
  // -------------------------------------------------------------------------

  Pixie.fmtBytes = function (n) {
    if (n == null || isNaN(n)) return "";
    var units = ["B", "KB", "MB", "GB"];
    var i = 0; var v = Number(n);
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + " " + units[i];
  };

  Pixie.escapeHtml = function (s) {
    return String(s == null ? "" : s).replace(/[<>&"]/g, function (c) {
      return ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" })[c];
    });
  };

  // A tiny markdown render used by the markdown input's preview pane.
  // Intentionally minimal — headings, paragraphs, bold, italic, code,
  // inline code, links, lists. Anything fancier and the user should set
  // up a proper viewer in the tool's output.
  Pixie.renderMarkdownString = function (src) {
    if (!src) return "";
    var html = Pixie.escapeHtml(src);
    // Fenced code
    html = html.replace(/```([\s\S]*?)```/g, function (_, code) {
      return '<pre class="md-code"><code>' + code + "</code></pre>";
    });
    // Headings
    html = html.replace(/^###### (.*)$/gm, "<h6>$1</h6>")
               .replace(/^##### (.*)$/gm, "<h5>$1</h5>")
               .replace(/^#### (.*)$/gm, "<h4>$1</h4>")
               .replace(/^### (.*)$/gm, "<h3>$1</h3>")
               .replace(/^## (.*)$/gm, "<h2>$1</h2>")
               .replace(/^# (.*)$/gm, "<h1>$1</h1>");
    // Bold + italic + inline code
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
               .replace(/\*([^*]+)\*/g, "<em>$1</em>")
               .replace(/`([^`]+)`/g, "<code>$1</code>");
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" rel="noopener">$1</a>');
    // Unordered lists
    html = html.replace(/(^|\n)(-\s.+(?:\n-\s.+)*)/g, function (_, lead, block) {
      var items = block.split(/\n/).map(function (l) {
        return "<li>" + l.replace(/^-\s+/, "") + "</li>";
      }).join("");
      return lead + "<ul>" + items + "</ul>";
    });
    // Paragraphs (anything not already wrapped)
    html = html.split(/\n{2,}/).map(function (p) {
      if (/^<(h\d|ul|pre|ol|blockquote)/.test(p.trim())) return p;
      return "<p>" + p.replace(/\n/g, "<br>") + "</p>";
    }).join("\n");
    return html;
  };

  // -------------------------------------------------------------------------
  // CodeMirror editable init for code & json input partials
  // -------------------------------------------------------------------------

  var INPUT_MODE_MAP = {
    python: "python", py: "python",
    sql: "text/x-sql",
    javascript: "javascript", js: "javascript",
    typescript: "javascript", ts: "javascript",
    json: { name: "javascript", json: true },
    html: "htmlmixed", xml: "xml",
    plain: "text/plain", text: "text/plain"
  };

  Pixie.initInputCodeEditors = function (root) {
    var nodes = (root || document).querySelectorAll(
      "textarea[data-pixie-code]:not([data-cm-init])"
    );
    if (!nodes.length) return;
    if (typeof CodeMirror === "undefined") {
      // CDN still loading — try again on next tick.
      setTimeout(function () { Pixie.initInputCodeEditors(root); }, 200);
      return;
    }
    var dark = document.documentElement.getAttribute("data-theme") === "dark";
    nodes.forEach(function (ta) {
      ta.dataset.cmInit = "1";
      var lang = ta.dataset.language || "plain";
      var editor = CodeMirror.fromTextArea(ta, {
        mode: INPUT_MODE_MAP[lang] || "text/plain",
        theme: dark ? "material-darker" : "neo",
        lineNumbers: true,
        indentUnit: 2,
        tabSize: 2,
        lineWrapping: false,
        viewportMargin: Infinity
      });
      // CodeMirror writes to the textarea on form serialise, but htmx
      // collects values from the DOM at hx-trigger time, so we sync
      // explicitly via the configRequest hook on the parent form.
      var form = ta.form || ta.closest("form");
      if (form) {
        form.addEventListener("htmx:configRequest", function () { editor.save(); });
      }
      // JSON validation band — partial owns the .json-editor__err slot.
      if (ta.dataset.pixieJson != null) {
        editor.on("change", function () {
          var raw = editor.getValue().trim();
          var holder = ta.closest(".json-editor");
          var alpine = holder && holder.__x;
          try {
            if (raw) JSON.parse(raw);
            ta.setAttribute("aria-invalid", "false");
            if (alpine) alpine.$data.err = null;
            var hidden = holder && holder.querySelector("input[type=hidden]");
            if (hidden) hidden.value = raw;
          } catch (e) {
            ta.setAttribute("aria-invalid", "true");
            if (alpine) alpine.$data.err = e.message;
          }
        });
      }
    });
  };

  document.addEventListener("pixie:theme-changed", function () {
    var dark = document.documentElement.getAttribute("data-theme") === "dark";
    document.querySelectorAll("textarea[data-pixie-code]").forEach(function (ta) {
      var cm = ta.nextSibling;
      while (cm && (!cm.classList || !cm.classList.contains("CodeMirror"))) cm = cm.nextSibling;
      if (cm && cm.CodeMirror) cm.CodeMirror.setOption("theme", dark ? "material-darker" : "neo");
    });
  });

  // -------------------------------------------------------------------------
  // File / image / audio Alpine factories
  // -------------------------------------------------------------------------

  Pixie.fileDrop = function () {
    return {
      dragover: false,
      files: [],
      onChange: function (e) {
        var added = Array.from(e.target.files || []);
        this.files = this.files.concat(added);
      },
      onDrop: function (e) {
        this.dragover = false;
        var dropped = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
        if (!dropped.length) return;
        var inputEl = this.$el.querySelector("input[type=file]");
        if (inputEl) {
          var dt = new DataTransfer();
          this.files.concat(dropped).forEach(function (f) { dt.items.add(f); });
          inputEl.files = dt.files;
        }
        this.files = this.files.concat(dropped);
      },
      remove: function (i) {
        this.files.splice(i, 1);
        var inputEl = this.$el.querySelector("input[type=file]");
        if (inputEl) {
          var dt = new DataTransfer();
          this.files.forEach(function (f) { dt.items.add(f); });
          inputEl.files = dt.files;
        }
      }
    };
  };

  Pixie.imageInput = function () {
    return {
      dragover: false,
      files: [],
      _attach: function (added) {
        var self = this;
        added.forEach(function (file) {
          var preview = URL.createObjectURL(file);
          var entry = { name: file.name, size: file.size, preview: preview, dim: "" };
          var img = new Image();
          img.onload = function () { entry.dim = img.naturalWidth + "×" + img.naturalHeight; };
          img.src = preview;
          self.files.push(entry);
        });
      },
      _sync: function () {
        var inputEl = this.$el.querySelector("input[type=file]");
        if (!inputEl) return;
        var dt = new DataTransfer();
        // Best-effort sync from the entry objects' original files. We track
        // the DataTransfer separately on first attach so removals work.
        if (this._dt && this._dt.items) {
          for (var i = 0; i < this.files.length; i++) {
            if (this._files && this._files[i]) dt.items.add(this._files[i]);
          }
        }
        inputEl.files = dt.files;
      },
      onChange: function (e) {
        var added = Array.from(e.target.files || []);
        this._files = (this._files || []).concat(added);
        this._attach(added);
        this._sync();
      },
      onDrop: function (e) {
        this.dragover = false;
        var dropped = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
        if (!dropped.length) return;
        this._files = (this._files || []).concat(dropped);
        this._attach(dropped);
        this._sync();
      },
      remove: function (i) {
        var entry = this.files[i];
        if (entry && entry.preview) URL.revokeObjectURL(entry.preview);
        this.files.splice(i, 1);
        if (this._files) this._files.splice(i, 1);
        this._sync();
      }
    };
  };

  Pixie.audioInput = function () {
    return {
      dragover: false,
      file: null,
      audio: null,
      playing: false,
      durationText: "",
      progress: 0,
      bars: (function () {
        var arr = [];
        for (var i = 0; i < 70; i++) {
          arr.push(4 + Math.abs(Math.sin(i * 0.7) * 10 + Math.sin(i * 0.31) * 8) + (i % 7 === 0 ? 4 : 0));
        }
        return arr;
      })(),
      _attach: function (file) {
        this.file = file;
        var url = URL.createObjectURL(file);
        if (this.audio) { this.audio.pause(); URL.revokeObjectURL(this.audio.src); }
        this.audio = new Audio(url);
        var self = this;
        this.audio.addEventListener("loadedmetadata", function () {
          var d = self.audio.duration;
          if (isFinite(d)) {
            var m = Math.floor(d / 60), s = Math.round(d % 60);
            self.durationText = m + ":" + String(s).padStart(2, "0");
          }
        });
        this.audio.addEventListener("timeupdate", function () {
          if (self.audio.duration > 0) {
            self.progress = self.audio.currentTime / self.audio.duration;
          }
        });
        this.audio.addEventListener("ended", function () { self.playing = false; self.progress = 0; });
      },
      onChange: function (e) {
        var f = (e.target.files || [])[0];
        if (f) this._attach(f);
      },
      onDrop: function (e) {
        this.dragover = false;
        var f = (e.dataTransfer && e.dataTransfer.files || [])[0];
        if (f) {
          this._attach(f);
          var inputEl = this.$el.querySelector("input[type=file]");
          if (inputEl) {
            var dt = new DataTransfer();
            dt.items.add(f);
            inputEl.files = dt.files;
          }
        }
      },
      togglePlay: function () {
        if (!this.audio) return;
        if (this.playing) { this.audio.pause(); this.playing = false; }
        else { this.audio.play(); this.playing = true; }
      },
      reset: function () {
        if (this.audio) { this.audio.pause(); URL.revokeObjectURL(this.audio.src); }
        this.audio = null; this.file = null; this.playing = false;
        this.progress = 0; this.durationText = "";
        var inputEl = this.$el.querySelector("input[type=file]");
        if (inputEl) inputEl.value = "";
      }
    };
  };

  // -------------------------------------------------------------------------
  // Autocomplete — proxied to /tool/<id>/autocomplete/<endpoint>?q=…
  // The page's tool id lives on the form via data-pixie-tool="<id>".
  // -------------------------------------------------------------------------

  Pixie.autocomplete = function (opts) {
    opts = opts || {};
    return {
      query: "",
      results: [],
      open: false,
      loading: false,
      cursor: -1,
      _toolId: function () {
        var form = this.$el.closest("form[data-pixie-tool]");
        return form ? form.getAttribute("data-pixie-tool") : null;
      },
      fetch: function () {
        var self = this;
        var toolId = this._toolId();
        if (!toolId || !this.query) { this.results = []; return; }
        this.loading = true;
        var url = "/tool/" + encodeURIComponent(toolId) +
                  "/autocomplete/" + encodeURIComponent(opts.endpoint) +
                  "?q=" + encodeURIComponent(this.query);
        fetch(url, { headers: { "Accept": "application/json" } })
          .then(function (r) { return r.ok ? r.json() : { results: [] }; })
          .then(function (json) {
            self.results = Array.isArray(json) ? json
                          : Array.isArray(json.results) ? json.results : [];
            self.cursor = self.results.length ? 0 : -1;
            self.loading = false;
            self.open = true;
          })
          .catch(function () { self.results = []; self.loading = false; });
      },
      next: function () { if (this.cursor < this.results.length - 1) this.cursor++; },
      prev: function () { if (this.cursor > 0) this.cursor--; },
      pick: function (r) {
        this.query = r.label || r.value || String(r);
        this.open = false;
      },
      commit: function () {
        if (this.cursor >= 0 && this.results[this.cursor]) this.pick(this.results[this.cursor]);
        else this.open = false;
      }
    };
  };

  // -------------------------------------------------------------------------
  // Leaflet map inputs (point / bbox / polygon / multipoint)
  // -------------------------------------------------------------------------

  function syncMapValue(canvas, value) {
    var hidden = canvas.parentElement.querySelector("input[type=hidden]");
    if (hidden) hidden.value = JSON.stringify(value);
  }

  function ensureLeaflet(retry) {
    if (typeof L !== "undefined") return true;
    if (retry > 40) return false;
    setTimeout(function () { Pixie.initMapInputs(document); }, 150);
    return false;
  }

  Pixie.initMapInputs = function (root) {
    var canvases = (root || document).querySelectorAll(
      "[data-pixie-map]:not([data-map-init])"
    );
    if (!canvases.length) return;
    if (!ensureLeaflet(0)) return;

    canvases.forEach(function (canvas) {
      canvas.dataset.mapInit = "1";
      var mode = canvas.getAttribute("data-pixie-map");
      var center = JSON.parse(canvas.getAttribute("data-center") || "[51.505,-0.09]");
      var zoom = parseInt(canvas.getAttribute("data-zoom") || "6", 10);

      var map = L.map(canvas, { zoomControl: true, scrollWheelZoom: true });
      map.setView(center, zoom);
      if (Pixie.addBaseTiles) Pixie.addBaseTiles(map);
      else L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap, © CartoDB",
        subdomains: "abcd", maxZoom: 19
      }).addTo(map);

      // Resize map once visible (htmx swaps insert into hidden containers).
      setTimeout(function () { map.invalidateSize(); }, 60);

      var initial = canvas.getAttribute("data-initial");
      if (initial) try { initial = JSON.parse(initial); } catch (e) { initial = null; }

      if (mode === "point") {
        var marker = null;
        function setPoint(latlng) {
          if (!marker) marker = L.marker(latlng, { draggable: true }).addTo(map)
            .on("dragend", function (ev) { setPoint(ev.target.getLatLng()); });
          else marker.setLatLng(latlng);
          syncMapValue(canvas, [latlng.lat, latlng.lng]);
        }
        map.on("click", function (e) { setPoint(e.latlng); });
        if (initial && initial.length === 2) setPoint(L.latLng(initial[0], initial[1]));
      }
      else if (mode === "bbox") {
        var rect = null, start = null;
        map.on("mousedown", function (e) {
          if (!e.originalEvent.shiftKey) return;
          map.dragging.disable();
          start = e.latlng;
          if (rect) { map.removeLayer(rect); rect = null; }
        });
        map.on("mousemove", function (e) {
          if (!start) return;
          if (rect) map.removeLayer(rect);
          rect = L.rectangle([start, e.latlng], {
            color: "var(--accent, #5b6cd1)", weight: 2, fillOpacity: 0.12
          }).addTo(map);
        });
        map.on("mouseup", function (e) {
          if (!start) return;
          map.dragging.enable();
          var b = L.latLngBounds(start, e.latlng);
          syncMapValue(canvas, [[b.getSouth(), b.getWest()], [b.getNorth(), b.getEast()]]);
          start = null;
        });
        if (initial && initial.length === 2) {
          rect = L.rectangle(initial, { color: "var(--accent, #5b6cd1)", weight: 2, fillOpacity: 0.12 }).addTo(map);
          map.fitBounds(initial);
        }
      }
      else if (mode === "polygon") {
        var pts = [], poly = null, preview = null;
        function drawPreview() {
          if (preview) map.removeLayer(preview);
          if (pts.length > 0) {
            preview = L.polyline(pts, { color: "var(--accent, #5b6cd1)", dashArray: "4,4" }).addTo(map);
          }
        }
        map.on("click", function (e) {
          pts.push([e.latlng.lat, e.latlng.lng]);
          drawPreview();
        });
        map.on("dblclick", function () {
          if (pts.length < 3) return;
          if (preview) map.removeLayer(preview);
          if (poly) map.removeLayer(poly);
          poly = L.polygon(pts.slice(), {
            color: "var(--accent, #5b6cd1)", weight: 2, fillOpacity: 0.16
          }).addTo(map);
          syncMapValue(canvas, pts.slice());
          pts = []; preview = null;
        });
        map.doubleClickZoom.disable();
        if (initial && initial.length >= 3) {
          poly = L.polygon(initial, { color: "var(--accent, #5b6cd1)", weight: 2, fillOpacity: 0.16 }).addTo(map);
          map.fitBounds(poly.getBounds());
        }
      }
      else if (mode === "multipoint") {
        var allPts = [];
        function commit() { syncMapValue(canvas, allPts.slice()); }
        function add(latlng) {
          var idx = allPts.push([latlng.lat, latlng.lng]) - 1;
          L.marker(latlng, { draggable: true })
            .on("dragend", function (ev) {
              var ll = ev.target.getLatLng();
              allPts[idx] = [ll.lat, ll.lng]; commit();
            })
            .on("contextmenu", function (ev) {
              map.removeLayer(ev.target);
              allPts.splice(idx, 1); commit();
            })
            .addTo(map);
          commit();
        }
        map.on("click", function (e) { add(e.latlng); });
        if (Array.isArray(initial)) initial.forEach(function (p) { add(L.latLng(p[0], p[1])); });
      }
    });
  };

  // -------------------------------------------------------------------------
  // Boot — register every initialiser via the swap hook.
  // -------------------------------------------------------------------------

  if (typeof Pixie.initOnSwap === "function") {
    Pixie.initOnSwap(function (root) {
      try { Pixie.initInputCodeEditors(root); } catch (e) { console.warn(e); }
      try { Pixie.initMapInputs(root); } catch (e) { console.warn(e); }
    });
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      Pixie.initInputCodeEditors(document);
      Pixie.initMapInputs(document);
    });
  }

})();
