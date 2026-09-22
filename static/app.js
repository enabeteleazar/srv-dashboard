/* srv dashboard — comportements de l'interface.
   Sans dépendance : <dialog> natif, SVG dessiné à la main, fetch pour le
   rafraîchissement automatique. */

(function () {
  "use strict";

  /* --- thème ------------------------------------------------------------ */

  function currentTheme() {
    var stamped = document.documentElement.getAttribute("data-theme");
    if (stamped) return stamped;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try {
        localStorage.setItem("srv-theme", next);
      } catch (e) {
        /* stockage indisponible : le thème vaut pour cette page seulement */
      }
      drawCharts();
    });
  });

  /* --- modal ------------------------------------------------------------ */

  document.querySelectorAll("[data-open-dialog]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var dialog = document.getElementById(btn.getAttribute("data-open-dialog"));
      if (dialog && typeof dialog.showModal === "function") dialog.showModal();
    });
  });

  document.querySelectorAll("dialog").forEach(function (dialog) {
    dialog.querySelectorAll("[data-close-dialog]").forEach(function (el) {
      el.addEventListener("click", function () {
        dialog.close();
      });
    });
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });
  });

  /* --- confirmation avant une action sensible (deploy-prod) ------------- */

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
    });
  });

  /* --- lignes de tableau cliquables ------------------------------------- */

  document.querySelectorAll("tr[data-href]").forEach(function (row) {
    row.addEventListener("click", function (event) {
      if (event.target.closest("a, button, select, input, form")) return;
      window.location.href = row.getAttribute("data-href");
    });
  });

  /* --- filtres de la liste de projets ----------------------------------- */

  var search = document.querySelector("[data-filter-search]");
  var rootSelect = document.querySelector("[data-filter-root]");
  var statusChips = document.querySelectorAll("[data-filter-status]");
  var rows = document.querySelectorAll("tr[data-row]");
  var noMatch = document.getElementById("no-match");
  var activeStatus = "";

  function applyFilters() {
    var term = search ? search.value.trim().toLowerCase() : "";
    var root = rootSelect ? rootSelect.value : "";
    var visible = 0;
    rows.forEach(function (row) {
      var ok =
        (!term || row.getAttribute("data-name").indexOf(term) !== -1) &&
        (!activeStatus || row.getAttribute("data-status") === activeStatus) &&
        (!root || row.getAttribute("data-root") === root);
      row.hidden = !ok;
      if (ok) visible++;
    });
    if (noMatch) noMatch.hidden = visible !== 0 || rows.length === 0;
  }

  if (search) search.addEventListener("input", applyFilters);
  if (rootSelect) rootSelect.addEventListener("change", applyFilters);
  statusChips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      statusChips.forEach(function (c) {
        c.classList.remove("is-active");
      });
      chip.classList.add("is-active");
      activeStatus = chip.getAttribute("data-filter-status");
      applyFilters();
    });
  });

  /* --- graphique d'activité (colonnes empilées) ------------------------- */

  var tooltip = document.getElementById("chart-tooltip");

  function hideTooltip() {
    if (tooltip) tooltip.hidden = true;
  }

  function showTooltip(event, day) {
    if (!tooltip) return;
    var date = new Date(day.date + "T00:00:00");
    tooltip.innerHTML =
      "<strong>" +
      date.toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "short" }) +
      "</strong>" +
      '<div class="row"><span>Réussies</span><span>' + day.ok + "</span></div>" +
      '<div class="row"><span>Échecs</span><span>' + day.error + "</span></div>";
    tooltip.hidden = false;
    var box = tooltip.getBoundingClientRect();
    var x = Math.min(event.clientX + 14, window.innerWidth - box.width - 8);
    var y = Math.max(event.clientY - box.height - 12, 8);
    tooltip.style.left = x + "px";
    tooltip.style.top = y + "px";
  }

  // Maximum "rond" ET pair, pour que la graduation du milieu tombe sur un
  // entier (0 / 3 / 6 plutôt que 0 / 2,5 / 5).
  function niceMax(value) {
    if (value <= 4) return 4;
    if (value <= 10) return value % 2 === 0 ? value : value + 1;
    var step = Math.pow(10, Math.floor(Math.log10(value))) / 2;
    var max = Math.ceil(value / step) * step;
    return max % 2 === 0 ? max : max + step;
  }

  // Colonne : coins hauts arrondis (4px) seulement pour le segment du dessus,
  // pied carré sur la ligne de base.
  function columnPath(x, y, w, h, roundTop) {
    if (h <= 0) return "";
    var r = roundTop ? Math.min(4, w / 2, h) : 0;
    return (
      "M" + x + " " + (y + h) +
      " L" + x + " " + (y + r) +
      (r ? " Q" + x + " " + y + " " + (x + r) + " " + y : "") +
      " L" + (x + w - r) + " " + y +
      (r ? " Q" + (x + w) + " " + y + " " + (x + w) + " " + (y + r) : "") +
      " L" + (x + w) + " " + (y + h) + " Z"
    );
  }

  function drawChart(container) {
    var dataEl = document.getElementById("activity-data");
    if (!dataEl) return;
    var days;
    try {
      days = JSON.parse(dataEl.textContent);
    } catch (e) {
      return;
    }
    container.innerHTML = "";

    var total = days.reduce(function (sum, d) {
      return sum + d.ok + d.error;
    }, 0);
    if (!total) {
      var empty = document.createElement("p");
      empty.className = "chart-empty";
      empty.textContent = "Aucune action enregistrée sur les 14 derniers jours.";
      container.appendChild(empty);
      return;
    }

    var W = container.clientWidth || 640;
    var H = container.clientHeight || 190;
    var padL = 28, padR = 6, padT = 8, padB = 20;
    var plotW = Math.max(40, W - padL - padR);
    var plotH = Math.max(40, H - padT - padB);
    var max = niceMax(Math.max.apply(null, days.map(function (d) { return d.ok + d.error; })));
    var band = plotW / days.length;
    var barW = Math.min(24, band * 0.55);
    var GAP = 2; // l'espace en couleur de surface qui sépare les deux segments

    var svgNS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Actions par jour sur 14 jours : " + total + " au total");

    function add(tag, attrs, parent) {
      var el = document.createElementNS(svgNS, tag);
      Object.keys(attrs).forEach(function (k) {
        el.setAttribute(k, attrs[k]);
      });
      (parent || svg).appendChild(el);
      return el;
    }

    // grille + graduations (toujours des entiers : max est pair)
    [0, max / 2, max].forEach(function (t) {
      var y = padT + plotH - (t / max) * plotH;
      add("line", { class: t === 0 ? "axis-line" : "grid-line", x1: padL, y1: y, x2: W - padR, y2: y });
      var label = add("text", { class: "tick", x: padL - 8, y: y + 3.5, "text-anchor": "end" });
      label.textContent = String(Math.round(t));
    });

    // Étiquettes de dates : une tous les N jours (N dépend de la largeur
    // disponible), plus la dernière si elle ne colle pas à la précédente.
    var every = band < 34 ? 4 : 3;
    var labelledDays = [];
    for (var k = 0; k < days.length; k += every) labelledDays.push(k);
    var lastIndex = days.length - 1;
    if (labelledDays[labelledDays.length - 1] !== lastIndex &&
        lastIndex - labelledDays[labelledDays.length - 1] >= 2) {
      labelledDays.push(lastIndex);
    }

    days.forEach(function (day, i) {
      var x = padL + i * band + (band - barW) / 2;
      var okH = (day.ok / max) * plotH;
      var errH = (day.error / max) * plotH;
      var baseY = padT + plotH;
      var group = add("g", { class: "band" });

      if (okH > 0) {
        add("path", { class: "bar-ok", d: columnPath(x, baseY - okH, barW, okH, day.error === 0) }, group);
      }
      if (errH > 0) {
        var errBottom = baseY - okH - (okH > 0 ? GAP : 0);
        add("path", { class: "bar-err", d: columnPath(x, errBottom - errH, barW, errH, true) }, group);
      }

      var hit = add("rect", { class: "hit", x: padL + i * band, y: padT, width: band, height: plotH }, group);
      hit.addEventListener("mousemove", function (event) { showTooltip(event, day); });
      hit.addEventListener("mouseleave", hideTooltip);

      if (labelledDays.indexOf(i) !== -1) {
        var parts = day.date.split("-");
        var tick = add("text", {
          class: "tick", x: padL + i * band + band / 2, y: H - 5, "text-anchor": "middle",
        });
        tick.textContent = parts[2] + "/" + parts[1];
      }
    });

    container.appendChild(svg);
  }

  function drawCharts() {
    document.querySelectorAll("[data-chart='activity']").forEach(drawChart);
  }

  drawCharts();
  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawCharts, 150);
  });

  /* --- rafraîchissement pendant les actions ----------------------------- */

  var main = document.querySelector("[data-poll]");
  if (main && typeof fetch === "function") {
    var endpoint = main.getAttribute("data-poll");
    var seen = null;

    setInterval(function () {
      if (document.hidden) return;
      fetch(endpoint, { headers: { Accept: "application/json" } })
        .then(function (res) { return res.ok ? res.json() : null; })
        .then(function (state) {
          if (!state) return;
          if (seen === null) {
            seen = state.count;
            return;
          }
          // une action vient de se terminer (ou de démarrer ailleurs) :
          // on recharge pour afficher le résultat à jour.
          if (state.count !== seen) {
            seen = state.count;
            window.location.reload();
          }
        })
        .catch(function () { /* dashboard momentanément injoignable : on réessaiera */ });
    }, 4000);
  }
})();
