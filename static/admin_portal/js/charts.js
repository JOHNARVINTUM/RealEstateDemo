/* Brand-styled Chart.js configurations */
const BRAND_BLUE   = '#172554';
const BRAND_GREEN  = '#22c55e';
const BRAND_BLUE_L = 'rgba(23,37,84,0.12)';
const BRAND_GREEN_L= 'rgba(34,197,94,0.12)';

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
      bodyFont:  { family: 'Poppins', size: 12 },
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
        },
      ],
    },
    options: sharedOptions,
  });
}

const waterCtx = document.getElementById('waterChart');
if (waterCtx) {
  new Chart(waterCtx, {
    type: 'bar',
    data: {
      labels: ['Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb'],
      datasets: [
        {
          label: 'Cubic Meters',
          data: [185, 192, 178, 205, 198, 210],
          backgroundColor: BRAND_BLUE_L,
          borderColor: BRAND_BLUE,
          borderWidth: 2,
          borderRadius: 8,
          borderSkipped: false,
          hoverBackgroundColor: 'rgba(23,37,84,0.22)',
        },
      ],
    },
    options: sharedOptions,
  });
}
