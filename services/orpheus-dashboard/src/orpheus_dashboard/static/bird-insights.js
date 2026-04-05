/**
 * Bird Insights Dashboard - Frontend Logic
 * Fetches bird detection data and renders interactive charts using Plotly.js
 */

let scatterPlotData = null;
let dailyHistogramData = null;
let enabledSpecies = new Set(); // Track which species are enabled for filtering

// Initialize date controls and fetch data on page load
document.addEventListener("DOMContentLoaded", async () => {
  console.log("Bird Insights Dashboard starting...");

  // Check if dateController is available
  if (!window.dateController) {
    console.error("DateController not available!");
    showError("scatter-plot", "Initialization error - please refresh page");
    showError("daily-histogram", "Initialization error - please refresh page");
    showError(
      "non-bird-histogram",
      "Initialization error - please refresh page",
    );
    return;
  }

  // Initialize date controller
  try {
    window.dateController.init({
      onChange: (startDate, endDate) => {
        console.log("Date range changed:", startDate, endDate);
        window.dateController.updateDisplay(); // Update display text when dates change
        loadBirdData();
      },
      defaultDays: 7,
    });
    console.log("Date controller initialized successfully");
  } catch (error) {
    console.error("Failed to initialize date controller:", error);
  }

  // Display user's timezone
  const tzElement = document.getElementById("timezone-name");
  if (tzElement) {
    tzElement.textContent = window.dateController.getUserTimezone();
  }

  // Check if Plotly is loaded
  if (typeof Plotly === "undefined") {
    console.error("Plotly library not loaded!");
    showError(
      "scatter-plot",
      "Chart library not available. Please refresh the page.",
    );
    showError(
      "daily-histogram",
      "Chart library not available. Please refresh the page.",
    );
    showError(
      "non-bird-histogram",
      "Chart library not available. Please refresh the page.",
    );
    return;
  }
  console.log("Plotly library loaded successfully");

  // Load initial data
  console.log("Loading initial bird data...");
  await loadBirdData();
});

async function loadBirdData() {
  try {
    const queryParams = window.dateController.getQueryParams();
    console.log("Fetching bird data with params:", queryParams);

    // Fetch all datasets in parallel
    const [historyResponse, dailyResponse, nonBirdResponse] = await Promise.all(
      [
        fetch(`/api/data/birds/history?${queryParams}`),
        fetch(`/api/data/birds/daily?${queryParams}`),
        fetch(`/api/data/non-birds/daily?${queryParams}`),
      ],
    );

    console.log("Bird data responses:", {
      history: historyResponse.ok,
      daily: dailyResponse.ok,
      nonBird: nonBirdResponse.ok,
    });

    if (!historyResponse.ok || !dailyResponse.ok || !nonBirdResponse.ok) {
      throw new Error("Failed to fetch bird data");
    }

    const historyData = await historyResponse.json();
    const dailyData = await dailyResponse.json();
    const nonBirdData = await nonBirdResponse.json();

    console.log("Bird data loaded:", {
      historyCount: historyData.detections?.length || 0,
      dailyCount: dailyData.daily_counts?.length || 0,
      nonBirdCount: nonBirdData.daily_counts?.length || 0,
    });

    // Store data globally for potential re-rendering
    scatterPlotData = historyData;
    dailyHistogramData = dailyData;

    // Initialize species filter on first load (BEFORE rendering)
    if (enabledSpecies.size === 0) {
      initializeSpeciesFilter(historyData);
    }

    // Render charts (species filter is now populated)
    renderScatterPlot(historyData);
    renderDailyHistogram(dailyData);
    renderNonBirdHistogram(nonBirdData);

    updateTimestamp();
  } catch (error) {
    console.error("Error loading bird data:", error);
    showError("scatter-plot", "Failed to load detection timeline data");
    showError("daily-histogram", "Failed to load daily sightings data");
    showError("non-bird-histogram", "Failed to load non-bird sounds data");
  }
}

