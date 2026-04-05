# Common deploy logic for Orpheus agents and services.
#
# Include this from a component Makefile after setting these variables:
#
#   SERVICE_NAME     (required)  e.g. orpheus-agent-audio-motion
#   DEPLOY_ROOT      (required)  e.g. /opt/orpheus/agents/$(SERVICE_NAME)
#   DEPLOY_SRC_DIR   (optional)  local source dir to rsync, default: src/
#   DEPLOY_EXTRA_FILES (optional) files to copy alongside source, default: pyproject.toml requirements.txt
#
# Provides targets:  deploy, _deploy-check
#
# Usage in the component Makefile:
#
#   include ../../make/common_deploy.mk
#
#   update:
#       git pull
#       $(MAKE) install
#       $(MAKE) deploy
#       $(MAKE) restart

# -- Defaults -----------------------------------------------------------------

DEPLOY_SRC_DIR   ?= src/
DEPLOY_EXTRA_FILES ?= pyproject.toml requirements.txt

# -- Targets ------------------------------------------------------------------

.PHONY: deploy _deploy-check

_deploy-check:
	@if [ ! -d "$(DEPLOY_ROOT)" ]; then \
		echo "❌ $(DEPLOY_ROOT) not found. Run 'make install-service' first."; \
		exit 1; \
	fi

deploy: _deploy-check
	@echo "Deploying $(SERVICE_NAME) to $(DEPLOY_ROOT)..."
	@sudo rsync -a --delete \
		--exclude venv \
		--exclude __pycache__ \
		--exclude '*.pyc' \
		$(DEPLOY_SRC_DIR) $(DEPLOY_ROOT)/src/
	@for f in $(DEPLOY_EXTRA_FILES); do \
		if [ -f "$$f" ]; then \
			sudo cp "$$f" $(DEPLOY_ROOT)/; \
		fi; \
	done
	@if [ -x "$(DEPLOY_ROOT)/venv/bin/pip" ]; then \
		if [ -d "/opt/orpheus/platform/orpheus-common" ]; then \
			echo "  Reinstalling orpheus-common into venv..."; \
			sudo $(DEPLOY_ROOT)/venv/bin/pip install /opt/orpheus/platform/orpheus-common -q 2>/dev/null || true; \
		fi; \
		sudo $(DEPLOY_ROOT)/venv/bin/pip install $(DEPLOY_ROOT) -q 2>/dev/null || true; \
	fi
	@sudo chown -R orpheus:orpheus $(DEPLOY_ROOT)
	@echo "✓ Deployed to $(DEPLOY_ROOT)"
