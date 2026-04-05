/**
 * Reusable Date Range Controls Module
 * Handles date range selection and formatting across all data visualization pages
 *
 * Timezone Handling:
 * - Backend stores all timestamps in UTC
 * - Frontend converts UTC timestamps to user's local timezone for display
 * - Date inputs are in local timezone (YYYY-MM-DD format)
 */

class DateRangeController {
  constructor() {
    this.listeners = [];
    this.userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    console.log("User timezone detected:", this.userTimezone);
    // Initialize with default 7-day range
    this.setDefaultDates(7);
  }

  /**
   * Initialize date controls for a page
   * @param {Object} options - Configuration options
   * @param {Function} options.onChange - Callback when dates change
   * @param {number} options.defaultDays - Default number of days (default: 7)
   */
  init(options = {}) {
    const { onChange, defaultDays = 7 } = options;

    // Always set default dates to ensure inputs are updated
    this.setDefaultDates(defaultDays);

    // Setup event listeners
    const applyButton = document.getElementById("apply-dates");
    const resetButton = document.getElementById("reset-dates");
    const reset1DayButton = document.getElementById("reset-1day");
    const reset30DaysButton = document.getElementById("reset-30days");
    const startInput = document.getElementById("start-date");
    const endInput = document.getElementById("end-date");

    if (applyButton) {
      applyButton.addEventListener("click", () => {
        console.log("Apply dates button clicked");
        this.startDate = startInput.value;
        this.endDate = endInput.value;
        console.log("New dates from inputs:", this.startDate, this.endDate);
        this.updateDisplay();
        console.log(
          "Calling onChange with dates:",
          this.startDate,
          this.endDate,
        );
        if (onChange) onChange(this.startDate, this.endDate);
      });
    }

    if (resetButton) {
      resetButton.addEventListener("click", () => {
        console.log("Reset to 7 days button clicked");
        this.setDefaultDates(7);
        this.updateDisplay();
        console.log(
          "Calling onChange with dates:",
          this.startDate,
          this.endDate,
        );
        if (onChange) onChange(this.startDate, this.endDate);
      });
    }

    if (reset1DayButton) {
      reset1DayButton.addEventListener("click", () => {
        console.log("Reset to 1 day button clicked");
        this.setDefaultDates(1);
        this.updateDisplay();
        console.log(
          "Calling onChange with dates:",
          this.startDate,
          this.endDate,
        );
        if (onChange) onChange(this.startDate, this.endDate);
      });
    }

    if (reset30DaysButton) {
      reset30DaysButton.addEventListener("click", () => {
        console.log("Reset to 30 days button clicked");
        this.setDefaultDates(30);
        this.updateDisplay();
        console.log(
          "Calling onChange with dates:",
          this.startDate,
          this.endDate,
        );
        if (onChange) onChange(this.startDate, this.endDate);
      });
    }

    // Set initial values in inputs
    if (startInput) startInput.value = this.startDate;
    if (endInput) endInput.value = this.endDate;

    // Update display
    this.updateDisplay();
  }

  /**
   * Set default date range (last N days)
   * @param {number} days - Number of days to look back
   */
  setDefaultDates(days = 7) {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);

    this.startDate = this.formatDate(start);
    this.endDate = this.formatDate(end);

    // Update inputs
    const startInput = document.getElementById("start-date");
    const endInput = document.getElementById("end-date");
    if (startInput) startInput.value = this.startDate;
    if (endInput) endInput.value = this.endDate;
  }

  /**
   * Format date as YYYY-MM-DD
   * @param {Date} date - Date object to format
   * @returns {string} Formatted date string
   */
  formatDate(date) {
    return date.toISOString().split("T")[0];
  }

  /**
   * Update all date range displays on the page
   */
  updateDisplay() {
    const start = new Date(this.startDate);
    const end = new Date(this.endDate);
    const diffDays = Math.round((end - start) / (1000 * 60 * 60 * 24));

    let displayText;
    if (diffDays === 0 || diffDays === 1) {
      displayText = "(Last 1 Day)";
    } else if (diffDays === 7) {
      displayText = "(Last 7 Days)";
    } else if (diffDays === 30) {
      displayText = "(Last 30 Days)";
    } else {
      displayText = `(${this.formatDisplayDate(start)} - ${this.formatDisplayDate(end)})`;
    }

    // Update all date range display elements
    document.querySelectorAll('[id^="date-range-display"]').forEach((el) => {
      el.textContent = displayText;
    });
  }

  /**
   * Format date for display (e.g., "Jan 1, 2026")
   * @param {Date} date - Date to format
   * @returns {string} Formatted display string
   */
  formatDisplayDate(date) {
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }

  /**
   * Get query parameters for API calls
   * @returns {string} Query string for API
   */
  getQueryParams() {
    console.log(
      "getQueryParams called, startDate:",
      this.startDate,
      "endDate:",
      this.endDate,
    );
    const params = `start_date=${this.startDate}&end_date=${this.endDate}`;
    console.log("Returning query params:", params);
    return params;
  }

  /**
   * Get start and end dates
   * @returns {Object} Object with startDate and endDate
   */
  getDates() {
    return {
      startDate: this.startDate,
      endDate: this.endDate,
    };
  }

  /**
   * Convert UTC ISO timestamp to local Date object
   * @param {string} utcTimestamp - ISO timestamp string from backend (UTC)
   * @returns {Date} Date object in user's local timezone
   */
  utcToLocal(utcTimestamp) {
    return new Date(utcTimestamp); // JavaScript Date automatically converts to local
  }

  /**
   * Format UTC timestamp for display in local timezone
   * @param {string} utcTimestamp - ISO timestamp string from backend (UTC)
   * @param {Object} options - Intl.DateTimeFormat options
   * @returns {string} Formatted date/time string in local timezone
   */
  formatUTCTimestamp(utcTimestamp, options = {}) {
    const date = this.utcToLocal(utcTimestamp);
    const defaultOptions = {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
      ...options,
    };
    return date.toLocaleString("en-US", defaultOptions);
  }

  /**
   * Get user's timezone name
   * @returns {string} Timezone name (e.g., "America/New_York")
   */
  getUserTimezone() {
    return this.userTimezone;
  }
}

// Create global instance
window.dateController = new DateRangeController();
