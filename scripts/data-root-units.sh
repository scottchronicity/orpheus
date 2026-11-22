# Sourced, not run. The services that read or write the data root
# ($ORPHEUS_DATA_ROOT, /data/orpheus on a station): every agent, the UI and the
# storage sweep. scripts/check_guardrails.py holds the same set for the repo's
# unit files; these scripts check what systemd has loaded on a host.
# shellcheck disable=SC2034  # used by the sourcing script
#
# DATA_ROOT_SERVICES are the long-running ones: when the data drive drops out
# and comes back, the mount starts them again. The sweep is a timer's one-shot,
# so the timer starts it, not the mount.
DATA_ROOT_SERVICES=(
    orpheus-agent-audio-events orpheus-agent-audio-motion orpheus-agent-audio-playback
    orpheus-agent-bird-detection orpheus-agent-crow-detection orpheus-agent-event-correlator
    orpheus-agent-video-motion orpheus-agent-video-snapshotter orpheus-agent-video-timelapser
    orpheus-ui
)
DATA_ROOT_UNITS=("${DATA_ROOT_SERVICES[@]}" orpheus-storage-sweep)
