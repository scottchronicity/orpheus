# Sourced, not run. The services that read or write the data root
# ($ORPHEUS_DATA_ROOT, /data/orpheus on a station): every agent, the UI and the
# storage sweep. scripts/check_guardrails.py holds the same set for the repo's
# unit files; these scripts check what systemd has loaded on a host.
# shellcheck disable=SC2034  # used by the sourcing script
DATA_ROOT_UNITS=(
    orpheus-agent-audio-events orpheus-agent-audio-motion orpheus-agent-audio-playback
    orpheus-agent-bird-detection orpheus-agent-crow-detection orpheus-agent-event-correlator
    orpheus-agent-video-motion orpheus-agent-video-snapshotter orpheus-agent-video-timelapser
    orpheus-ui orpheus-storage-sweep
)
