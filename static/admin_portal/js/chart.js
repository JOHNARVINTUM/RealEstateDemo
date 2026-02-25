const rentCtx = document.getElementById("rentChart");
if (rentCtx) {
  new Chart(rentCtx, {
    type: "line",
    data: {
      labels: ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb"],
      datasets: [
        { label: "Actual Revenue", data: [92000, 98000, 103000, 101000, 108000, 0] },
        { label: "Forecasted Revenue", data: [90000, 95000, 100000, 106000, 112000, 118000] },
      ],
    },
  });
}

const waterCtx = document.getElementById("waterChart");
if (waterCtx) {
  new Chart(waterCtx, {
    type: "bar",
    data: {
      labels: ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb"],
      datasets: [{ label: "Cubic Meters", data: [185, 192, 178, 205, 198, 210] }],
    },
  });
}