/**
 * Navigation functionality for Orpheus Dashboard
 * Handles mobile hamburger menu toggle
 */

function toggleNav() {
  const navMenu = document.getElementById("navMenu");
  const navToggle = document.querySelector(".nav-toggle");

  navMenu.classList.toggle("active");
  navToggle.classList.toggle("active");
}

// Close nav menu when clicking outside on mobile
document.addEventListener("click", (event) => {
  const navMenu = document.getElementById("navMenu");
  const navToggle = document.querySelector(".nav-toggle");
  const isClickInsideNav = event.target.closest(".top-nav");

  if (!isClickInsideNav && navMenu.classList.contains("active")) {
    navMenu.classList.remove("active");
    navToggle.classList.remove("active");
  }
});

// Display user's timezone
function updateTimezoneDisplay() {
  const timezoneSpan = document.getElementById("timezone-name");
  if (timezoneSpan) {
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const offset = new Date().toLocaleTimeString("en-US", {
        timeZoneName: "short",
      });
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

// Update timestamp
function updateTimestamp() {
  const lastUpdate = document.getElementById("lastUpdate");
  if (lastUpdate) {
    lastUpdate.textContent = new Date().toLocaleString();
  }
}

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  updateTimezoneDisplay();
  updateTimestamp();
});
