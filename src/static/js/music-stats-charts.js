(function () {
  "use strict";

  function readJSON(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  var INDIGO = "#6366f1";
  var GRID = "rgba(255,255,255,0.05)";
  var TICK = "#9ca3af";

  function makeChart(canvasId, jsonId, type) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") return;
    var payload = readJSON(jsonId);
    var wrap = canvas.closest("[data-chart-wrap]");
    if (!payload || !payload.labels || !payload.labels.length) {
      if (wrap) wrap.classList.add("hidden");
      return;
    }
    var isLine = type === "line";
    new Chart(canvas, {
      type: type,
      data: {
        labels: payload.labels,
        datasets: [
          {
            label: "Plays",
            data: payload.data,
            backgroundColor: isLine ? "rgba(99,102,241,0.18)" : INDIGO,
            borderColor: INDIGO,
            borderWidth: 2,
            tension: 0.3,
            fill: isLine,
            pointRadius: isLine ? 2 : 0,
            borderRadius: isLine ? 0 : 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            ticks: { color: TICK, maxRotation: 0, autoSkip: true },
            grid: { color: GRID },
          },
          y: {
            beginAtZero: true,
            ticks: { color: TICK, precision: 0 },
            grid: { color: GRID },
          },
        },
      },
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    makeChart("chart-by-month", "music-by-month", "line");
    makeChart("chart-by-hour", "music-by-hour", "bar");
    makeChart("chart-by-weekday", "music-by-weekday", "bar");
    makeChart("chart-discoveries", "music-discoveries", "line");
  });
})();
