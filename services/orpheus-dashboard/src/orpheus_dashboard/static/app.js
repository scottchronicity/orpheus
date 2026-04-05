/**
 * Orpheus Dashboard - Frontend Logic
 *
 * Polls API endpoints every 5 seconds and updates the UI.
 * Currently implements:
 * - System health monitoring (CPU, memory, disk)
 * - Service status display
 *
 * TODO:
 * - Hardware validation endpoints
 * - Detection counts from MQTT
 * - Real-time updates via SSE
 */

// Poll interval (default 5s, updated from config)
let pollInterval = 5000;
let updateTimer;
let isUpdating = false;

// Start polling on page load
document.addEventListener("DOMContentLoaded", async () => {
  console.log("Orpheus Dashboard starting...");

  // Initialize theme from localStorage or default
  initializeTheme();

  // Display user's timezone in footer
  updateTimezoneDisplay();

  // Fetch config first
  try {
    const configResponse = await fetch("/api/config");
    if (configResponse.ok) {
      const config = await configResponse.json();
      if (config.poll_interval) {
        pollInterval = config.poll_interval;
        console.log(`Poll interval set to ${pollInterval}ms`);
      }
    }
  } catch (e) {
    console.warn("Failed to fetch config, using defaults", e);
  }

  updateDashboard();
  updateTimer = setInterval(updateDashboard, pollInterval);
});

/**
 * Display the user's timezone in the footer.
 */
function updateTimezoneDisplay() {
  const timezoneSpan = document.getElementById("timezone-name");
  if (timezoneSpan) {
    try {
      // Get the user's timezone name (e.g., "America/Los_Angeles" or "PST")
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      // Also get the offset for clarity
      const offset = new Date().toLocaleTimeString("en-US", {
        timeZoneName: "short",
      });
      // Match timezone abbreviations (case-insensitive for broader compatibility)
      const offsetMatch = offset.match(/[A-Za-z]{2,4}$/);
      const offsetStr = offsetMatch ? offsetMatch[0] : "";

      timezoneSpan.textContent = offsetStr
        ? `${timezone} / ${offsetStr}`
        : timezone;
    } catch (e) {
      timezoneSpan.textContent = "Local";
    }
  }
}

async function updateDashboard() {
  if (isUpdating) {
    console.log("Skipping update - previous update still in progress");
    return;
  }
  isUpdating = true;

  try {
    await updateHealth();
    await updateServices();
    await updateStorageHardware();
    await updateCameras();
    await updateAudioHealth();
    await updateVideoHealth();
    await updateAudioDetections();
    await updateVideoDetections();
    await updateBirdDetections();
    await updateCrowAnalysis();
    await updateCameraViews();
    await updateSnapshotTimelapseStatus();
    // Only fetch debug info once
    if (!document.getElementById("debug-info").classList.contains("loaded")) {
      await updateDebugInfo();
    }
    updateTimestamp();
  } catch (error) {
    console.error("Dashboard update failed:", error);
  } finally {
    isUpdating = false;
  }
}

async function updateHealth() {
  try {
    const response = await fetch("/api/health");
    const health = await response.json();

    const healthDiv = document.getElementById("health");
    healthDiv.className = "data";
    healthDiv.innerHTML = `
            <div class="metric">
                <span class="label">CPU:</span>
                <span class="value ${getHealthClass(health.cpu_percent)}">${health.cpu_percent}%</span>
            </div>
            <div class="metric">
                <span class="label">Memory:</span>
                <span class="value ${getHealthClass(health.memory_percent)}">${health.memory_percent}%</span>
            </div>
            <div class="metric">
                <span class="label">Disk:</span>
                <span class="value ${getHealthClass(health.disk_percent)}">${health.disk_percent}%</span>
            </div>
            <div class="metric">
                <span class="label">Uptime:</span>
                <span class="value">${formatUptime(health.uptime_seconds)}</span>
            </div>
        `;
  } catch (error) {
    document.getElementById("health").innerHTML =
      '<p class="error">❌ Failed to fetch health data</p>';
  }
}

function renderStatusIndicator(elementId, status, text = "") {
  const el = document.getElementById(elementId);
  if (!el) return;

  let icon = "❓";
  let className = "unknown";
  let statusText = text;

  // Handle boolean input for backward compatibility
  if (typeof status === "boolean") {
    status = status ? "healthy" : "critical";
  }

  switch (status) {
    case "healthy":
    case "running":
      icon = "✅";
      className = "ok";
      statusText = statusText || "Healthy";
      break;
    case "degraded":
      icon = "⚠️";
      className = "warning";
      statusText = statusText || "Degraded";
      break;
    case "critical":
    case "stopped":
    case "offline":
      icon = "❌";
      className = "critical";
      statusText = statusText || "Critical";
      break;
    default:
      icon = "❓";
      className = "unknown";
      statusText = statusText || "Unknown";
  }

  el.innerHTML = `<span class="${className}">${icon} ${statusText}</span>`;
}

function updateSystemSummary(id, label, status, linkTarget) {
  const container = document.getElementById("health-summary");
  if (!container) return;

  let item = document.getElementById(`summary-${id}`);
  if (!item) {
    item = document.createElement("div");
    item.id = `summary-${id}`;
    item.className = "summary-item";
    container.appendChild(item);
  }

  // Handle boolean input for backward compatibility
  if (typeof status === "boolean") {
    status = status ? "healthy" : "critical";
  }

  let icon = "❓";
  let className = "unknown";
  let statusText = "Unknown";

  switch (status) {
    case "healthy":
      icon = "✅";
      className = "ok";
      statusText = "Healthy";
      break;
    case "degraded":
      icon = "⚠️";
      className = "warning";
      statusText = "Degraded";
      break;
    case "critical":
      icon = "❌";
      className = "critical";
      statusText = "Issues Detected";
      break;
  }

  item.innerHTML = `
    <a href="#${linkTarget}">${label}</a>
    <span class="${className}">${icon} ${statusText}</span>
  `;
}

async function updateCameras() {
  console.log("Updating cameras...");
  try {
    const response = await fetch("/api/cameras");
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const cameras = await response.json();
    console.log("Cameras data:", cameras);

    const camerasDiv = document.getElementById("cameras");
    camerasDiv.className = "data";

    if (!cameras || cameras.length === 0) {
      camerasDiv.innerHTML = '<p class="placeholder">No cameras detected</p>';
      renderStatusIndicator("status-cameras-header", false, "No Cameras");
      renderStatusIndicator("status-hardware-header", false, "No Devices");
      updateSystemSummary(
        "hardware",
        "Connected Devices",
        false,
        "panel-hardware",
      );
      return;
    }

    // Calculate aggregate status
    let aggregateStatus = "healthy";
    const anyOffline = cameras.some(
      (c) => c.status === "offline" || c.status === "critical",
    );
    const anyDegraded = cameras.some((c) => c.status === "degraded");

    if (anyOffline) {
      aggregateStatus = "degraded"; // One camera down is degraded for the system, not critical? Or critical?
      // User said: "healthy, degraded, failed/unknown? maybe red, yellow, green?"
      // Let's say if ANY camera is offline, the camera subsystem is DEGRADED (unless all are offline?)
      // Actually, if a camera is offline, it's usually just that camera.
      // Let's stick to: Offline -> Critical for that item, but Degraded for the group?
      // Let's use "degraded" for the group if some are offline.
      aggregateStatus = "degraded";
    } else if (anyDegraded) {
      aggregateStatus = "degraded";
    }

    // If NO cameras, that's critical/warning
    if (cameras.length === 0) aggregateStatus = "critical";

    // Update the main header for this panel
    renderStatusIndicator("status-hardware-header", aggregateStatus);
    updateSystemSummary(
      "hardware",
      "Connected Devices",
      aggregateStatus,
      "panel-hardware",
    );

    camerasDiv.innerHTML = cameras
      .map((camera) => {
        const statusClass =
          camera.status === "healthy"
            ? "ok"
            : camera.status === "degraded"
              ? "warning"
              : "critical";
        const statusIcon =
          camera.status === "healthy"
            ? "✅"
            : camera.status === "degraded"
              ? "⚠️"
              : "❌";

        const checks = Object.entries(camera.checks || {})
          .map(([check, result]) => {
            const checkClass = result ? "ok" : "critical";
            const checkIcon = result ? "✓" : "✗";
            // Format check name (replace _ with space)
            const checkName = check.replace(/_/g, " ");
            return `
                <span class="check-pill ${checkClass}">
                    <span class="check-icon">${checkIcon}</span>
                    ${checkName}
                </span>`;
          })
          .join("");

        return `
                <div class="status-item">
                    <div class="item-header">
                        <span class="item-title">
                            <a href="http://${camera.host}" target="_blank" rel="noopener noreferrer">${camera.name}</a>
                            <span class="item-status ${statusClass}" style="margin-left: 10px; font-size: 0.9em;">${statusIcon} ${camera.status}</span>
                        </span>
                    </div>
                    <div class="item-details">
                        ${checks}
                    </div>
                    <div class="item-meta">
                        ${camera.model ? `<span class="meta-pill">Model: ${camera.model}</span>` : ""}
                        ${camera.firmware_version ? `<span class="meta-pill">FW: ${camera.firmware_version}</span>` : ""}
                        ${camera.uptime ? `<span class="meta-pill">Up: ${formatUptime(camera.uptime)}</span>` : ""}
                    </div>
                </div>
            `;
      })
      .join("");
  } catch (error) {
    console.error("Failed to update cameras:", error);
    document.getElementById("cameras").innerHTML =
      '<p class="error">❌ Failed to fetch camera status</p>';
  }
}

