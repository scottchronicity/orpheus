#!/usr/bin/env bats
#
# The board sync writes to a public issue tracker. --dry-run is the rehearsal
# that makes merge day survivable, and it is only worth anything if it (a)
# writes nothing and (b) decides the same things the real run decides.
#
# Both are checked against a fake `gh` on PATH rather than by mocking inside
# Python: what matters is the commands that reach the GitHub CLI.

setup() {
    SCRIPT="${BATS_TEST_DIRNAME}/../../tools/scripts/sync_github_board.py"
    FAKE_BIN="${BATS_TEST_TMPDIR}/bin"
    CALL_LOG="${BATS_TEST_TMPDIR}/gh-calls.log"
    LEDGER="${BATS_TEST_TMPDIR}/backlog.json"
    mkdir -p "$FAKE_BIN"

    cat > "$LEDGER" <<'JSON'
{
  "labels": [
    {"name": "type: bug", "color": "d73a4a", "description": "a defect"},
    {"name": "roadmap", "color": "0e8a16", "description": "seeded"}
  ],
  "milestones": [
    {"title": "Existing Theme", "description": "already there"},
    {"title": "New Theme", "description": "not there yet"}
  ],
  "issues": [
    {"title": "Already filed", "body": "one", "labels": ["type: bug"],
     "milestone": "Existing Theme"},
    {"title": "Not yet filed", "body": "two", "labels": ["type: bug"],
     "milestone": "New Theme"},
    {"title": "Filed under an older name", "body": "three", "labels": [],
     "milestone": "New Theme", "previous_titles": ["The older name"]}
  ]
}
JSON

    # Fake gh: logs every invocation, answers the reads the script performs.
    cat > "${FAKE_BIN}/gh" <<'SH'
#!/usr/bin/env bash
echo "$*" >> "$CALL_LOG"
case "$1 $2" in
  "issue list")
    echo '[{"number":11,"title":"Already filed","body":"stale body","labels":[{"name":"type: bug"},{"name":"stale"}],"milestone":{"title":"Old Epic"},"state":"OPEN"},
          {"number":12,"title":"The older name","body":"x","labels":[],"milestone":null,"state":"CLOSED"}]'
    ;;
  "label list") echo '[{"name":"type: bug"}]' ;;
  "api repos/scottchronicity/orpheus/milestones"|"api "*) echo "Existing Theme" ;;
  "project list") echo '[]' ;;
  "issue create") echo "https://github.com/scottchronicity/orpheus/issues/99" ;;
  *) echo "" ;;
esac
exit 0
SH
    chmod +x "${FAKE_BIN}/gh"
    export CALL_LOG
    export PATH="${FAKE_BIN}:${PATH}"
}

# A write is any gh verb that changes the board. Reads are list/get only.
mutating_calls() {
    grep -cE '^(issue (create|edit)|label (create|edit)|project item-add|api repos/[^ ]*/milestones -f)' \
        "$CALL_LOG" || true
}

@test "dry-run issues no mutating gh command" {
    run python3 "$SCRIPT" "$LEDGER" --dry-run
    [ "$status" -eq 0 ]
    [ "$(mutating_calls)" -eq 0 ]
}

@test "dry-run still performs the reads it needs to decide" {
    run python3 "$SCRIPT" "$LEDGER" --dry-run
    grep -q '^issue list' "$CALL_LOG"
    grep -q '^label list' "$CALL_LOG"
}

@test "dry-run reports what it would do, not what it did" {
    run python3 "$SCRIPT" "$LEDGER" --dry-run
    [[ "$output" == *"nothing was changed"* ]]
    [[ "$output" == *"CREATE 'Not yet filed'"* ]]
    [[ "$output" == *"RENAME #12"* ]]
    [[ "$output" == *"MILESTONE create New Theme"* ]]
}

@test "dry-run names the label and milestone moves an edit performs" {
    run python3 "$SCRIPT" "$LEDGER" --dry-run
    # The reconciling push strips a label the ledger does not carry.
    [[ "$output" == *"-labels stale"* ]]
    [[ "$output" == *"milestone Old Epic -> Existing Theme"* ]]
}

@test "dry-run flags an edit that lands on a closed issue" {
    run python3 "$SCRIPT" "$LEDGER" --dry-run
    [[ "$output" == *"issue is CLOSED (edited, not reopened)"* ]]
}

@test "both modes decide the same set of actions" {
    run python3 "$SCRIPT" "$LEDGER" --dry-run
    dry_creates=$(grep -c "^     issue create" <<< "$output" || true)
    dry_summary=$(sed -n '/Actions that WOULD run/,$p' <<< "$output" \
        | grep -E '^     (issue|label|milestone|project)' | sort)

    : > "$CALL_LOG"
    run python3 "$SCRIPT" "$LEDGER"
    real_summary=$(sed -n '/Actions performed/,$p' <<< "$output" \
        | grep -E '^     (issue|label|milestone|project)' | sort)

    [ -n "$dry_summary" ]
    [ "$dry_summary" = "$real_summary" ]
}

@test "the real run does issue the writes the rehearsal described" {
    run python3 "$SCRIPT" "$LEDGER"
    [ "$status" -eq 0 ]
    [ "$(mutating_calls)" -gt 0 ]
    grep -q '^issue create' "$CALL_LOG"
    grep -q '^issue edit' "$CALL_LOG"
}

@test "no run closes an issue" {
    run python3 "$SCRIPT" "$LEDGER"
    run grep -cE 'issue (close|reopen)' "$CALL_LOG"
    [ "$output" -eq 0 ]
}

@test "an unreadable board aborts rather than filing everything twice" {
    cat > "${FAKE_BIN}/gh" <<'SH'
#!/usr/bin/env bash
echo "$*" >> "$CALL_LOG"
case "$1 $2" in
  "issue list") exit 1 ;;
  *) echo "" ;;
esac
exit 0
SH
    chmod +x "${FAKE_BIN}/gh"
    run python3 "$SCRIPT" "$LEDGER" --dry-run
    [ "$status" -ne 0 ]
    [[ "$output" == *"could not be read"* ]]
}