function renderScatterPlot(data) {
  const container = document.getElementById("scatter-plot");

  if (!data.detections || data.detections.length === 0) {
    container.innerHTML =
      '<p class="no-data">No bird detections found in the last 7 days.</p>';
    return;
  }

  // Check if Plotly is loaded
  if (typeof Plotly === "undefined") {
    container.innerHTML =
      '<p class="error-message">Chart library not available. Please refresh the page.</p>';
    return;
  }

  // Filter detections by enabled species (skip filter if empty - initialization)
  const filteredDetections =
    enabledSpecies.size === 0
      ? data.detections
      : data.detections.filter((det) => {
          const species = det.species_common || det.species_code || "Unknown";
          return enabledSpecies.has(species);
        });

  if (filteredDetections.length === 0) {
    container.innerHTML =
      '<p class="no-data">No detections match the selected species filter.</p>';
    return;
  }

  // Group detections by species for color coding
  const speciesGroups = {};
  filteredDetections.forEach((det) => {
    const species = det.species_common || det.species_code || "Unknown";
    if (!speciesGroups[species]) {
      speciesGroups[species] = {
        timestamps: [],
        confidences: [],
        channels: [],
        hoverTexts: [],
      };
    }

    const timestamp = new Date(det.timestamp);
    speciesGroups[species].timestamps.push(timestamp);
    speciesGroups[species].confidences.push((det.confidence * 100).toFixed(1));
    speciesGroups[species].channels.push(det.channel);
    speciesGroups[species].hoverTexts.push(
      `<b>${species}</b><br>` +
        `Time: ${timestamp.toLocaleString()}<br>` +
        `Confidence: ${(det.confidence * 100).toFixed(1)}%<br>` +
        `Channel: ${det.channel}`,
    );
  });

  // Create traces for each species
  const traces = Object.entries(speciesGroups).map(([species, group]) => ({
    x: group.timestamps,
    y: group.confidences,
    mode: "markers",
    type: "scatter",
    name: species,
    marker: {
      size: 8,
      opacity: 0.7,
    },
    text: group.hoverTexts,
    hovertemplate: "%{text}<extra></extra>",
  }));

  const layout = {
    title: "",
    xaxis: {
      title: "Detection Time",
      type: "date",
      showgrid: true,
    },
    yaxis: {
      title: "Confidence (%)",
      range: [0, 100],
      showgrid: true,
    },
    hovermode: "closest",
    showlegend: true,
    legend: {
      orientation: "h",
      y: -0.2,
    },
    margin: { t: 20, b: 80, l: 60, r: 20 },
    plot_bgcolor: "rgba(0,0,0,0.05)",
    paper_bgcolor: "transparent",
  };

  const config = {
    responsive: true,
    displayModeBar: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  };

  Plotly.newPlot(container, traces, layout, config);
}

function renderDailyHistogram(data) {
  const container = document.getElementById("daily-histogram");

  if (!data.daily_counts || data.daily_counts.length === 0) {
    container.innerHTML =
      '<p class="no-data">No daily sightings data available.</p>';
    return;
  }

  // Check if Plotly is loaded
  if (typeof Plotly === "undefined") {
    container.innerHTML =
      '<p class="error-message">Chart library not available. Please refresh the page.</p>';
    return;
  }

  // Filter species in daily counts (skip filter if empty - initialization)
  const filteredCounts =
    enabledSpecies.size === 0
      ? data.daily_counts
      : data.daily_counts.map((day) => ({
          ...day,
          species_counts: Object.fromEntries(
            Object.entries(day.species_counts || {}).filter(([species]) =>
              enabledSpecies.has(species),
            ),
          ),
        }));

  // Extract dates and species
  const dates = data.daily_counts.map((d) => d.date);
  const species = data.species || [];

  // Create traces for each species (stacked bars)
  const traces = species.map((sp) => {
    const counts = data.daily_counts.map((d) => d[sp] || 0);
    return {
      x: dates,
      y: counts,
      name: sp,
      type: "bar",
      hovertemplate: `<b>${sp}</b><br>Date: %{x}<br>Count: %{y}<extra></extra>`,
    };
  });

  const layout = {
    title: "",
    barmode: "stack",
    xaxis: {
      title: "Date",
      type: "category",
    },
    yaxis: {
      title: "Number of Detections",
      showgrid: true,
    },
    hovermode: "closest",
    showlegend: true,
    legend: {
      orientation: "h",
      y: -0.2,
    },
    margin: { t: 20, b: 80, l: 60, r: 20 },
    plot_bgcolor: "rgba(0,0,0,0.05)",
    paper_bgcolor: "transparent",
  };

  const config = {
    responsive: true,
    displayModeBar: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  };

  Plotly.newPlot(container, traces, layout, config);
}