async function updateStorageHardware() {
  try {
    const response = await fetch("/api/hardware/storage");
    const devices = await response.json();

    const div = document.getElementById("storage-hardware");
    div.className = "data";

    // Calculate aggregate status
    let aggregateStatus = "healthy";
    const anyCritical = devices.some((d) => d.status === "critical");
    const anyDegraded = devices.some((d) => d.status === "degraded");

    if (anyCritical) aggregateStatus = "critical";
    else if (anyDegraded) aggregateStatus = "degraded";

    renderStatusIndicator("status-storage-header", aggregateStatus);
    updateSystemSummary(
      "storage",
      "Storage Status",
      aggregateStatus,
      "panel-storage",
    );

    const formatSize = (bytes) => {
      if (bytes === 0) return "0 B";
      const k = 1024;
      const sizes = ["B", "KB", "MB", "GB", "TB"];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
    };

    div.innerHTML = devices
      .map((info) => {
        const isHealthy = info.status === "healthy";
        const isDegraded = info.status === "degraded";
        const statusClass = isHealthy
          ? "ok"
          : isDegraded
            ? "warning"
            : "critical";
        const statusIcon = isHealthy ? "✅" : isDegraded ? "⚠️" : "❌";

        const checks = Object.entries(info.checks || {})
          .map(([check, result]) => {
            const checkClass = result ? "ok" : "critical";
            const checkIcon = result ? "✓" : "✗";
            const checkName = check.replace(/_/g, " ");
            return `
                    <span class="check-pill ${checkClass}">
                        <span class="check-icon">${checkIcon}</span>
                        ${checkName}
                    </span>`;
          })
          .join("");

        let usageHtml = "";
        if (info.usage) {
          const percentClass =
            info.usage.percent > 90
              ? "critical"
              : info.usage.percent > 85
                ? "warning"
                : "ok";
          usageHtml = `
                <div class="item-usage" style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #003300;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.9em;">
                        <span style="color: #00cc00;">Usage: <span class="${percentClass}">${info.usage.percent}%</span></span>
                        <span style="color: #666;">${formatSize(info.usage.used)} / ${formatSize(info.usage.total)}</span>
                    </div>
                    <div style="width: 100%; height: 4px; background: #1a1a1a; margin-top: 4px; border-radius: 2px;">
                        <div style="width: ${info.usage.percent}%; height: 100%; background: ${info.usage.percent > 90 ? "#ff0000" : info.usage.percent > 85 ? "#ffaa00" : "#00ff00"}; border-radius: 2px;"></div>
                    </div>
                </div>
            `;
        }

        return `
            <div class="status-item">
                <div class="item-header">
                    <span class="item-title">
                        ${info.name}
                        <span class="item-status ${statusClass}" style="margin-left: 10px; font-size: 0.9em;">${statusIcon} ${info.status}</span>
                    </span>
                </div>
                <div class="item-details">
                    ${checks}
                </div>
                ${usageHtml}
                <div class="item-meta">
                    <span class="meta-pill">Path: ${info.path}</span>
                    ${info.filesystem !== "unknown" ? `<span class="meta-pill">FS: ${info.filesystem}</span>` : ""}
                    ${info.device !== "unknown" ? `<span class="meta-pill">Dev: ${info.device}</span>` : ""}
                    ${info.message ? `<span class="meta-pill warning">${info.message}</span>` : ""}
                </div>
            </div>
        `;
      })
      .join("");

    // Store status for aggregation
    // window.storageStatus = aggregateStatus;
    // updateOverallHardwareStatus();
  } catch (error) {
    console.error("Failed to update storage hardware:", error);
    document.getElementById("storage-hardware").innerHTML =
      '<p class="error">❌ Failed to fetch storage hardware info</p>';
  }
}

async function updateAudioHealth() {
  console.log("Updating audio health...");
  try {
    const response = await fetch("/api/diagnostics/audio");
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const audio = await response.json();
    console.log("Audio health data:", audio);

    const audioDiv = document.getElementById("audio-health");
    audioDiv.classList.remove("loading");

    // Determine status
    let aggregateStatus = "healthy";
    if (!audio.running) {
      aggregateStatus = "degraded";
    }
    // Use percentage thresholds instead of raw count
    const xrunPercent = audio.xrun?.percentage || 0;
    if (xrunPercent >= 5.0) {
      aggregateStatus = "critical"; // Red: ≥5% glitch rate
    } else if (xrunPercent >= 3.0) {
      aggregateStatus = "degraded"; // Yellow: ≥3% to <5% glitch rate
    }
    // else: healthy (green) if <3%
    if (audio.no_signal_channels && audio.no_signal_channels.length > 0) {
      aggregateStatus = "degraded";
    }

    renderStatusIndicator("status-audio-header", aggregateStatus);
    updateSystemSummary(
      "audio",
      "Audio System",
      aggregateStatus,
      "panel-audio",
    );

    // Build the HTML content
    let html = "";

    // Health status message
    if (audio.health_description) {
      html += `<div class="audio-message" style="color: #00cc00; font-style: normal; margin-bottom: 10px;">${audio.health_description}</div>`;
    }

    // MQTT Counter with rate (matching video health display)
    if (audio.mqtt) {
      const mqttRate = audio.mqtt.rate_per_minute || 0;
      const mqttTotal = audio.mqtt.messages_sent || 0;
      const mqttSinceStart = audio.mqtt.messages_since_start || 0;
      const mqttWindow = audio.mqtt.window_seconds || 0;

      html += `
        <div class="audio-mqtt-counter">
          <div>
            <span class="mqtt-label">MQTT MESSAGES</span>
            <div style="font-size: 0.7em; color: #666; margin-top: 2px;">
              ${mqttRate.toFixed(1)}/min (last ${mqttWindow.toFixed(0)}s) | ${mqttSinceStart} since start
            </div>
          </div>
          <div style="text-align: right;">
            <span class="mqtt-value">${mqttTotal}</span>
          </div>
        </div>
      `;
    }

    // XRUN Counter with percentage and explanation
    const xrunCount = audio.xrun?.total || 0;
    // xrunPercent already declared above for status determination (line 459)
    const xrunRate = audio.xrun?.rate_per_minute || 0;
    const xrunClass =
      xrunPercent < 0.5 ? "ok" : xrunPercent < 2.0 ? "warning" : "critical";

    const xrunWindow = audio.xrun?.window_seconds || 60;
    const callbackCount = audio.timing?.callback_count || 0;

    html += `
      <div class="audio-xrun-counter ${xrunClass}">
        <div>
          <span class="xrun-label">AUDIO GLITCHES</span>
          <div style="font-size: 0.7em; color: #666; margin-top: 2px;">
            ${xrunRate.toFixed(1)}/min (last ${xrunWindow}s)
          </div>
        </div>
        <div style="text-align: right;">
          <span class="xrun-value">${xrunPercent.toFixed(2)}%</span>
          <div style="font-size: 0.6em; color: #666; margin-top: 2px;">
            ${xrunCount} of ${callbackCount} callbacks
          </div>
        </div>
      </div>
    `;

    // Status indicator
    const statusIcon = audio.running ? "🔊" : "🔇";
    const statusText = audio.running ? "Active" : "Inactive";
    html += `<div class="audio-status">${statusIcon} Audio: ${statusText}</div>`;

    // Hardware config
    if (audio.hardware) {
      const hw = audio.hardware;
      html += `
        <div class="audio-config">
          <span class="meta-pill">Device: ${hw.device_name || "Unknown"}</span>
          <span class="meta-pill">Rate: ${hw.sample_rate}Hz</span>
          <span class="meta-pill">Buffer: ${hw.buffer_size} samples</span>
          <span class="meta-pill">Channels: ${hw.num_channels}</span>
        </div>
      `;
    }

    // Channel level meters
    if (audio.channels && audio.channels.length > 0) {
      const channelDesc = audio.channels_description || "Channel audio levels";
      html += `<div class="audio-channels-header">Channel Levels</div>`;
      html += `<div style="font-size: 0.7em; color: #666; margin-bottom: 8px;">${channelDesc}</div>`;
      html += `<div class="audio-channel-meters">`;

      audio.channels.sort((a, b) => a.channel_id.localeCompare(b.channel_id));

      for (const ch of audio.channels) {
        const levelPercent = Math.max(
          0,
          Math.min(100, ((ch.level_db + 60) / 60) * 100),
        );
        const peakPercent = Math.max(
          0,
          Math.min(100, ((ch.peak_db + 60) / 60) * 100),
        );

        // Color mapping: green (<-18dB), yellow (-18 to -6dB), red (>-6dB), none (no signal/below -90dB)
        let barColor = "#00ff00"; // green
        if (ch.level_color === "yellow") barColor = "#ffaa00";
        if (ch.level_color === "red") barColor = "#ff0000";
        if (ch.level_color === "none") barColor = "#333"; // gray for no signal

        const signalWarning = !ch.has_signal
          ? `<span class="no-signal-warning">⚠ NO SIGNAL - PHANTOM OFF?</span>`
          : "";

        html += `
          <div class="audio-channel-meter">
            <span class="channel-label">${ch.channel_id}</span>
            <div class="level-bar-container">
              <div class="level-bar" style="width: ${levelPercent}%; background: ${barColor};"></div>
              <div class="peak-marker" style="left: ${peakPercent}%;"></div>
            </div>
            <span class="level-db">${ch.level_db.toFixed(1)}dB</span>
            ${signalWarning}
          </div>
        `;
      }
      html += `</div>`;
    } else {
      html += `<p class="placeholder">No audio channels detected</p>`;
    }

    // Timing stats
    if (audio.timing) {
      const timing = audio.timing;
      html += `
        <div class="audio-timing">
          <span class="meta-pill">Interval: ${timing.callback_interval_ms?.toFixed(1) || 0}ms</span>
          <span class="meta-pill">Jitter: ${timing.jitter_ms?.toFixed(2) || 0}ms</span>
          <span class="meta-pill">Callbacks: ${timing.callback_count || 0}</span>
        </div>
      `;
    }

    // System stats relevant to audio
    if (audio.system) {
      const sys = audio.system;
      let sysHtml = `
        <div class="audio-system-stats">
          <span class="meta-pill">CPU: ${sys.cpu_percent}%</span>
      `;
      if (sys.cpu_freq_mhz) {
        sysHtml += `<span class="meta-pill">${sys.cpu_freq_mhz.toFixed(0)}MHz</span>`;
      }
      if (sys.thermal_temp_c) {
        const tempClass = sys.thermal_throttling ? "critical" : "ok";
        sysHtml += `<span class="meta-pill ${tempClass}">Temp: ${sys.thermal_temp_c.toFixed(1)}°C</span>`;
      }
      if (sys.thermal_throttling) {
        sysHtml += `<span class="meta-pill critical">⚠ THROTTLING</span>`;
      }
      sysHtml += `</div>`;
      html += sysHtml;
    }

    // Message if present
    if (audio.message) {
      html += `<div class="audio-message">${audio.message}</div>`;
    }

    audioDiv.innerHTML = html;
  } catch (error) {
    console.error("Failed to update audio health:", error);
    document.getElementById("audio-health").innerHTML =
      '<p class="placeholder">Audio diagnostics unavailable</p>';
    renderStatusIndicator("status-audio-header", "unknown");
  }
}

