// Renders the per-book KOReader reading-history chart: percentage over
// time, one dataset per device so each gets its own colour and legend
// entry. Data is embedded by the koreader_book_history view; x values
// are epoch ms (so Chart.js can run on the linear axis without needing
// a date-adapter library shipped alongside chartjs-4.4.9).

document.addEventListener("DOMContentLoaded", function () {
  const node = document.getElementById("koreader-history-data");
  if (!node) return;

  let datasets;
  try {
    datasets = JSON.parse(node.textContent);
  } catch (err) {
    console.error("koreader-history: malformed dataset payload", err);
    return;
  }
  if (!Array.isArray(datasets) || datasets.length === 0) return;

  const canvas = document.getElementById("koreader-history-chart");
  if (!canvas) return;

  // Tailwind 500-shade hues; readable on the dark surface. Order matters:
  // the Nth device gets palette[N % len].
  const palette = [
    "#6366f1", // indigo
    "#22c55e", // green
    "#f59e0b", // amber
    "#ec4899", // pink
    "#06b6d4", // cyan
    "#a855f7", // purple
    "#ef4444", // red
    "#84cc16", // lime
  ];

  const chartDatasets = datasets.map((d, i) => {
    const color = palette[i % palette.length];
    return {
      label: d.label,
      data: d.points.map((p) => ({ x: p.x, y: p.y, page: p.page })),
      borderColor: color,
      backgroundColor: color,
      pointRadius: 3,
      pointHoverRadius: 5,
      borderWidth: 2,
      tension: 0.15,
      showLine: true, // connect a device's points chronologically
    };
  });

  const allX = chartDatasets.flatMap((d) => d.data.map((p) => p.x));
  const minX = Math.min.apply(null, allX);
  const maxX = Math.max.apply(null, allX);

  // Format epoch ms → human-friendly tick label. Width-aware: if the
  // span is < 36h, show "May 26 14:00"; otherwise show "May 26".
  const span = maxX - minX;
  const dense = span < 36 * 60 * 60 * 1000;
  const fmtTick = (ms) => {
    const d = new Date(ms);
    const date = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    if (!dense) return date;
    const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    return `${date} ${time}`;
  };
  const fmtTooltipTitle = (items) => {
    const ms = items[0].parsed.x;
    const d = new Date(ms);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  new Chart(canvas, {
    type: "scatter",
    data: { datasets: chartDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false, // x is a number, y is a number
      scales: {
        x: {
          type: "linear",
          min: minX,
          max: maxX,
          ticks: {
            color: "#9ca3af",
            maxRotation: 0,
            autoSkipPadding: 20,
            callback: fmtTick,
          },
          grid: { color: "rgba(148,163,184,0.12)" },
        },
        y: {
          min: 0,
          max: 100,
          ticks: {
            color: "#9ca3af",
            callback: (v) => v + "%",
          },
          grid: { color: "rgba(148,163,184,0.12)" },
        },
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: "#d1d5db", usePointStyle: true },
        },
        tooltip: {
          callbacks: {
            title: fmtTooltipTitle,
            label: (ctx) => {
              const p = ctx.raw;
              const pct = p.y.toFixed(1) + "%";
              const page = p.page ? ` · page ${p.page}` : "";
              return `${ctx.dataset.label}: ${pct}${page}`;
            },
          },
        },
      },
    },
  });
});
