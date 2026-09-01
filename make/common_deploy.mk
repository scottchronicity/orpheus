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

# The orpheus-common reinstall below runs WITH dependency resolution on
# purpose: pip always rebuilds a local-directory install (force-reinstall
# adds nothing), and suppressing resolution (--no-deps) starves long-lived
# agent venvs of any NEW platform dependency — invisibly, because the
# platform's lazy imports keep the import smoke green and the gap only
# surfaces as a runtime failure (e.g. at bus connect). Satisfied
# pins are left alone (no --upgrade); only missing deps are installed.
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
	@if [ -x "$(DEPLOY_ROOT)/venv/bin/python" ]; then \
		if [ -d "/opt/orpheus/platform/orpheus-common" ]; then \
			echo "  Reinstalling orpheus-common into venv..."; \
			sudo $(DEPLOY_ROOT)/venv/bin/python -m pip install --no-cache-dir \
				/opt/orpheus/platform/orpheus-common -q || \
				echo "  ⚠️  orpheus-common reinstall FAILED — agent may run stale code"; \
		fi; \
		sudo $(DEPLOY_ROOT)/venv/bin/python -m pip install $(DEPLOY_ROOT) -q || \
			echo "  ⚠️  agent package install reported an issue"; \
	fi
	@sudo chown -R orpheus:orpheus $(DEPLOY_ROOT)
	@echo "✓ Deployed to $(DEPLOY_ROOT)"
