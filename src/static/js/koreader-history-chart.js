// Renders the per-book "Book Journey" chart: one bar per reading
// session (clustered server-side from kosync events on a 30-min idle
// gap), stacked into a "start %" base and a "delta %" tip so the tip
// reads as the gain the user made in that session and the full bar
// height reads as the cumulative % reached at the end of it.
//
// X axis is categorical (one slot per session, evenly spaced). The
// label is the session start date — long real-world gaps between
// sessions are surfaced via the date labels rather than wide visual
// gaps so the bars stay readable on a phone-width canvas. Tooltip
// shows the full date, duration, and start→end percentages.

document.addEventListener("DOMContentLoaded", function () {
  const node = document.getElementById("koreader-history-data");
  if (!node) return;

  let sessions;
  try {
    sessions = JSON.parse(node.textContent);
  } catch (err) {
    console.error("koreader-history: malformed dataset payload", err);
    return;
  }
  if (!Array.isArray(sessions) || sessions.length === 0) return;

  const canvas = document.getElementById("koreader-history-chart");
  if (!canvas) return;

  const labels = sessions.map((s) => s.label);
  const baseData = sessions.map((s) => s.start_pct);
  const deltaData = sessions.map((s) => s.delta_pct);

  const fmtDate = (iso) => {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const fmtDuration = (mins) => {
    if (!mins) return "< 1 min";
    if (mins < 60) return `${mins} min`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return m ? `${h}h ${m}m` : `${h}h`;
  };

  new Chart(canvas, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Already read",
          data: baseData,
          backgroundColor: "rgba(249,115,22,0.35)", // muted orange (base)
          borderColor: "rgba(249,115,22,0.35)",
          stack: "journey",
          borderRadius: { topLeft: 0, topRight: 0, bottomLeft: 4, bottomRight: 4 },
          borderSkipped: false,
        },
        {
          label: "This session",
          data: deltaData,
          backgroundColor: "#f97316", // vivid orange (delta tip)
          borderColor: "#f97316",
          stack: "journey",
          borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
          borderSkipped: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          stacked: true,
          ticks: { color: "#9ca3af", maxRotation: 0, autoSkipPadding: 12 },
          grid: { display: false },
        },
        y: {
          stacked: true,
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
            title: (items) => {
              const s = sessions[items[0].dataIndex];
              return fmtDate(s.started);
            },
            label: (ctx) => {
              const s = sessions[ctx.dataIndex];
              if (ctx.datasetIndex === 1) {
                return `Read this session: +${s.delta_pct.toFixed(1)}% (${fmtDuration(s.duration_min)})`;
              }
              return `Reached: ${s.end_pct.toFixed(1)}% (from ${s.start_pct.toFixed(1)}%)`;
            },
          },
        },
      },
    },
  });
});