async function updateVideoHealth() {
  console.log("Updating video health...");
  try {
    const response = await fetch("/api/diagnostics/video");
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const video = await response.json();
    console.log("Video health data:", video);

    const videoDiv = document.getElementById("video-health");
    videoDiv.classList.remove("loading");

    // Determine status
    let aggregateStatus = "healthy";
    if (!video.running) {
      aggregateStatus = "degraded";
    }
    if (!video.mqtt_connected) {
      aggregateStatus = "degraded";
    }

    renderStatusIndicator("status-video-header", aggregateStatus);
    updateSystemSummary(
      "video",
      "Video System",
      aggregateStatus,
      "panel-video",
    );

    // Build the HTML content
    let html = "";

    // Health status message
    if (video.health_description) {
      html += `<div class="video-message" style="color: #00cc00; font-style: normal; margin-bottom: 10px;">${video.health_description}</div>`;
    } else if (video.message) {
      html += `<div class="video-message">${video.message}</div>`;
    }

    // MQTT Counter with rate
    if (video.mqtt) {
      const mqttRate = video.mqtt.rate_per_minute || 0;
      const mqttTotal = video.mqtt.messages_sent || 0;
      const mqttSinceStart = video.mqtt.messages_since_start || 0;
      const mqttWindow = video.mqtt.window_seconds || 0;

      html += `
        <div class="video-mqtt-counter">
          <div>
            <span class="mqtt-label">MQTT MESSAGES</span>
            <div style="font-size: 0.7em; color: #666; margin-top: 2px;">
              ${mqttRate.toFixed(1)}/min (last ${mqttWindow.toFixed(0)}s) | ${mqttSinceStart} since start
            </div>
          </div>
          <div style="text-align: right;">
            <span class="mqtt-value">${mqttTotal}</span>
          </div>
        </div>
      `;
    }

    // Status indicator
    const statusIcon = video.running ? "📹" : "📴";
    const statusText = video.running ? "Active" : "Inactive";
    html += `<div class="video-status">${statusIcon} Video: ${statusText}</div>`;

    // Hardware config
    if (video.hardware && video.hardware.fps) {
      const hw = video.hardware;
      html += `
        <div class="video-config">
          <span class="meta-pill">FPS: ${hw.fps}</span>
          <span class="meta-pill">Resolution: ${hw.width}x${hw.height}</span>
          <span class="meta-pill">Cameras: ${hw.num_cameras}</span>
        </div>
      `;
    }

    // Camera level meters (motion levels and thresholds)
    if (video.cameras && video.cameras.length > 0) {
      const camerasDesc =
        video.cameras_description || "Per-camera motion levels";
      html += `<div class="video-cameras-header">Camera Motion Levels</div>`;
      html += `<div style="font-size: 0.7em; color: #666; margin-bottom: 8px;">${camerasDesc}</div>`;
      html += `<div class="video-camera-meters">`;

      video.cameras.sort((a, b) => a.camera_id.localeCompare(b.camera_id));

      for (const cam of video.cameras) {
        const motionPercent = Math.max(0, Math.min(100, cam.motion_level || 0));
        const peakPercent = Math.max(0, Math.min(100, cam.peak_motion || 0));
        const threshold = cam.motion_threshold || 25.0;
        const releaseThreshold = cam.release_threshold || 12.5;

        // Color mapping based on threshold
        let barColor = "#00ff00"; // green (below release threshold)
        if (motionPercent >= threshold) {
          barColor = "#ff0000"; // red (above trigger threshold)
        } else if (motionPercent >= releaseThreshold) {
          barColor = "#ffaa00"; // yellow (between release and trigger)
        }

        // Threshold markers on the bar
        const thresholdMarkerPos = Math.min(100, threshold);
        const releaseMarkerPos = Math.min(100, releaseThreshold);

        const lastDetection = cam.last_detection
          ? formatTimeAgo(new Date(cam.last_detection))
          : "Never";
        const framesProcessed = cam.frames_processed || 0;
        const detectionsCount = cam.detections_count || 0;

        html += `
          <div class="video-camera-meter">
            <span class="camera-label">${cam.camera_id}</span>
            <div class="level-bar-container">
              <div class="level-bar" style="width: ${motionPercent}%; background: ${barColor};"></div>
              <div class="peak-marker" style="left: ${peakPercent}%;"></div>
              <div class="threshold-marker" style="left: ${thresholdMarkerPos}%;" title="Trigger threshold: ${threshold.toFixed(1)}%"></div>
              <div class="threshold-marker release" style="left: ${releaseMarkerPos}%;" title="Release threshold: ${releaseThreshold.toFixed(1)}%"></div>
            </div>
            <span class="level-value">${motionPercent.toFixed(1)}%</span>
            <div style="font-size: 0.6em; color: #666; margin-top: 2px;">
              Frames: ${framesProcessed} | Detections: ${detectionsCount} | Last: ${lastDetection}
            </div>
          </div>
        `;
      }
      html += `</div>`;
    } else {
      html += `<p class="placeholder">No cameras detected</p>`;
    }

    // Timing stats
    if (video.timing && video.timing.frame_count > 0) {
      const timing = video.timing;
      html += `
        <div class="video-timing">
          <span class="meta-pill">Interval: ${timing.frame_interval_ms?.toFixed(1) || 0}ms</span>
          <span class="meta-pill">Jitter: ${timing.jitter_ms?.toFixed(2) || 0}ms</span>
          <span class="meta-pill">Frames: ${timing.frame_count || 0}</span>
        </div>
      `;
    }

    // System stats relevant to video
    if (video.system && video.system.cpu_percent > 0) {
      const sys = video.system;
      let sysHtml = `
        <div class="video-system-stats">
          <span class="meta-pill">CPU: ${sys.cpu_percent}%</span>
      `;
      if (sys.cpu_freq_mhz) {
        sysHtml += `<span class="meta-pill">${sys.cpu_freq_mhz.toFixed(0)}MHz</span>`;
      }
      if (sys.thermal_temp_c) {
        const tempClass = sys.thermal_throttling ? "critical" : "ok";
        sysHtml += `<span class="meta-pill ${tempClass}">Temp: ${sys.thermal_temp_c.toFixed(1)}°C</span>`;
      }
      if (sys.thermal_throttling) {
        sysHtml += `<span class="meta-pill critical">⚠ THROTTLING</span>`;
      }
      sysHtml += `</div>`;
      html += sysHtml;
    }

    videoDiv.innerHTML = html;
  } catch (error) {
    console.error("Failed to update video health:", error);
    document.getElementById("video-health").innerHTML =
      '<p class="placeholder">Video diagnostics unavailable</p>';
    renderStatusIndicator("status-video-header", "unknown");
  }
}

// Track expanded state for audio detection channels
const expandedChannels = new Set();

// Track expanded state for video detection cameras
const expandedCameras = new Set();

async function updateAudioDetections() {
  console.log("Updating audio detections...");
  try {
    const response = await fetch("/api/diagnostics/audio/detections");
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    console.log("Audio detections data:", data);

    const detectionsDiv = document.getElementById("audio-detections");
    detectionsDiv.classList.remove("loading");

    // Determine aggregate status based on detections
    let aggregateStatus = "healthy";
    if (!data.mqtt_connected) {
      aggregateStatus = "degraded";
    }

    renderStatusIndicator("status-audio-detections-header", aggregateStatus);

    let html = "";

    // MQTT connection warning
    if (!data.mqtt_connected) {
      html += `<div class="mqtt-warning">⚠️ MQTT not connected - detections may not be received</div>`;
    }

    // Summary cards (2x2 grid)
    html += '<div class="detection-summary-grid">';
    for (const channelId of ["1", "2", "3", "4"]) {
      const detection = data.summary[channelId];
      const isExpanded = expandedChannels.has(channelId);

      let statusClass = "gray";
      let timeAgo = "No detections";
      let statusIcon = "⏳";

      if (detection && detection.timestamp) {
        const detectionTime = parseTimestamp(detection.timestamp);
        const now = new Date();
        const diffMs = now - detectionTime;
        const diffMinutes = Math.floor(diffMs / 60000);

        if (diffMinutes < 5) {
          statusClass = "green";
          statusIcon = "🟢";
        } else if (diffMinutes < 30) {
          statusClass = "yellow";
          statusIcon = "🟡";
        } else {
          statusClass = "gray";
          statusIcon = "⚪";
        }

        timeAgo = formatTimeAgo(detectionTime);
      }

      html += `
        <div class="detection-card ${statusClass} ${isExpanded ? "expanded" : ""}" 
             onclick="toggleChannelHistory('${channelId}')" 
             data-channel="${channelId}">
          <div class="detection-card-header">
            <span class="channel-icon">🎤</span>
            <span class="channel-name">Channel ${channelId}</span>
            <span class="expand-icon">${isExpanded ? "▼" : "▶"}</span>
          </div>
          <div class="detection-card-status">
            <span class="status-icon">${statusIcon}</span>
            <span class="time-ago">${timeAgo}</span>
          </div>
        </div>
      `;
    }
    html += "</div>";

    // Expandable history tables for each channel
    for (const channelId of ["1", "2", "3", "4"]) {
      const isExpanded = expandedChannels.has(channelId);
      if (isExpanded) {
        const channelHistory = data.history.filter(
          (d) => d.channel_id === channelId,
        );
        const last10 = channelHistory.slice(0, 10);

        html += `
          <div class="channel-history" id="history-${channelId}">
            <h4>🎤 Channel ${channelId} - Recent Detections</h4>
            ${
              last10.length > 0
                ? `
              <table class="detection-table">
                <thead>
                  <tr>
                    <th>⏱️ Time</th>
                    <th>Duration</th>
                    <th>📊 Peak dB</th>
                    <th>Clip</th>
                  </tr>
                </thead>
                <tbody>
                  ${last10
                    .map((d) => {
                      const time = formatTimestamp(d.timestamp);
                      const duration = d.duration_seconds
                        ? `${d.duration_seconds.toFixed(2)}s`
                        : "-";
                      const peakDb = d.peak_energy_db
                        ? `${d.peak_energy_db.toFixed(1)} dB`
                        : "-";
                      const clipLink = d.clip_path
                        ? `<a href="${getClipUrl(d.clip_path)}" class="clip-link" target="_blank">📁 Download</a>`
                        : "-";
                      return `
                        <tr>
                          <td>${time}</td>
                          <td>${duration}</td>
                          <td>${peakDb}</td>
                          <td>${clipLink}</td>
                        </tr>
                      `;
                    })
                    .join("")}
                </tbody>
              </table>
            `
                : '<p class="placeholder">No detections recorded for this channel</p>'
            }
          </div>
        `;
      }
    }

    detectionsDiv.innerHTML = html;
  } catch (error) {
    console.error("Failed to update audio detections:", error);
    document.getElementById("audio-detections").innerHTML =
      '<p class="placeholder">Waiting for audio detections...</p>';
    renderStatusIndicator("status-audio-detections-header", "unknown");
  }
}

