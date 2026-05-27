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

(function () {
  function render() {
    const node = document.getElementById("koreader-history-data");
    if (!node) {
      console.warn("koreader-history: data node missing");
      return;
    }

    let sessions;
    try {
      sessions = JSON.parse(node.textContent || "[]");
    } catch (err) {
      console.error("koreader-history: malformed dataset payload", err);
      return;
    }
    if (!Array.isArray(sessions)) {
      console.warn("koreader-history: payload is not an array", sessions);
      return;
    }
    console.log("koreader-history: rendering chart with", sessions.length, "session(s)");

    const canvas = document.getElementById("koreader-history-chart");
    if (!canvas) {
      console.warn("koreader-history: canvas missing");
      return;
    }
    if (typeof Chart === "undefined") {
      console.error("koreader-history: Chart.js not loaded");
      return;
    }

    if (sessions.length === 0) {
      // Nothing to plot, but keep the canvas empty rather than throwing.
      // The template's empty-state branch is gated on event_count, not
      // session_count, so a book with events but no sessions still
      // reaches here.
      return;
    }

    const labels = sessions.map((s) => s.label || "");
    const baseData = sessions.map((s) => Number(s.start_pct) || 0);
    const deltaData = sessions.map((s) =>
      Math.max(0, Number(s.delta_pct) || 0),
    );

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
            backgroundColor: "rgba(249,115,22,0.35)",
            stack: "journey",
            borderWidth: 0,
          },
          {
            label: "This session",
            data: deltaData,
            backgroundColor: "#f97316",
            stack: "journey",
            borderWidth: 0,
            borderRadius: 4,
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
                return s && s.started ? fmtDate(s.started) : "";
              },
              label: (ctx) => {
                const s = sessions[ctx.dataIndex];
                if (!s) return "";
                if (ctx.datasetIndex === 1) {
                  return `Read this session: +${(s.delta_pct || 0).toFixed(1)}% (${fmtDuration(s.duration_min)})`;
                }
                return `Reached: ${(s.end_pct || 0).toFixed(1)}% (from ${(s.start_pct || 0).toFixed(1)}%)`;
              },
            },
          },
        },
      },
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }
})();
