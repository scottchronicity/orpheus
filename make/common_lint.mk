# Common lint / format targets for Python components using ruff.
#
# Requires common_python.mk to be included first (provides RUFF, SRC_DIR,
# TEST_DIR, check-deps).
#
# Provides targets: lint, format, check

.PHONY: lint format check

lint: check-deps
	@echo "Linting Python code with ruff..."
	@$(RUFF) check $(SRC_DIR) $(TEST_DIR)
	@echo "✓ Linting complete"

format: check-deps
	@echo "Formatting Python code with ruff..."
	@$(RUFF) format $(SRC_DIR) $(TEST_DIR)
	@$(RUFF) check --fix $(SRC_DIR) $(TEST_DIR)
	@echo "✓ Formatting complete"

check: check-deps
	@echo "Checking code formatting..."
	@$(RUFF) format --check $(SRC_DIR) $(TEST_DIR)
	@$(RUFF) check $(SRC_DIR) $(TEST_DIR)
	@echo "✓ All code properly formatted"