function toggleChannelHistory(channelId) {
  if (expandedChannels.has(channelId)) {
    expandedChannels.delete(channelId);
  } else {
    expandedChannels.add(channelId);
  }
  // Immediately refresh to show/hide the history
  updateAudioDetections();
}

async function updateVideoDetections() {
  console.log("Updating video detections...");
  try {
    const response = await fetch("/api/diagnostics/video/detections");
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    console.log("Video detections data:", data);

    const detectionsDiv = document.getElementById("video-detections");
    detectionsDiv.classList.remove("loading");

    // Determine aggregate status based on detections
    let aggregateStatus = "healthy";
    if (!data.mqtt_connected) {
      aggregateStatus = "degraded";
    }

    renderStatusIndicator("status-video-detections-header", aggregateStatus);

    let html = "";

    // MQTT connection warning
    if (!data.mqtt_connected) {
      html += `<div class="mqtt-warning">⚠️ MQTT not connected - detections may not be received</div>`;
    }

    // Summary cards (2x2 grid for 4 cameras)
    html += '<div class="detection-summary-grid">';
    const cameraIds = [
      "orpheus-eye-1",
      "orpheus-eye-2",
      "orpheus-eye-3",
      "orpheus-eye-4",
    ];
    for (const cameraId of cameraIds) {
      const detection = data.summary[cameraId];
      const isExpanded = expandedCameras.has(cameraId);

      let statusClass = "gray";
      let timeAgo = "No detections";
      let statusIcon = "⏳";

      if (detection && detection.timestamp) {
        const detectionTime = parseTimestamp(detection.timestamp);
        const now = new Date();
        const diffMs = now - detectionTime;
        const diffMinutes = Math.floor(diffMs / 60000);

        if (diffMinutes < 5) {
          statusClass = "green";
          statusIcon = "🟢";
        } else if (diffMinutes < 30) {
          statusClass = "yellow";
          statusIcon = "🟡";
        } else {
          statusClass = "gray";
          statusIcon = "⚪";
        }

        timeAgo = formatTimeAgo(detectionTime);
      }

      html += `
        <div class="detection-card ${statusClass} ${isExpanded ? "expanded" : ""}" 
             onclick="toggleCameraHistory('${cameraId}')" 
             data-camera="${cameraId}">
          <div class="detection-card-header">
            <span class="channel-icon">📹</span>
            <span class="channel-name">${cameraId}</span>
            <span class="expand-icon">${isExpanded ? "▼" : "▶"}</span>
          </div>
          <div class="detection-card-status">
            <span class="status-icon">${statusIcon}</span>
            <span class="time-ago">${timeAgo}</span>
          </div>
        </div>
      `;
    }
    html += "</div>";

    // Expandable history tables for each camera
    for (const cameraId of cameraIds) {
      const isExpanded = expandedCameras.has(cameraId);
      if (isExpanded) {
        const cameraHistory = data.history.filter(
          (d) => d.camera_id === cameraId,
        );
        const last10 = cameraHistory.slice(0, 10);

        html += `
          <div class="channel-history" id="history-${cameraId}">
            <h4>📹 ${cameraId} - Recent Detections</h4>
            ${
              last10.length > 0
                ? `
              <table class="detection-table">
                <thead>
                  <tr>
                    <th>⏱️ Time</th>
                    <th>Duration</th>
                    <th>📊 Peak Motion</th>
                    <th>Clip</th>
                  </tr>
                </thead>
                <tbody>
                  ${last10
                    .map((d) => {
                      const time = formatTimestamp(d.timestamp);
                      const duration = d.duration_seconds
                        ? `${d.duration_seconds.toFixed(2)}s`
                        : "-";
                      const peakMotion = d.peak_motion_value
                        ? `${d.peak_motion_value.toFixed(1)}%`
                        : "-";
                      const clipLink = d.clip_path
                        ? `<a href="${getClipUrl(d.clip_path)}" class="clip-link" target="_blank">📁 Download</a>`
                        : "-";
                      return `
                        <tr>
                          <td>${time}</td>
                          <td>${duration}</td>
                          <td>${peakMotion}</td>
                          <td>${clipLink}</td>
                        </tr>
                      `;
                    })
                    .join("")}
                </tbody>
              </table>
            `
                : '<p class="placeholder">No detections recorded for this camera</p>'
            }
          </div>
        `;
      }
    }

    detectionsDiv.innerHTML = html;
  } catch (error) {
    console.error("Failed to update video detections:", error);
    document.getElementById("video-detections").innerHTML =
      '<p class="placeholder">Waiting for video detections...</p>';
    renderStatusIndicator("status-video-detections-header", "unknown");
  }
}

function toggleCameraHistory(cameraId) {
  if (expandedCameras.has(cameraId)) {
    expandedCameras.delete(cameraId);
  } else {
    expandedCameras.add(cameraId);
  }
  // Immediately refresh to show/hide the history
  updateVideoDetections();
}

function formatTimeAgo(date) {
  const now = new Date();
  const diffMs = now - date;
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSeconds < 60) {
    return "Just now";
  } else if (diffMinutes < 60) {
    return `${diffMinutes} min ago`;
  } else if (diffHours < 24) {
    return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
  } else {
    return `${diffDays} day${diffDays > 1 ? "s" : ""} ago`;
  }
}

/**
 * Parse a timestamp string and return a Date object.
 * Handles timestamps that may or may not have timezone info.
 * Assumes UTC if no timezone is specified (since backend uses datetime.utcnow()).
 */
function parseTimestamp(timestamp) {
  if (!timestamp) return null;

  // If timestamp already ends with 'Z' or has timezone offset (with or without colon), parse directly
  if (timestamp.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(timestamp)) {
    return new Date(timestamp);
  }

  // Assume UTC if no timezone info (backend uses datetime.utcnow())
  return new Date(timestamp + "Z");
}

/**
 * Format a timestamp for display in the user's local timezone.
 */
