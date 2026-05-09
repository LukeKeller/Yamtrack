// Renders the four collection-stats charts on the records list page.
// Reads JSON payloads embedded by the Django template and instantiates
// Chart.js charts. Skips any chart whose payload is missing or null.

document.addEventListener("DOMContentLoaded", function () {
  const readJson = (id) => {
    const node = document.getElementById(id);
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (e) {
      return null;
    }
  };

  const baseGrid = "rgba(75, 85, 99, 0.3)";
  const baseTick = "#9ca3af";

  const horizontalBar = (canvasId, payload) => {
    const ctx = document.getElementById(canvasId);
    if (!ctx || !payload || !payload.labels || !payload.labels.length) return;
    const ds = payload.datasets[0];
    new Chart(ctx, {
      type: "bar",
      data: {
        labels: payload.labels,
        datasets: [
          {
            label: ds.label,
            data: ds.data,
            backgroundColor: ds.background_color,
            borderRadius: 4,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            ticks: { color: baseTick, precision: 0 },
            grid: { color: baseGrid },
          },
          y: { ticks: { color: baseTick }, grid: { display: false } },
        },
      },
    });
  };

  const verticalBar = (canvasId, payload) => {
    const ctx = document.getElementById(canvasId);
    if (!ctx || !payload || !payload.labels || !payload.labels.length) return;
    const ds = payload.datasets[0];
    new Chart(ctx, {
      type: "bar",
      data: {
        labels: payload.labels,
        datasets: [
          {
            label: ds.label,
            data: ds.data,
            backgroundColor: ds.background_color,
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: baseTick }, grid: { display: false } },
          y: {
            ticks: { color: baseTick, precision: 0 },
            grid: { color: baseGrid },
          },
        },
      },
    });
  };

  const donut = (canvasId, payload) => {
    const ctx = document.getElementById(canvasId);
    if (!ctx || !payload || !payload.labels || !payload.labels.length) return;
    new Chart(ctx, {
      type: "doughnut",
      data: payload,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "60%",
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: baseTick, padding: 12 },
          },
        },
      },
    });
  };

  donut("recordOwnedVsWantChart", readJson("record_owned_vs_want_data"));
  verticalBar("recordByDecadeChart", readJson("record_by_decade_data"));
  horizontalBar("recordTopArtistsChart", readJson("record_top_artists_data"));
  horizontalBar("recordTopLabelsChart", readJson("record_top_labels_data"));
});
