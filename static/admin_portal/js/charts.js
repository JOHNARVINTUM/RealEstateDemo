/* Brand-styled Chart.js configurations */
const BRAND_BLUE = '#172554';
const BRAND_GREEN = '#22c55e';
const BRAND_BLUE_L = 'rgba(23,37,84,0.12)';
const BRAND_GREEN_L = 'rgba(34,197,94,0.12)';

const sharedOptions = {
  responsive: true,
  plugins: {
    legend: {
      labels: {
        font: { family: 'Poppins', size: 12, weight: '600' },
        color: '#64748b',
        boxWidth: 12,
        padding: 16,
      },
    },
    tooltip: {
      backgroundColor: '#0f172a',
      titleFont: { family: 'Poppins', size: 12, weight: '700' },
      bodyFont: { family: 'Poppins', size: 12 },
      padding: 10,
      cornerRadius: 10,
      displayColors: true,
    },
  },
  scales: {
    x: {
      grid: { display: false },
      ticks: { font: { family: 'Poppins', size: 11 }, color: '#94a3b8' },
    },
    y: {
      grid: { color: 'rgba(226,232,240,0.7)', drawBorder: false },
      ticks: { font: { family: 'Poppins', size: 11 }, color: '#94a3b8' },
      beginAtZero: true,
    },
  },
};

const rentCtx = document.getElementById('rentChart');
if (rentCtx) {
  new Chart(rentCtx, {
    type: 'line',
    data: {
      labels: ['Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb'],
      datasets: [
        {
          label: 'Actual Revenue',
          data: [92000, 98000, 103000, 101000, 108000, 0],
          borderColor: BRAND_BLUE,
          backgroundColor: BRAND_BLUE_L,
          borderWidth: 2.5,
          pointBackgroundColor: BRAND_BLUE,
          pointRadius: 4,
          pointHoverRadius: 6,
          fill: true,
          tension: 0.4,
        },
        {
          label: 'Forecasted Revenue',
          data: [90000, 95000, 100000, 106000, 112000, 118000],
          borderColor: BRAND_GREEN,
          backgroundColor: BRAND_GREEN_L,
          borderWidth: 2,
          borderDash: [6, 4],
          pointBackgroundColor: BRAND_GREEN,
          pointRadius: 4,
          pointHoverRadius: 6,
          fill: true,
          tension: 0.4,
        });
    }
/* Brand-styled Chart.js configurations */
const BRAND_BLUE = '#172554';
const BRAND_GREEN = '#22c55e';
const BRAND_BLUE_L = 'rgba(23,37,84,0.12)';
const BRAND_GREEN_L = 'rgba(34,197,94,0.12)';

const sharedOptions = {
  responsive: true,
  plugins: {
    legend: {
      labels: {
        font: { family: 'Poppins', size: 12, weight: '600' },
        color: '#64748b',
        boxWidth: 12,
        padding: 16,
      },
    },
    tooltip: {
      backgroundColor: '#0f172a',
      titleFont: { family: 'Poppins', size: 12, weight: '700' },
      bodyFont: { family: 'Poppins', size: 12 },
      padding: 10,
      cornerRadius: 10,
      displayColors: true,
    },
  },
  scales: {
    x: {
      grid: { display: false },
      ticks: { font: { family: 'Poppins', size: 11 }, color: '#94a3b8' },
    },
    y: {
      grid: { color: 'rgba(226,232,240,0.7)', drawBorder: false },
      ticks: { font: { family: 'Poppins', size: 11 }, color: '#94a3b8' },
      beginAtZero: true,
    },
  },
};

const rentCtx = document.getElementById('rentChart');
if (rentCtx) {
  new Chart(rentCtx, {
    type: 'line',
    data: {
      labels: ['Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb'],
      datasets: [
        {
          label: 'Actual Revenue',
          data: [92000, 98000, 103000, 101000, 108000, 0],
          borderColor: BRAND_BLUE,
          backgroundColor: BRAND_BLUE_L,
          borderWidth: 2.5,
          pointBackgroundColor: BRAND_BLUE,
          pointRadius: 4,
          pointHoverRadius: 6,
          fill: true,
          tension: 0.4,
        },
        {
          label: 'Forecasted Revenue',
          data: [90000, 95000, 100000, 106000, 112000, 118000],
          borderColor: BRAND_GREEN,
          backgroundColor: BRAND_GREEN_L,
          borderWidth: 2,
          borderDash: [6, 4],
          pointBackgroundColor: BRAND_GREEN,
          pointRadius: 4,
          pointHoverRadius: 6,
          fill: true,
          tension: 0.4,
        }
      ]
    },
    options: sharedOptions
  });

  function updateChart(months) {
    // ... logic would go here
  }

  updateChart(12);
  monthFilter.addEventListener('change', (e) => updateChart(parseInt(e.target.value)));
}

// Water Monitoring Chart with Water-Like Gradient
const waterCtx = document.getElementById('waterChart');
if (waterCtx) {
  const ctx = waterCtx.getContext('2d');
  
  // Create a beautiful water-like gradient
  const waterGradient = ctx.createLinearGradient(0, 0, 0, 400);
  waterGradient.addColorStop(0, 'rgba(6, 182, 212, 0.8)');   // Cyan-500
  waterGradient.addColorStop(1, 'rgba(59, 130, 246, 0.1)');   // Blue-500 (faded)

  new Chart(waterCtx, {
    type: 'bar',
    data: {
      labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],
      datasets: [
        {
          label: 'Cubic Meters',
          data: [185, 210, 178, 245, 198, 225],
          backgroundColor: waterGradient,
          borderColor: '#0891b2',
          borderWidth: 1,
          borderRadius: 12,
          borderSkipped: false,
          hoverBackgroundColor: 'rgba(6, 182, 212, 1)',
          hoverBorderWidth: 2,
          barPercentage: 0.6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#fff',
          titleColor: '#1e293b',
          bodyColor: '#64748b',
          borderColor: '#e2e8f0',
          borderWidth: 1,
          padding: 12,
          displayColors: false,
          callbacks: {
            label: function(context) {
              return `Usage: ${context.parsed.y} m³`;
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(226, 232, 240, 0.5)', drawBorder: false },
          ticks: { font: { family: "'Outfit', sans-serif", size: 11 }, color: '#94a3b8' }
        },
        x: {
          grid: { display: false },
          ticks: { font: { family: "'Outfit', sans-serif", size: 11 }, color: '#94a3b8' }
        }
      }
    }
  });
}