function formatTimestamp(timestamp) {
  const date = parseTimestamp(timestamp);
  if (!date || isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

/**
 * Convert filesystem clip path to API URL.
 * Supports both audio clips (/audio_motion/{channel}/{file})
 * and video clips (/video/motion/{camera}/{file}).
 * @param {string} clipPath - Full filesystem path to the clip
 * @returns {string} API URL for downloading the clip
 */
function getClipUrl(clipPath) {
  // Convert filesystem path to API URL
  if (!clipPath) return "";

  // Handle audio clips
  // Input: /data/orpheus/audio/audio_motion/1/20251201T211427.340286Z.flac
  // Output: /api/audio/clips/1/20251201T211427.340286Z.flac
  const audioMatch = clipPath.match(/audio_motion\/(\d+)\/(.+)$/);
  if (audioMatch) {
    const channelId = audioMatch[1];
    const filename = audioMatch[2];
    return `/api/audio/clips/${channelId}/${filename}`;
  }

  // Handle video clips
  // Input: /data/orpheus/video/video_motion/orpheus-eye-1/20251201T211427.340286Z.mp4
  // Output: /api/video/clips/orpheus-eye-1/20251201T211427.340286Z.mp4
  const videoMatch = clipPath.match(/video_motion\/([^/]+)\/(.+)$/);
  if (videoMatch) {
    const cameraId = videoMatch[1];
    const filename = videoMatch[2];
    return `/api/video/clips/${cameraId}/${filename}`;
  }

  // Fallback: return original path (will likely 404 but preserves behavior)
  return clipPath;
}

// function updateOverallHardwareStatus() {
//   // Check if we have both statuses
//   const cameraStatus = window.camerasStatus;
//   const storageStatus = window.storageStatus;

//   if (!cameraStatus || !storageStatus) return;

//   let aggregate = "healthy";

//   if (cameraStatus === "critical" || storageStatus === "critical") {
//     aggregate = "critical";
//   } else if (cameraStatus === "degraded" || storageStatus === "degraded") {
//     aggregate = "degraded";
//   }

//   renderStatusIndicator("status-hardware-header", aggregate);
//   updateSystemSummary(
//     "hardware",
//     "Hardware Status",
//     aggregate,
//     "panel-hardware",
//   );
// }

async function updateServices() {
  try {
    const response = await fetch("/api/services/status");
    const data = await response.json();

    const servicesDiv = document.getElementById("services");
    servicesDiv.className = "data";

    // Calculate aggregate status
    const allRunning = data.services.every((s) => s.status === "running");
    const anyUnknown = data.services.some((s) => s.status === "unknown");

    let status = "healthy";
    if (!allRunning)
      status = "critical"; // Services down is critical
    else if (anyUnknown) status = "degraded";

    renderStatusIndicator("status-services-header", status);
    updateSystemSummary(
      "services",
      "Services Status",
      status,
      "panel-services",
    );

    servicesDiv.innerHTML = data.services
      .map(
        (service) => `
                <div class="service ${service.status}">
                    <span class="service-name">${service.name}</span>
                    <span class="service-status">${getStatusIcon(service.status)} ${service.status}</span>
                    <span class="service-reason">${service.reason}</span>
                    <div class="service-actions">
                        <button class="log-button" onclick="openLogModal('${service.name}')">Tail Logs</button>
                    </div>
                </div>
            `,
      )
      .join("");
  } catch (error) {
    document.getElementById("services").innerHTML =
      '<p class="error">❌ Failed to fetch service status</p>';
  }
}

function getHealthClass(percent) {
  if (percent > 90) return "critical";
  if (percent > 75) return "warning";
  return "ok";
}

function getStatusIcon(status) {
  switch (status) {
    case "running":
      return "✅";
    case "stopped":
      return "🛑";
    case "unknown":
      return "⚠️";
    default:
      return "❓";
  }
}

function formatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function updateTimestamp() {
  document.getElementById("lastUpdate").textContent =
    new Date().toLocaleTimeString();
}

async function updateCameraViews() {
  console.log("Updating camera views...");
  try {
    const response = await fetch("/api/cameras");
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const cameras = await response.json();

    const viewsDiv = document.getElementById("camera-views");
    viewsDiv.classList.remove("loading");

    if (!cameras || cameras.length === 0) {
      viewsDiv.innerHTML = '<p class="placeholder">No cameras available</p>';
      return;
    }

    // If grid is empty, build initial structure
    if (!viewsDiv.children.length || viewsDiv.children[0].tagName === "P") {
      viewsDiv.innerHTML = cameras
        .map(
          (camera) => `
                <div class="camera-card" id="view-${camera.name}">
                    <div class="camera-view-header">
                        <span class="name">${camera.name}</span>
                        <span class="timestamp">Waiting...</span>
                    </div>
                    <div class="image-container">
                        <img src="/api/cameras/${camera.name}/snapshot" 
                             alt="${camera.name} snapshot"
                             onerror="this.onerror=null;this.src='';this.parentElement.classList.add('error-placeholder');this.parentElement.innerHTML='<span>Signal Lost</span>'">
                    </div>
                </div>
            `,
        )
        .join("");
    } else {
      // Update existing images to avoid flickering
      cameras.forEach((camera) => {
        const card = document.getElementById(`view-${camera.name}`);
        if (card) {
          const container = card.querySelector(".image-container");
          const img = container.querySelector("img");
          const timestamp = card.querySelector(".timestamp");
          const newSrc = `/api/cameras/${camera.name}/snapshot?t=${new Date().getTime()}`;

          if (container.classList.contains("error-placeholder")) {
            // Try to recover from error state
            container.classList.remove("error-placeholder");
            container.innerHTML = `<img src="${newSrc}" alt="${camera.name} snapshot" onerror="this.onerror=null;this.src='';this.parentElement.classList.add('error-placeholder');this.parentElement.innerHTML='<span>Signal Lost</span>'">`;
          } else if (img) {
            // Update existing image
            img.src = newSrc;
          }

          if (timestamp) {
            timestamp.textContent = new Date().toLocaleTimeString();
          }
        }
      });
    }
  } catch (error) {
    console.error("Failed to update camera views:", error);
    // Don't wipe out the whole section on transient errors, just log it
  }
}

async function updateDebugInfo() {
  try {
    const response = await fetch("/api/debug/config");
    const config = await response.json();

    const debugDiv = document.getElementById("debug-info");
    debugDiv.classList.add("loaded");

    // Group orpheus_config by top-level section
    const groupedConfig = groupConfigBySection(config.orpheus_config || {});

    const sections = [
      { title: "Active Configuration", data: groupedConfig },
      { title: "Environment Overrides", data: config.environment_overrides },
      { title: "Camera Registry", data: config.camera_registry },
    ].filter((section) => section.data && Object.keys(section.data).length);

    if (sections.length === 0) {
      debugDiv.innerHTML = '<p class="placeholder">No debug data available</p>';
      return;
    }

    debugDiv.innerHTML = sections.map(renderDebugSection).join("");
  } catch (error) {
    console.error("Failed to update debug info:", error);
    document.getElementById("debug-info").innerHTML =
      '<p class="error">❌ Failed to fetch debug info</p>';
  }
}

function groupConfigBySection(orpheusConfig) {
  const groups = {};

  for (const [key, value] of Object.entries(orpheusConfig)) {
    // Skip config.source as it's metadata
    if (key === "config.source") {
      if (!groups["Meta"]) groups["Meta"] = {};
      groups["Meta"][key] = value;
      continue;
    }

    // Extract the top-level section name
    const parts = key.split(".");
    const section = parts[0] || "Other";
    const capitalizedSection =
      section.charAt(0).toUpperCase() + section.slice(1);

    if (!groups[capitalizedSection]) {
      groups[capitalizedSection] = {};
    }

    // For cameras and audio, create sub-subsections based on second level
    if ((section === "cameras" || section === "audio") && parts.length >= 2) {
      const subsection = parts[1]; // e.g., 'orpheus-eye-1', 'auth', 'channel_0'

      if (!groups[capitalizedSection][subsection]) {
        groups[capitalizedSection][subsection] = {};
      }
      groups[capitalizedSection][subsection][key] = value;
    } else {
      // Regular flat grouping for other sections
      groups[capitalizedSection][key] = value;
    }
  }

  // Sort sections: Meta first, then alphabetically
  const sortedGroups = {};
  if (groups["Meta"]) {
    sortedGroups["Meta"] = groups["Meta"];
  }

  Object.keys(groups)
    .filter((k) => k !== "Meta")
    .sort()
    .forEach((key) => {
      sortedGroups[key] = groups[key];
    });

  return sortedGroups;
}

function renderDebugSection({ title, data }) {
  // Handle grouped config sections (object of objects)
  if (title === "Active Configuration") {
    // This is a grouped section, render each group with its own heading
    const groups = Object.entries(data)
      .map(([groupName, groupData]) => {
        if (Object.keys(groupData).length === 0) return "";

        // Check if this section has sub-subsections (e.g., Cameras or Audio)
        const firstValue = Object.values(groupData)[0];
        const hasSubsections =
          typeof firstValue === "object" && !Array.isArray(firstValue);

        if (hasSubsections) {
          // Render sub-subsections (e.g., orpheus-eye-1, orpheus-eye-2 under Cameras)
          const subsections = Object.entries(groupData)
            .map(([subName, subData]) => {
              const entries = Object.entries(subData).sort(([a], [b]) =>
                a.localeCompare(b),
              );
              if (entries.length === 0) return "";

              const items = entries
                .map(
                  ([key, value]) => `
                <div class="debug-item">
                    <span class="debug-key">${key}</span>
                    <span class="debug-value">${value}</span>
                </div>
              `,
                )
                .join("");

              return `
            <div class="debug-subsubsection">
                <h5>${subName}</h5>
                <div class="debug-grid">
                    ${items}
                </div>
            </div>
          `;
            })
            .join("");

          return `
          <div class="debug-subsection">
              <h4>${groupName}</h4>
              ${subsections}
          </div>
        `;
        } else {
          // Regular flat section
          const entries = Object.entries(groupData).sort(([a], [b]) =>
            a.localeCompare(b),
          );
          const items = entries
            .map(
              ([key, value]) => `
              <div class="debug-item">
                  <span class="debug-key">${key}</span>
                  <span class="debug-value">${value}</span>
              </div>
            `,
            )
            .join("");

          return `
          <div class="debug-subsection">
              <h4>${groupName}</h4>
              <div class="debug-grid">
                  ${items}
              </div>
          </div>
        `;
        }
      })
      .join("");

    return `
      <div class="subsection debug-section">
          <h3>${title} <span style="font-size: 0.8em; color: #666; font-weight: normal;">(YAML + env overrides applied)</span></h3>
          ${groups}
      </div>
    `;
  }

  // Regular section (flat key-value pairs)
  const entries = Object.entries(data).sort(([a], [b]) => a.localeCompare(b));

  if (entries.length === 0) {
    return "";
  }

  const items = entries
    .map(
      ([key, value]) => `
        <div class="debug-item">
            <span class="debug-key">${key}</span>
            <span class="debug-value">${value}</span>
        </div>
      `,
    )
    .join("");

  return `
    <div class="subsection debug-section">
        <h3>${title}</h3>
        <div class="debug-grid">
            ${items}
        </div>
    </div>
  `;
}

// ===== Audio Playback Functions =====

async function loadAvailableSounds() {
  try {
    const response = await fetch("/api/audio/playback/sounds");
    const data = await response.json();

    const select = document.getElementById("sound-select");
    if (data.sounds && data.sounds.length > 0) {
      select.innerHTML = data.sounds
        .map((sound) => `<option value="${sound}">${sound}</option>`)
        .join("");

      renderStatusIndicator(
        "status-playback-header",
        "ok",
        `${data.count} sounds available`,
      );
    } else {
      select.innerHTML = '<option value="">No sounds available</option>';
      renderStatusIndicator(
        "status-playback-header",
        "warning",
        "No sounds configured",
      );
    }
  } catch (error) {
    console.error("Failed to load available sounds:", error);
    const select = document.getElementById("sound-select");
    select.innerHTML = '<option value="">Error loading sounds</option>';
    renderStatusIndicator(
      "status-playback-header",
      "error",
      "Failed to load sounds",
    );
  }
}

async function playSound() {
  const soundName = document.getElementById("sound-select").value;
  const repeatCount = parseInt(document.getElementById("repeat-select").value);
  const pauseBetween = parseFloat(
    document.getElementById("pause-select").value,
  );
  const statusDiv = document.getElementById("playback-status");
  const playButton = document.getElementById("play-button");

  if (!soundName) {
    statusDiv.textContent = "Please select a sound";
    statusDiv.className = "playback-status error";
    return;
  }

  // Disable button during request
  playButton.disabled = true;
  statusDiv.textContent = "Sending playback request...";
  statusDiv.className = "playback-status info";

  try {
    const response = await fetch("/api/audio/playback/play", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        sound_name: soundName,
        repeat_count: repeatCount,
        pause_between: pauseBetween,
      }),
    });

    const data = await response.json();

    if (response.ok) {
      statusDiv.textContent = `✓ ${data.message}`;
      statusDiv.className = "playback-status success";
      renderStatusIndicator("status-playback-header", "ok", "Playing");

      // Clear status after 3 seconds
      setTimeout(() => {
        statusDiv.textContent = "";
        statusDiv.className = "playback-status";
        renderStatusIndicator(
          "status-playback-header",
          "ok",
          `${document.getElementById("sound-select").options.length} sounds available`,
        );
      }, 3000);
    } else {
      statusDiv.textContent = `✗ Error: ${data.detail || "Unknown error"}`;
      statusDiv.className = "playback-status error";
      renderStatusIndicator(
        "status-playback-header",
        "error",
        "Playback failed",
      );
    }
  } catch (error) {
    console.error("Failed to play sound:", error);
    statusDiv.textContent = `✗ Error: ${error.message}`;
    statusDiv.className = "playback-status error";
    renderStatusIndicator("status-playback-header", "error", "Request failed");
  } finally {
    playButton.disabled = false;
  }
}

