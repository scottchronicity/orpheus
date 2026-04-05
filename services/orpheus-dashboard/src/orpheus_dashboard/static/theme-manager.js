/**
 * Orpheus Theme Manager
 * Handles theme switching and persistence across all pages
 */

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
  // Default theme doesn't need attribute
}

/**
 * Change theme and save to localStorage
 * @param {string} theme - Theme name to apply
 */
function changeTheme(theme) {
  applyTheme(theme);
  localStorage.setItem("orpheus-theme", theme);
  console.log(`Theme changed to: ${theme}`);
}

/**
 * Load saved theme from localStorage and apply it
 */
function loadSavedTheme() {
  const savedTheme = localStorage.getItem("orpheus-theme") || "default";
  applyTheme(savedTheme);

  // Update theme selector if it exists
  const themeSelect = document.getElementById("theme-select");
  if (themeSelect) {
    themeSelect.value = savedTheme;
  }

  console.log(`Loaded theme: ${savedTheme}`);
}

// Load theme on page load
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", loadSavedTheme);
} else {
  loadSavedTheme();
}
