(function () {
  'use strict';

  function formatWeek(week) {
    var d = new Date(week * 1000);
    var pad = function (n) { return String(n).padStart(2, '0'); };
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate());
  }

  function renderChart() {
    var canvas = document.getElementById('activity-chart');
    var dataEl = document.getElementById('activity-data');
    if (!canvas || !dataEl || typeof Chart === 'undefined') return;
    if (canvas.chart) canvas.chart.destroy();
    var weeks = JSON.parse(dataEl.textContent);
    canvas.chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: weeks.map(function (w) { return formatWeek(w.week); }),
        datasets: [{
          label: 'Commits',
          data: weeks.map(function (w) { return w.total; }),
          borderColor: '#2563eb',
          backgroundColor: 'rgba(37, 99, 235, 0.15)',
          fill: true,
          tension: 0.3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { maxTicksLimit: 12, color: '#64748b', font: { size: 11 } },
          },
          y: {
            beginAtZero: true,
            ticks: { precision: 0, color: '#64748b', font: { size: 11 } },
            grid: { color: '#e2e8f0' },
          },
        },
      },
    });
  }

  document.addEventListener('DOMContentLoaded', renderChart);
  document.addEventListener('htmx:afterSwap', renderChart);
})();