// Load sounds on page load
document.addEventListener("DOMContentLoaded", () => {
  loadAvailableSounds();
});

// ===== Bird Detection Functions =====

// Track expanded channels for bird detections
const expandedBirdChannels = new Set();

async function updateBirdDetections() {
  console.log("Updating bird detections...");
  try {
    const response = await fetch("/api/diagnostics/bird/detections");
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    console.log("Bird detections data:", data);

    const detectionsDiv = document.getElementById("bird-detections");
    detectionsDiv.classList.remove("loading");

    // Determine aggregate status based on detections
    let aggregateStatus = "healthy";
    if (!data.mqtt_connected) {
      aggregateStatus = "degraded";
    }

    renderStatusIndicator("status-bird-detections-header", aggregateStatus);

    let html = "";

    // MQTT connection warning
    if (!data.mqtt_connected) {
      html += `<div class="mqtt-warning">⚠️ MQTT not connected - detections may not be received</div>`;
    }

    // Summary cards (2x2 grid for 4 channels)
    html += '<div class="detection-summary-grid">';
    for (const channelId of ["1", "2", "3", "4"]) {
      const detection = data.summary[channelId];
      const isExpanded = expandedBirdChannels.has(channelId);

      let statusClass = "gray";
      let timeAgo = "No detections";
      let statusIcon = "⏳";
      let detectionCount = 0;

      if (detection && detection.timestamp) {
        const detectionTime = parseTimestamp(detection.timestamp);
        const now = new Date();
        const diffMs = now - detectionTime;
        const diffMinutes = Math.floor(diffMs / 60000);

        if (diffMinutes < 5) {
          statusClass = "green";
          statusIcon = "🟢";
        } else if (diffMinutes < 30) {
          statusClass = "yellow";
          statusIcon = "🟡";
        } else {
          statusClass = "gray";
          statusIcon = "⚪";
        }

        timeAgo = formatTimeAgo(detectionTime);
        detectionCount = detection.detections ? detection.detections.length : 0;
      }

      html += `
        <div class="detection-card ${statusClass} ${isExpanded ? "expanded" : ""}" 
             onclick="toggleBirdChannelHistory('${channelId}')" 
             data-channel="${channelId}">
          <div class="detection-card-header">
            <span class="channel-icon">🐦</span>
            <span class="channel-name">Channel ${channelId}</span>
            <span class="expand-icon">${isExpanded ? "▼" : "▶"}</span>
          </div>
          <div class="detection-card-status">
            <span class="status-icon">${statusIcon}</span>
            <span class="time-ago">${timeAgo}</span>
          </div>
          ${
            detectionCount > 0
              ? `<div class="detection-card-extra">${detectionCount} species</div>`
              : ""
          }
        </div>
      `;
    }
    html += "</div>";

    // Expandable history tables for each channel
    for (const channelId of ["1", "2", "3", "4"]) {
      const isExpanded = expandedBirdChannels.has(channelId);
      if (isExpanded) {
        const channelHistory = data.history.filter(
          (d) => d.channel_id === channelId,
        );
        const last10 = channelHistory.slice(0, 10);

        html += `
          <div class="channel-history" id="bird-history-${channelId}">
            <h4>🐦 Channel ${channelId} - Recent Bird Detections</h4>
            ${
              last10.length > 0
                ? `
              <table class="detection-table">
                <thead>
                  <tr>
                    <th>⏱️ Time</th>
                    <th>Species</th>
                    <th>Confidence</th>
                    <th>Event ID</th>
                    <th>Audio Clip</th>
                  </tr>
                </thead>
                <tbody>
                  ${last10
                    .map((d) => {
                      const time = formatTimestamp(d.timestamp);
                      const species = d.detections
                        ? d.detections
                            .map((det) => det.species_common)
                            .join(", ")
                        : "-";
                      // Show confidence range if multiple detections, else single confidence
                      let confidence = "-";
                      if (d.detections && d.detections.length > 0) {
                        if (d.detections.length === 1) {
                          confidence = `${(d.detections[0].confidence * 100).toFixed(1)}%`;
                        } else {
                          const confidences = d.detections.map(
                            (det) => det.confidence * 100,
                          );
                          const minConf = Math.min(...confidences);
                          const maxConf = Math.max(...confidences);
                          confidence = `${minConf.toFixed(1)}-${maxConf.toFixed(1)}%`;
                        }
                      }

                      // Create playback button if audio clip exists
                      let audioButton = "-";
                      let downloadButton = "";
                      if (d.clip_path) {
                        // Only pass the filename, not the full path, to match crow analysis
                        const audioClipName = d.clip_path.split("/").pop();
                        const audioUrl = `/api/audio/clips/${d.channel_id}/${audioClipName}`;
                        audioButton = `<button class="play-audio-btn" onclick="playAudioClip('${d.channel_id}', '${audioClipName}')" title="Play audio clip">🔊</button>`;
                        downloadButton = `<a href="${audioUrl}" download class="download-audio-btn" title="Download audio clip">⬇️</a>`;
                      }
                      const eventId = d.event_id || "-";
                      return `
                        <tr>
                          <td>${time}</td>
                          <td>${species}</td>
                          <td>${confidence}</td>
                          <td class="event-id">${eventId}</td>
                          <td>${audioButton} ${downloadButton}</td>
                        </tr>
                      `;
                    })
                    .join("")}
                </tbody>
              </table>
            `
                : '<p class="placeholder">No bird detections recorded for this channel</p>'
            }
          </div>
        `;
      }
    }

    detectionsDiv.innerHTML = html;
  } catch (error) {
    console.error("Failed to update bird detections:", error);
    document.getElementById("bird-detections").innerHTML =
      '<p class="placeholder">Waiting for bird detections...</p>';
    renderStatusIndicator("status-bird-detections-header", "unknown");
  }
}

function toggleBirdChannelHistory(channelId) {
  if (expandedBirdChannels.has(channelId)) {
    expandedBirdChannels.delete(channelId);
  } else {
    expandedBirdChannels.add(channelId);
  }
  // Immediately refresh to show/hide the history
  updateBirdDetections();
}

// ===== Crow Analysis Functions =====

// Track expanded channels for crow analysis
const expandedCrowChannels = new Set();

async function updateCrowAnalysis() {
  console.log("Updating crow analysis...");
  try {
    const response = await fetch("/api/diagnostics/crow/detections");
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    console.log("Crow analysis data:", data);

    const analysisDiv = document.getElementById("crow-analysis");
    analysisDiv.classList.remove("loading");

    // Determine aggregate status based on analyses
    let aggregateStatus = "healthy";
    if (!data.mqtt_connected) {
      aggregateStatus = "degraded";
    }

    renderStatusIndicator("status-crow-analysis-header", aggregateStatus);

    let html = "";

    // MQTT connection warning
    if (!data.mqtt_connected) {
      html += `<div class="mqtt-warning">⚠️ MQTT not connected - analyses may not be received</div>`;
    }

    // Summary cards (2x2 grid for 4 channels)
    html += '<div class="detection-summary-grid">';
    for (const channelId of ["1", "2", "3", "4"]) {
      const analysis = data.summary[channelId];
      const isExpanded = expandedCrowChannels.has(channelId);

      let statusClass = "gray";
      let timeAgo = "No analyses";
      let statusIcon = "⏳";
      let analysisInfo = "";

      if (analysis && analysis.timestamp) {
        const analysisTime = parseTimestamp(analysis.timestamp);
        const now = new Date();
        const diffMs = now - analysisTime;
        const diffMinutes = Math.floor(diffMs / 60000);

        if (diffMinutes < 5) {
          statusClass = "green";
          statusIcon = "🟢";
        } else if (diffMinutes < 30) {
          statusClass = "yellow";
          statusIcon = "🟡";
        } else {
          statusClass = "gray";
          statusIcon = "⚪";
        }

        timeAgo = formatTimeAgo(analysisTime);
        if (analysis.detection) {
          const detection = analysis.detection;
          const callType = detection.call_type || "unknown";
          const callTypeLabel =
            callType.charAt(0).toUpperCase() +
            callType.slice(1).replace("_", " ");

          // Get icon for call type
          const behaviorIcons = {
            alert: "⚠️",
            begging: "🍴",
            soft_song: "🎵",
            rattle: "🔊",
            mob: "⚔️",
          };
          const icon = behaviorIcons[callType] || "🐦‍⬛";

          analysisInfo = `${icon} ${callTypeLabel}`;
        }
      }

      html += `
        <div class="detection-card ${statusClass} ${isExpanded ? "expanded" : ""}" 
             onclick="toggleCrowChannelHistory('${channelId}')" 
             data-channel="${channelId}">
          <div class="detection-card-header">
            <span class="channel-icon">🐦‍⬛</span>
            <span class="channel-name">Channel ${channelId}</span>
            <span class="expand-icon">${isExpanded ? "▼" : "▶"}</span>
          </div>
          <div class="detection-card-status">
            <span class="status-icon">${statusIcon}</span>
            <span class="time-ago">${timeAgo}</span>
          </div>
          ${
            analysisInfo
              ? `<div class="detection-card-extra">${analysisInfo}</div>`
              : ""
          }
        </div>
      `;
    }
    html += "</div>";

    // Expandable history tables for each channel
    for (const channelId of ["1", "2", "3", "4"]) {
      const isExpanded = expandedCrowChannels.has(channelId);
      if (isExpanded) {
        const channelHistory = data.history.filter(
          (d) => d.channel_id === channelId,
        );
        const last10 = channelHistory.slice(0, 10);

        html += `
          <div class="channel-history" id="crow-history-${channelId}">
            <h4>🐦‍⬛ Channel ${channelId} - Recent Crow Analyses</h4>
            ${
              last10.length > 0
                ? `
              <table class="detection-table crow-table">
                <thead>
                  <tr>
                    <th>⏱️ Time</th>
                    <th>Call Type</th>
                    <th>Behaviors</th>
                    <th>Quality</th>
                    <th>Source Event</th>
                    <th>Audio Clip</th>
                  </tr>
                </thead>
                <tbody>
                  ${last10
                    .map((d) => {
                      const time = formatTimestamp(d.timestamp);
                      const detection = d.detection || {};
                      const callType = detection.call_type || "-";
                      const qualityScore =
                        detection.quality_score !== undefined
                          ? (detection.quality_score * 100).toFixed(1) + "%"
                          : "-";
                      const audioClipPath = d.audio_clip_path || "";
                      const audioClipName = audioClipPath
                        ? audioClipPath.split("/").pop()
                        : "-";
                      const sourceEventId = d.source_event_id || "-";

                      // Format behaviors using the existing formatBehaviors function
                      const behaviors = detection.attributes || {};
                      const behaviorsDisplay = formatBehaviors(behaviors);

                      // Create playback and download buttons if audio clip exists
                      let audioButton = "-";
                      let downloadButton = "";
                      if (audioClipPath && audioClipName !== "-") {
                        const audioUrl = `/api/audio/clips/${d.channel_id}/${audioClipName}`;
                        audioButton = `<button class="play-audio-btn" onclick="playAudioClip('${d.channel_id}', '${audioClipName}')" title="Play audio clip">🔊</button>`;
                        downloadButton = `<a href="${audioUrl}" download class="download-audio-btn" title="Download audio clip">⬇️</a>`;
                      }

                      // Shorten source event ID for display (show last 12 chars)
                      const shortSourceId =
                        sourceEventId.length > 20
                          ? "..." + sourceEventId.slice(-20)
                          : sourceEventId;

                      return `
                        <tr>
                          <td>${time}</td>
                          <td><strong>${callType}</strong></td>
                          <td>${behaviorsDisplay}</td>
                          <td>${qualityScore}</td>
                          <td class="event-id" title="${sourceEventId}">${shortSourceId}</td>
                          <td>${audioButton} ${downloadButton}</td>
                        </tr>
                      `;
                    })
                    .join("")}
                </tbody>
              </table>
            `
                : '<p class="placeholder">No crow analyses recorded for this channel</p>'
            }
          </div>
        `;
      }
    }

    analysisDiv.innerHTML = html;
  } catch (error) {
    console.error("Failed to update crow analysis:", error);
    document.getElementById("crow-analysis").innerHTML =
      '<p class="placeholder">Waiting for crow analysis...</p>';
    renderStatusIndicator("status-crow-analysis-header", "unknown");
  }
}