function renderNonBirdHistogram(data) {
  const container = document.getElementById("non-bird-histogram");

  if (!data.daily_counts || data.daily_counts.length === 0) {
    container.innerHTML =
      '<p class="no-data">No non-bird sounds detected in this period.</p>';
    return;
  }

  // Check if Plotly is loaded
  if (typeof Plotly === "undefined") {
    container.innerHTML =
      '<p class="error-message">Chart library not available. Please refresh the page.</p>';
    return;
  }

  // Extract dates and sound types
  const dates = data.daily_counts.map((d) => d.date);
  const soundTypes = data.sound_types || [];

  // Create traces for each sound type
  const traces = soundTypes.map((soundType) => {
    const counts = data.daily_counts.map((d) => d[soundType] || 0);
    return {
      x: dates,
      y: counts,
      name: soundType,
      type: "bar",
      hovertemplate: `<b>${soundType}</b><br>Date: %{x}<br>Count: %{y}<extra></extra>`,
    };
  });

  const layout = {
    title: "",
    barmode: "stack",
    xaxis: {
      title: "Date",
      type: "category",
    },
    yaxis: {
      title: "Number of Detections",
      rangemode: "tozero",
    },
    hovermode: "x unified",
    showlegend: true,
    legend: {
      orientation: "h",
      y: -0.2,
    },
    margin: { t: 20, b: 80, l: 60, r: 20 },
    plot_bgcolor: "rgba(0,0,0,0.05)",
    paper_bgcolor: "transparent",
    colorway: [
      "#ff6b6b",
      "#ffd93d",
      "#ff9a3d",
      "#a18cd1",
      "#f78fb3",
      "#95e1d3",
    ],
  };

  const config = {
    responsive: true,
    displayModeBar: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  };

  Plotly.newPlot(container, traces, layout, config);
}

function showError(containerId, message) {
  const container = document.getElementById(containerId);
  container.innerHTML = `<p class="error-message">${message}</p>`;
}

/**
 * Initialize species filter from detection data
 */
function initializeSpeciesFilter(data) {
  // Extract unique species from detections
  const speciesSet = new Set();

  if (!data || !data.detections || data.detections.length === 0) {
    console.warn("No detections available for species filter");
    const filterContainer = document.getElementById("species-filter");
    if (filterContainer) {
      filterContainer.innerHTML =
        '<p class="no-data">No species data available</p>';
    }
    return;
  }

  data.detections.forEach((det) => {
    const species = det.species_common || det.species_code || "Unknown";
    speciesSet.add(species);
  });

  console.log(
    "Initializing species filter with species:",
    Array.from(speciesSet),
  );

  // Initialize all species as enabled
  enabledSpecies.clear();
  speciesSet.forEach((species) => enabledSpecies.add(species));

  // Build filter UI
  renderSpeciesFilter(Array.from(speciesSet).sort());
}

/**
 * Render species filter checkboxes
 */
function renderSpeciesFilter(species) {
  const filterContainer = document.getElementById("species-filter");
  if (!filterContainer) return;

  let html = `
    <div class="filter-header">
      <strong>Filter by Species:</strong>
      <button onclick="toggleAllSpecies(false)" class="btn-secondary btn-small">Uncheck All</button>
      <button onclick="toggleAllSpecies(true)" class="btn-secondary btn-small">Check All</button>
    </div>
    <div class="filter-checkboxes">
  `;

  species.forEach((sp) => {
    html += `
      <label class="checkbox-label">
        <input type="checkbox" 
               value="${sp}" 
               checked 
               onchange="toggleSpecies('${sp.replace(/'/g, "\\'")}', this.checked)">
        <span>${sp}</span>
      </label>
    `;
  });

  html += "</div>";
  filterContainer.innerHTML = html;
}

/**
 * Toggle a single species on/off
 */
function toggleSpecies(species, enabled) {
  if (enabled) {
    enabledSpecies.add(species);
  } else {
    enabledSpecies.delete(species);
  }

  // Re-render charts with filtered data
  if (scatterPlotData) renderScatterPlot(scatterPlotData);
  if (dailyHistogramData) renderDailyHistogram(dailyHistogramData);
}

/**
 * Toggle all species on/off
 */
function toggleAllSpecies(enabled) {
  const checkboxes = document.querySelectorAll(
    '#species-filter input[type="checkbox"]',
  );
  checkboxes.forEach((cb) => {
    cb.checked = enabled;
    const species = cb.value;
    if (enabled) {
      enabledSpecies.add(species);
    } else {
      enabledSpecies.delete(species);
    }
  });

  // Re-render charts with filtered data
  if (scatterPlotData) renderScatterPlot(scatterPlotData);
  if (dailyHistogramData) renderDailyHistogram(dailyHistogramData);
}
