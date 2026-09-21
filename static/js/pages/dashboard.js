function renderDashboardChart(root = document) {
  const target = root.querySelector?.("[data-dashboard-chart]");
  const source = root.querySelector?.("#dashboard-chart-data");
  if (!target || !source) return;

  const rows = JSON.parse(source.textContent);
  const width = 700;
  const height = 230;
  const margin = { top: 16, right: 12, bottom: 32, left: 12 };
  const values = rows.map((row) => Number(row.amount));
  const minimum = Math.min(...values, 0);
  const maximum = Math.max(...values, 0);
  const range = maximum - minimum || 1;
  const x = (index) => margin.left + (index * (width - margin.left - margin.right)) / 6;
  const y = (value) => margin.top + (height - margin.top - margin.bottom) * ((maximum - value) / range);
  const points = values.map((value, index) => `${x(index)},${y(value)}`).join(" ");
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("preserveAspectRatio", "none");

  [0, 0.5, 1].forEach((position) => {
    const line = document.createElementNS(namespace, "line");
    const lineY = margin.top + position * (height - margin.top - margin.bottom);
    line.setAttribute("x1", margin.left);
    line.setAttribute("x2", width - margin.right);
    line.setAttribute("y1", lineY);
    line.setAttribute("y2", lineY);
    line.setAttribute("class", "chart-grid");
    svg.append(line);
  });
  if (minimum < 0 && maximum > 0) {
    const baseline = document.createElementNS(namespace, "line");
    baseline.setAttribute("x1", margin.left);
    baseline.setAttribute("x2", width - margin.right);
    baseline.setAttribute("y1", y(0));
    baseline.setAttribute("y2", y(0));
    baseline.setAttribute("class", "chart-baseline");
    svg.append(baseline);
  }
  const polyline = document.createElementNS(namespace, "polyline");
  polyline.setAttribute("points", points);
  polyline.setAttribute("class", "chart-line");
  svg.append(polyline);
  rows.forEach((row, index) => {
    const point = document.createElementNS(namespace, "circle");
    point.setAttribute("cx", x(index)); point.setAttribute("cy", y(values[index]));
    point.setAttribute("r", 4); point.setAttribute("class", "chart-point");
    svg.append(point);
    const label = document.createElementNS(namespace, "text");
    label.setAttribute("x", x(index)); label.setAttribute("y", height - 8);
    label.setAttribute("class", "chart-label"); label.textContent = row.label;
    svg.append(label);
  });
  target.replaceChildren(svg);
}

renderDashboardChart();
document.body.addEventListener("htmx:afterSwap", (event) => renderDashboardChart(event.detail.target));