function toggleCrowChannelHistory(channelId) {
  if (expandedCrowChannels.has(channelId)) {
    expandedCrowChannels.delete(channelId);
  } else {
    expandedCrowChannels.add(channelId);
  }
  // Immediately refresh to show/hide the history
  updateCrowAnalysis();
}

/**
 * Format crow behaviors object into a readable string with icons and probabilities.
 * Shows behaviors with confidence > 10% threshold.
 */
function formatBehaviors(behaviors) {
  if (!behaviors) return "-";

  const behaviorLabels = {
    alert: "Alert",
    begging: "Begging",
    soft_song: "Soft Song",
    rattle: "Rattle",
    mob: "Mob",
  };

  const behaviorIcons = {
    alert: "⚠️",
    begging: "🍴",
    soft_song: "🎵",
    rattle: "🔊",
    mob: "⚔️",
  };

  const activeBehaviors = [];
  const THRESHOLD = 0.1; // Show behaviors with >10% confidence

  for (const [key, value] of Object.entries(behaviors)) {
    // Skip non-behavior attributes (like 'age')
    if (!behaviorLabels[key]) continue;

    // Check if value is a number and above threshold
    if (typeof value === "number" && value > THRESHOLD) {
      const icon = behaviorIcons[key] || "•";
      const label = behaviorLabels[key] || key;
      const percentage = (value * 100).toFixed(0);
      activeBehaviors.push(`${icon} ${label} (${percentage}%)`);
    }
  }

  return activeBehaviors.length > 0
    ? activeBehaviors.join(", ")
    : "Low confidence";
}

/**
 * Format quality value into a readable string
 */
function formatQuality(quality) {
  switch (quality) {
    case 1:
      return "Poor";
    case 2:
      return "Good";
    case 3:
      return "Excellent";
    default:
      return "-";
  }
}

/**
 * Play an audio clip from the audio motion detection
 * @param {string} channelId - The channel ID (1-4)
 * @param {string} filename - The audio clip filename
 */
function playAudioClip(channelId, filename) {
  const audioUrl = `/api/audio/clips/${channelId}/${filename}`;

  // Create an audio element and play it
  const audio = new Audio(audioUrl);
  audio.play().catch((error) => {
    console.error("Failed to play audio clip:", error);
    alert(`Failed to play audio clip: ${error.message}`);
  });
}

// ===== Theme Switching Functions =====

/**
 * Initialize theme from localStorage or use default
 */
function initializeTheme() {
  const savedTheme = localStorage.getItem("orpheus-theme") || "default";
  applyTheme(savedTheme);

  // Set the select dropdown to match
  const themeSelect = document.getElementById("theme-select");
  if (themeSelect) {
    themeSelect.value = savedTheme;
  }
}

/**
 * Change the active theme
 * @param {string} theme - Theme name: "default", "legacy", or "universal"
 */
function changeTheme(theme) {
  applyTheme(theme);
  localStorage.setItem("orpheus-theme", theme);
  console.log(`Theme changed to: ${theme}`);
}

/**
 * Apply theme to the document body
 * @param {string} theme - Theme name to apply
 */
function applyTheme(theme) {
  const body = document.body;

  // Remove all theme attributes
  body.removeAttribute("data-theme");

  // Apply new theme if not default
  if (theme === "legacy") {
    body.setAttribute("data-theme", "legacy");
  } else if (theme === "universal") {
    body.setAttribute("data-theme", "universal");
  }
  // "default" theme uses :root CSS variables, no data-theme attribute needed
}

// ===== Log Viewer Modal Functions =====

let logStreamReader = null;

async function openLogModal(serviceName) {
  const modal = document.getElementById("log-modal");
  const title = document.getElementById("log-modal-title");
  const content = document.getElementById("log-content");

  title.textContent = `Logs for ${serviceName}`;
  content.textContent = "Connecting to log stream...";
  modal.style.display = "flex";

  try {
    const response = await fetch(`/api/services/${serviceName}/logs/tail`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    content.textContent = ""; // Clear the connecting message
    logStreamReader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { value, done } = await logStreamReader.read();
      if (done) {
        content.textContent += "\n--- Log stream ended ---";
        break;
      }
      const chunk = decoder.decode(value, { stream: true });
      content.textContent += chunk;
      // Auto-scroll to the bottom
      content.scrollTop = content.scrollHeight;
    }
  } catch (error) {
    content.textContent = `--- Error connecting to log stream ---\n${error.message}`;
    console.error("Log streaming error:", error);
  } finally {
    logStreamReader = null;
  }
}

function closeLogModal() {
  const modal = document.getElementById("log-modal");
  modal.style.display = "none";

  if (logStreamReader) {
    logStreamReader
      .cancel("Modal closed by user")
      .catch((e) => console.error("Error cancelling log stream:", e));
    logStreamReader = null;
  }
}

/**
 * Update the snapshot and timelapse status display with file listings.
 * Preserves expanded file list state across refreshes.
 */
async function updateSnapshotTimelapseStatus() {
  const container = document.getElementById("snapshot-timelapse-status");
  if (!container) return;

  // Save expanded state before refresh
  const expandedSnapshots = new Set();
  const expandedTimelapses = new Set();
  document.querySelectorAll('[id^="snapshot-list-"]').forEach((el) => {
    if (el.style.display === "block") {
      const cameraName = el.id.replace("snapshot-list-", "");
      expandedSnapshots.add(cameraName);
    }
  });
  document.querySelectorAll('[id^="timelapse-list-"]').forEach((el) => {
    if (el.style.display === "block") {
      const cameraName = el.id.replace("timelapse-list-", "");
      expandedTimelapses.add(cameraName);
    }
  });

  try {
    const response = await fetch("/api/diagnostics/video/snapshots/status");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();

    if (data.error) {
      container.innerHTML = `<p class="error">❌ ${data.error}</p>`;
      container.classList.remove("loading");
      renderStatusIndicator("status-snapshot-header", "critical");
      return;
    }

    // Filter cameras that have snapshot or timelapse config
    const configuredCameras = data.cameras.filter(
      (cam) => cam.snapshots_configured || cam.timelapses_configured,
    );

    if (configuredCameras.length === 0) {
      container.innerHTML = `<p class="placeholder">No cameras configured for snapshots or timelapses.</p>`;
      container.classList.remove("loading");
      renderStatusIndicator("status-snapshot-header", "unknown", "No config");
      return;
    }

    // Build the status display with file listings
    let html = '<div class="snapshot-status-grid">';

    for (const cam of configuredCameras) {
      const statusClass = cam.enabled ? "healthy" : "disabled";
      const statusIcon = cam.enabled ? "📷" : "⏸️";

      html += `
        <div class="snapshot-card ${statusClass}">
          <div class="snapshot-card-header">
            ${statusIcon} ${cam.camera_name}
            ${!cam.enabled ? '<span class="badge disabled">Disabled</span>' : ""}
          </div>
          <div class="snapshot-card-content">`;

      // Snapshot info with file listing toggle
      if (cam.snapshots_configured) {
        const lastSnapshot = cam.last_snapshot
          ? formatLocalTime(cam.last_snapshot)
          : "No snapshots yet";
        html += `
          <div class="snapshot-info">
            <div class="info-header">
              <strong>📸 Snapshots</strong>
              ${cam.snapshot_count_today > 0 ? `<button class="btn-small" onclick="toggleSnapshotList('${cam.camera_name}')">View Files</button>` : ""}
            </div>
            <div>Interval: ${cam.snapshot_config.interval}</div>
            <div>Today: ${cam.snapshot_count_today} snapshots</div>
            <div>Last: ${lastSnapshot}</div>
            <div id="snapshot-list-${cam.camera_name}" class="file-list-container" style="display:none;">
              <div class="loading-small">Loading...</div>
            </div>
          </div>`;
      }

      // Timelapse info with file listing toggle
      if (cam.timelapses_configured && cam.timelapse_config) {
        const lastTimelapse = cam.last_timelapse
          ? formatLocalTime(cam.last_timelapse)
          : "No timelapses yet";

        html += `
          <div class="timelapse-info">
            <div class="info-header">
              <strong>🎬 Timelapses</strong>
              <button class="btn-small" onclick="toggleTimelapseList('${cam.camera_name}')">View Files</button>
            </div>
            <div>Schedules: ${cam.timelapse_config.length}</div>`;

        for (const tl of cam.timelapse_config) {
          const label = tl.label || "timelapse";
          html += `<div class="timelapse-schedule">• <strong>${label}</strong>: ${tl.start_time} (${tl.timezone}) - ${tl.lookback_window} lookback, ${tl.sampling_interval} interval @ ${tl.clip_duration}s each</div>`;
        }

        html += `
            <div>Today: ${cam.timelapse_count_today} timelapse${cam.timelapse_count_today !== 1 ? "s" : ""}</div>
            <div>Last: ${lastTimelapse}</div>
            <div id="timelapse-list-${cam.camera_name}" class="file-list-container" style="display:none;">
              <div class="loading-small">Loading...</div>
            </div>
          </div>`;
      }

      html += `
          </div>
        </div>`;
    }

    html += "</div>";
    container.innerHTML = html;
    container.classList.remove("loading");

    // Restore expanded state after DOM update
    for (const cameraName of expandedSnapshots) {
      const snapshotList = document.getElementById(
        `snapshot-list-${cameraName}`,
      );
      if (snapshotList) {
        snapshotList.style.display = "block";
        // Reload the list content
        loadSnapshotList(cameraName);
      }
    }
    for (const cameraName of expandedTimelapses) {
      const timelapseList = document.getElementById(
        `timelapse-list-${cameraName}`,
      );
      if (timelapseList) {
        timelapseList.style.display = "block";
        // Reload the list content
        loadTimelapseList(cameraName);
      }
    }

    // Set header status based on overall health
    const hasRecentActivity = configuredCameras.some(
      (cam) =>
        cam.enabled &&
        (cam.snapshot_count_today > 0 || cam.timelapse_count_today > 0),
    );
    renderStatusIndicator(
      "status-snapshot-header",
      hasRecentActivity ? "healthy" : "degraded",
      hasRecentActivity ? "Active" : "Waiting",
    );
  } catch (error) {
    console.error("Failed to fetch snapshot/timelapse status:", error);
    container.innerHTML = `<p class="error">❌ Failed to fetch status: ${error.message}</p>`;
    container.classList.remove("loading");
    renderStatusIndicator("status-snapshot-header", "critical");
  }
}

