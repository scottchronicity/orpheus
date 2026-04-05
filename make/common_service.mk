# Common systemd service management targets for Orpheus components.
#
# Requires SERVICE_NAME to be set before including.
#
# Provides targets: install-service, uninstall-service,
#                   start, stop, restart, status, logs,
#                   service-start, service-stop, service-restart,
#                   service-status, service-logs, service-logs-static

.PHONY: install-service uninstall-service \
        start stop restart status logs \
        service-start service-stop service-restart service-status \
        service-logs service-logs-static

install-service:
	@echo "Installing $(SERVICE_NAME) systemd unit..."
	@sudo bash systemd/install-service.sh

uninstall-service:
	@echo "Uninstalling $(SERVICE_NAME) systemd unit..."
	@sudo bash systemd/uninstall-service.sh

start:
	@sudo systemctl start $(SERVICE_NAME)

stop:
	@sudo systemctl stop $(SERVICE_NAME)

restart:
	@sudo systemctl restart $(SERVICE_NAME)

status:
	@sudo systemctl status $(SERVICE_NAME)

logs:
	@sudo journalctl -u $(SERVICE_NAME) -f

# Backward-compatible aliases
service-start: start
service-stop: stop
service-restart: restart
service-status: status
service-logs: logs

service-logs-static:
	@sudo journalctl -u $(SERVICE_NAME) -n 100 --no-pager
