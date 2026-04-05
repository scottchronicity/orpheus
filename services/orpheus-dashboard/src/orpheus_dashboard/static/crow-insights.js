/**
 * Crow Insights Dashboard - Frontend Logic
 * Fetches crow detection statistics and renders interactive charts using Plotly.js
 */

let crowStatsData = null;

// Initialize date controls and fetch data on page load
document.addEventListener("DOMContentLoaded", async () => {
  console.log("Crow Insights Dashboard starting...");

  // Check if dateController is available
  if (!window.dateController) {
    console.error("DateController not available!");
    return;
  }

  // Initialize date controller
  try {
    window.dateController.init({
      onChange: (startDate, endDate) => {
        console.log("Date range changed:", startDate, endDate);
        loadCrowData();
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
    return;
  }
  console.log("Plotly library loaded successfully");

  // Load initial data
  console.log("Loading initial crow data...");
  await loadCrowData();
});

async function loadCrowData() {
  try {
    const queryParams = window.dateController.getQueryParams();
    console.log("Fetching crow data with params:", queryParams);
    const response = await fetch(`/api/data/crows/stats?${queryParams}`);

    console.log("Crow data response:", response.ok);

    if (!response.ok) {
      throw new Error("Failed to fetch crow data");
    }

    crowStatsData = await response.json();

    console.log("Crow data loaded:", {
      total: crowStatsData.total_detections,
      hasAgeData: Object.keys(crowStatsData.age_distribution || {}).length > 0,
      hasCallTypes: Object.keys(crowStatsData.call_types || {}).length > 0,
    });

    // Update summary cards
    updateSummaryCards(crowStatsData);

    // Render charts
    renderHourlyChart(crowStatsData);
    renderAgeChart(crowStatsData);
    renderCallTypeChart(crowStatsData);

    // Show intent chart if data is available
    if (
      crowStatsData.intents &&
      Object.keys(crowStatsData.intents).length > 0
    ) {
      document.getElementById("intent-section").style.display = "block";
      renderIntentChart(crowStatsData);
    }

    updateTimestamp();
  } catch (error) {
    console.error("Error loading crow data:", error);
    showError("hourly-chart", "Failed to load crow activity data");
  }
}

function updateSummaryCards(data) {
  const totalDetections = document.getElementById("total-detections");
  const peakHour = document.getElementById("peak-hour");

  totalDetections.textContent = data.total_detections || 0;

  // Find peak activity hour
  const hourlyData = data.hourly_activity || [];
  const peakHourData = hourlyData.reduce(
    (max, curr) => (curr.count > max.count ? curr : max),
    { hour: 0, count: 0 },
  );

  if (peakHourData.count > 0) {
    const hour12 = peakHourData.hour % 12 || 12;
    const ampm = peakHourData.hour >= 12 ? "PM" : "AM";
    peakHour.textContent = `${hour12}:00 ${ampm}`;
  } else {
    peakHour.textContent = "N/A";
  }
}

function renderHourlyChart(data) {
  const container = document.getElementById("hourly-chart");

  if (!data.hourly_activity || data.hourly_activity.length === 0) {
    container.innerHTML =
      '<p class="no-data">No hourly activity data available.</p>';
    return;
  }

  // Check if Plotly is loaded
  if (typeof Plotly === "undefined") {
    container.innerHTML =
      '<p class="error-message">Chart library not available. Please refresh the page.</p>';
    return;
  }

  const hours = data.hourly_activity.map((d) => {
    const hour12 = d.hour % 12 || 12;
    const ampm = d.hour >= 12 ? "PM" : "AM";
    return `${hour12} ${ampm}`;
  });
  const counts = data.hourly_activity.map((d) => d.count);

  const trace = {
    x: hours,
    y: counts,
    type: "bar",
    marker: {
      color: "rgba(100, 150, 255, 0.7)",
      line: {
        color: "rgba(100, 150, 255, 1)",
        width: 1,
      },
    },
    hovertemplate: "Hour: %{x}<br>Detections: %{y}<extra></extra>",
  };

  const layout = {
    title: "",
    xaxis: {
      title: "Hour of Day",
      type: "category",
    },
    yaxis: {
      title: "Number of Detections",
      showgrid: true,
    },
    hovermode: "closest",
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

  Plotly.newPlot(container, [trace], layout, config);
}

function renderAgeChart(data) {
  const container = document.getElementById("age-chart");

  if (
    !data.age_distribution ||
    Object.keys(data.age_distribution).length === 0
  ) {
    container.innerHTML =
      '<p class="no-data">No age distribution data available.</p>';
    return;
  }

  // Check if Plotly is loaded
  if (typeof Plotly === "undefined") {
    container.innerHTML =
      '<p class="error-message">Chart library not available. Please refresh the page.</p>';
    return;
  }

  const ages = Object.keys(data.age_distribution).filter(
    (age) => age !== "unknown",
  );
  const counts = ages.map((age) => data.age_distribution[age]);

  // Add unknown if it exists
  if (data.age_distribution.unknown) {
    ages.push("Unknown");
    counts.push(data.age_distribution.unknown);
  }

  const trace = {
    labels: ages,
    values: counts,
    type: "pie",
    hole: 0.4,
    marker: {
      colors: [
        "rgba(255, 180, 50, 0.8)",
        "rgba(100, 200, 150, 0.8)",
        "rgba(150, 150, 150, 0.6)",
      ],
    },
    hovertemplate: "%{label}<br>Count: %{value}<br>%{percent}<extra></extra>",
  };

  const layout = {
    title: "",
    showlegend: true,
    legend: {
      orientation: "h",
      y: -0.2,
    },
    margin: { t: 20, b: 80, l: 20, r: 20 },
    paper_bgcolor: "transparent",
  };

  const config = {
    responsive: true,
    displayModeBar: true,
    displaylogo: false,
  };

  Plotly.newPlot(container, [trace], layout, config);
}

function renderCallTypeChart(data) {
  const container = document.getElementById("call-type-chart");

  if (!data.call_types || Object.keys(data.call_types).length === 0) {
    container.innerHTML = '<p class="no-data">No call type data available.</p>';
    return;
  }

  // Check if Plotly is loaded
  if (typeof Plotly === "undefined") {
    container.innerHTML =
      '<p class="error-message">Chart library not available. Please refresh the page.</p>';
    return;
  }

  const callTypes = Object.keys(data.call_types).filter(
    (ct) => ct !== "unknown",
  );
  const counts = callTypes.map((ct) => data.call_types[ct]);

  // Add unknown if it exists
  if (data.call_types.unknown) {
    callTypes.push("Unknown");
    counts.push(data.call_types.unknown);
  }

  const trace = {
    x: callTypes,
    y: counts,
    type: "bar",
    marker: {
      color: "rgba(150, 100, 255, 0.7)",
      line: {
        color: "rgba(150, 100, 255, 1)",
        width: 1,
      },
    },
    hovertemplate: "Call Type: %{x}<br>Count: %{y}<extra></extra>",
  };

  const layout = {
    title: "",
    xaxis: {
      title: "Call Type",
      type: "category",
    },
    yaxis: {
      title: "Number of Detections",
      showgrid: true,
    },
    hovermode: "closest",
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

  Plotly.newPlot(container, [trace], layout, config);
}

function renderIntentChart(data) {
  const container = document.getElementById("intent-chart");

  if (!data.intents || Object.keys(data.intents).length === 0) {
    container.innerHTML =
      '<p class="no-data">No intent classification data available.</p>';
    return;
  }

  // Check if Plotly is loaded
  if (typeof Plotly === "undefined") {
    container.innerHTML =
      '<p class="error-message">Chart library not available. Please refresh the page.</p>';
    return;
  }

  const intents = Object.keys(data.intents);
  const counts = intents.map((intent) => data.intents[intent]);

  const trace = {
    labels: intents,
    values: counts,
    type: "pie",
    marker: {
      colors: [
        "rgba(255, 100, 100, 0.8)",
        "rgba(100, 255, 150, 0.8)",
        "rgba(255, 200, 100, 0.8)",
        "rgba(100, 180, 255, 0.8)",
      ],
    },
    hovertemplate: "%{label}<br>Count: %{value}<br>%{percent}<extra></extra>",
  };

  const layout = {
    title: "",
    showlegend: true,
    legend: {
      orientation: "h",
      y: -0.2,
    },
    margin: { t: 20, b: 80, l: 20, r: 20 },
    paper_bgcolor: "transparent",
  };

  const config = {
    responsive: true,
    displayModeBar: true,
    displaylogo: false,
  };

  Plotly.newPlot(container, [trace], layout, config);
}

function showError(containerId, message) {
  const container = document.getElementById(containerId);
  container.innerHTML = `<p class="error-message">${message}</p>`;
}