/**
 * Toggle snapshot file list visibility and load if needed.
 */
async function toggleSnapshotList(cameraName) {
  const container = document.getElementById(`snapshot-list-${cameraName}`);
  if (!container) return;

  if (container.style.display === "none") {
    container.style.display = "block";
    // Load snapshots if not already loaded
    if (container.querySelector(".loading-small")) {
      await loadSnapshotList(cameraName);
    }
  } else {
    container.style.display = "none";
  }
}

/**
 * Load snapshot file list for a camera.
 */
async function loadSnapshotList(cameraName) {
  const container = document.getElementById(`snapshot-list-${cameraName}`);
  if (!container) return;

  try {
    const response = await fetch(
      `/api/video/snapshots/${encodeURIComponent(cameraName)}?limit=20`,
    );
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();

    if (data.error) {
      container.innerHTML = `<p class="error">${data.error}</p>`;
      return;
    }

    if (!data.snapshots || data.snapshots.length === 0) {
      container.innerHTML = `<p class="placeholder">No snapshots found for today.</p>`;
      return;
    }

    let html =
      '<table class="file-table"><thead><tr><th>Time</th><th>Size</th><th>Actions</th></tr></thead><tbody>';
    for (const snap of data.snapshots) {
      const time = formatLocalTime(snap.timestamp_iso);
      html += `
        <tr>
          <td>${time}</td>
          <td>${snap.size_kb} KB</td>
          <td class="actions">
            <button class="btn-tiny" onclick="viewSnapshot('${snap.download_url}')" title="View">👁️</button>
            <a class="btn-tiny" href="${snap.download_url}" download="${snap.filename}" title="Download">⬇️</a>
          </td>
        </tr>`;
    }
    html += "</tbody></table>";
    container.innerHTML = html;
  } catch (error) {
    console.error("Failed to load snapshots:", error);
    container.innerHTML = `<p class="error">Failed to load: ${error.message}</p>`;
  }
}

/**
 * View a snapshot in a modal.
 */
function viewSnapshot(url) {
  // Create or reuse modal
  let modal = document.getElementById("snapshot-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "snapshot-modal";
    modal.className = "modal";
    modal.innerHTML = `
      <div class="modal-content snapshot-modal-content">
        <div class="modal-header">
          <h2>Snapshot Preview</h2>
          <span class="close-button" onclick="closeSnapshotModal()">&times;</span>
        </div>
        <div class="snapshot-preview">
          <img id="snapshot-preview-img" src="" alt="Snapshot preview">
        </div>
        <div class="modal-footer">
          <a id="snapshot-download-link" href="" download class="btn">Download</a>
        </div>
      </div>`;
    document.body.appendChild(modal);
  }

  const img = document.getElementById("snapshot-preview-img");
  const downloadLink = document.getElementById("snapshot-download-link");
  img.src = url;
  downloadLink.href = url;
  modal.style.display = "flex";
}

/**
 * Close snapshot preview modal.
 */
function closeSnapshotModal() {
  const modal = document.getElementById("snapshot-modal");
  if (modal) {
    modal.style.display = "none";
    // Clear the image to stop loading
    document.getElementById("snapshot-preview-img").src = "";
  }
}

/**
 * Toggle timelapse file list visibility and load if needed.
 */
async function toggleTimelapseList(cameraName) {
  const container = document.getElementById(`timelapse-list-${cameraName}`);
  if (!container) return;

  if (container.style.display === "none") {
    container.style.display = "block";
    // Load timelapses if not already loaded
    if (container.querySelector(".loading-small")) {
      await loadTimelapseList(cameraName);
    }
  } else {
    container.style.display = "none";
  }
}

/**
 * Load timelapse file list for a camera.
 * Groups timelapses by tier (24h, 1h, 30m, 10m) with newest first within each tier.
 */
async function loadTimelapseList(cameraName) {
  const container = document.getElementById(`timelapse-list-${cameraName}`);
  if (!container) return;

  try {
    const response = await fetch(
      `/api/video/timelapses/${encodeURIComponent(cameraName)}?limit=50`,
    );
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();

    if (data.error) {
      container.innerHTML = `<p class="error">${data.error}</p>`;
      return;
    }

    if (!data.timelapses || data.timelapses.length === 0) {
      container.innerHTML = `<p class="placeholder">No timelapses found.</p>`;
      return;
    }

    // Group timelapses by tier
    const tierGroups = {};
    const tierOrder = ["tl0", "tl1", "tl2", "tl3", "tl4"]; // 24h, 1h, 30m, 10m, 1m

    for (const tl of data.timelapses) {
      const tier = tl.tier || "legacy";
      if (!tierGroups[tier]) {
        tierGroups[tier] = [];
      }
      tierGroups[tier].push(tl);
    }

    // Build HTML grouped by tier
    let html = "";

    // Process tiers in order
    const allTiers = [...new Set([...tierOrder, ...Object.keys(tierGroups)])];
    for (const tier of allTiers) {
      if (!tierGroups[tier] || tierGroups[tier].length === 0) continue;

      const tierLabel = tierGroups[tier][0].tier_display || tier;
      const lookback = tierGroups[tier][0].lookback || "";

      html += `<div class="tier-group">
        <h4 class="tier-header">📹 ${tierLabel} Timelapses${lookback ? ` (${lookback})` : ""}</h4>
        <table class="file-table"><thead><tr><th>Label</th><th>Date</th><th>Time</th><th>Size</th><th>Actions</th></tr></thead><tbody>`;

      for (const tl of tierGroups[tier]) {
        const time = formatLocalTime(tl.timestamp_iso);
        const label = tl.label || "legacy";
        html += `
          <tr>
            <td><span class="timelapse-label">${label}</span></td>
            <td>${tl.date}</td>
            <td>${time}</td>
            <td>${tl.size_mb} MB</td>
            <td class="actions">
              <button class="btn-tiny" onclick="viewTimelapse('${tl.download_url}', '${label} - ${tl.date} ${time}')" title="Play">▶️</button>
              <a class="btn-tiny" href="${tl.download_url}" download="${tl.filename}" title="Download">⬇️</a>
            </td>
          </tr>`;
      }
      html += "</tbody></table></div>";
    }

    container.innerHTML = html;
  } catch (error) {
    console.error("Failed to load timelapses:", error);
    container.innerHTML = `<p class="error">Failed to load: ${error.message}</p>`;
  }
}

/**
 * View a timelapse video in a modal.
 * @param {string} url - The video URL to play
 * @param {string} title - Optional title to display in modal header
 */
function viewTimelapse(url, title) {
  // Create or reuse modal
  let modal = document.getElementById("timelapse-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "timelapse-modal";
    modal.className = "modal";
    modal.innerHTML = `
      <div class="modal-content timelapse-modal-content">
        <div class="modal-header">
          <h2 id="timelapse-modal-title">Timelapse Video</h2>
          <span class="close-button" onclick="closeTimelapseModal()">&times;</span>
        </div>
        <div class="timelapse-preview">
          <video id="timelapse-preview-video" controls autoplay>
            <source id="timelapse-preview-source" src="" type="video/mp4">
            Your browser does not support the video tag.
          </video>
        </div>
        <div class="modal-footer">
          <a id="timelapse-download-link" href="" download class="btn">Download</a>
        </div>
      </div>`;
    document.body.appendChild(modal);
  }

  const video = document.getElementById("timelapse-preview-video");
  const source = document.getElementById("timelapse-preview-source");
  const downloadLink = document.getElementById("timelapse-download-link");
  const modalTitle = document.getElementById("timelapse-modal-title");

  // Update title if provided
  if (modalTitle) {
    modalTitle.textContent = title || "Timelapse Video";
  }

  // Clear previous source before setting new one to prevent caching issues
  video.pause();
  source.src = "";
  video.load();

  // Set new source
  source.src = url;
  video.load();
  downloadLink.href = url;
  modal.style.display = "flex";
}

/**
 * Close timelapse preview modal.
 */
function closeTimelapseModal() {
  const modal = document.getElementById("timelapse-modal");
  if (modal) {
    modal.style.display = "none";
    // Stop the video
    const video = document.getElementById("timelapse-preview-video");
    if (video) {
      video.pause();
      video.currentTime = 0;
    }
  }
}
