# CI Workflows Guide

> For workflow structure and what to edit when adding a component, see
> [13 — CI/CD](agent-instructions/13-ci-cd.md), which is canonical for both. This
> page covers branch protection and the `ci-complete` gate.

This document describes the CI/CD workflows for the Orpheus project, with a focus on the path filtering system used to optimize test execution.

## Overview

The Orpheus project uses GitHub Actions for continuous integration. The main workflow file is `.github/workflows/pr-tests.yml`, which runs automated tests on all pull requests and pushes to the `main` branch.

## Path Filtering System

The workflow uses `dorny/paths-filter@v4` to skip test jobs for components a PR
did not touch. It is not as selective as that sounds: only `guardrails` is
ungated — `test-shared-make` gates on `makefile-includes`, `test-bash` on
`shell-scripts` and `docs-build` on `docs`, so all three can be skipped —
and a change to `platform/orpheus-common`, to a workflow, or to root config fans
out to every dependent job. See Special Cases below.

### How It Works

1. **Detection Phase**: The `changes` job runs first and detects which paths have changed in the PR
2. **Conditional Execution**: Each test job checks if its component or dependencies have changed
3. **Skipped Jobs**: Jobs for unchanged components are skipped (not failed), keeping PR status clean

### Path Filter Rules

| Component | Path | Triggers When... |
| ----------- | ------ | ------------------ |
| `common` | `platform/orpheus-common/**` | Any file in orpheus-common changes |

> This table is a partial copy and drifts. The filter list lives in the `changes`
> job's `filters:` block in `.github/workflows/pr-tests.yml` — read it there. Two
> that are not obvious: `event-correlator` also matches `tests/bdd/**`, and
> `shell-scripts` also matches the root `Makefile`.
| `ui` | `services/orpheus_ui/**` | Any file in orpheus_ui changes |
| `audio-motion` | `agents/orpheus-agent-audio-motion/**` | Any file in audio-motion agent changes |
| `audio-playback` | `agents/orpheus-agent-audio-playback/**` | Any file in audio-playback agent changes |
| `video-motion` | `agents/orpheus-agent-video-motion/**` | Any file in video-motion agent changes |
| `bird-detection` | `agents/orpheus-agent-bird-detection/**` | Any file in bird-detection agent changes |
| `crow-detection` | `agents/orpheus-agent-crow-detection/**` | Any file in crow-detection agent changes |
| `workflow` | `.github/workflows/**` | Any workflow file changes |
| `root-config` | `pyproject.toml`, `requirements*.txt` | Root configuration changes |

### Dependency Logic

Each test job uses conditional logic to determine if it should run:

```yaml
if: |
  needs.changes.outputs.common == 'true' ||
  needs.changes.outputs.your-component == 'true' ||
  needs.changes.outputs.workflow == 'true' ||
  needs.changes.outputs.root-config == 'true'
```

This means a test job runs if:

- **Its own component changed**, OR
- **orpheus-common changed** (all components depend on it), OR
- **Workflow files changed** (ensure CI changes don't break tests), OR
- **Root config files changed** (may affect all components)

### Special Cases

#### orpheus-common Changes

When `platform/orpheus-common/**` changes, **ALL component tests run** because every agent and service depends on the shared library. This is critical for catching breaking changes early.

#### Workflow Changes

When `.github/workflows/**` changes, **ALL tests run** to verify that workflow modifications don't break the CI system.

#### Root Configuration Changes

When `pyproject.toml` or `requirements*.txt` at the repository root change, **ALL tests run** because these files may affect dependency resolution for all components.

## Workflow Structure

### Job Execution Order

```bash
changes (detect paths)
    ↓
check-dependencies (if any component changed)
    ↓
test-* jobs (run in parallel if their conditions are met)
    ↓
ci-complete (gate job - always runs, checks no failures)
```

### Gate Job for Branch Protection

The workflow includes a special `ci-complete` gate job that:

- **Always runs** regardless of path filters
- Waits for all other jobs to complete
- Checks that no jobs failed (but allows skipped jobs)
- **Should be the only required job in branch protection settings**

This solves a critical issue: when jobs are skipped due to path filters, GitHub sees them as "required but not run" which blocks PR merges. By making only the gate job required in branch protection, skipped jobs won't block merges while still ensuring no actual failures occurred.

### Adding a New Component to CI

When you create a new agent, service, or platform component, follow these steps to add it to the CI workflow:

### Step 1: Prepare Your Component

Ensure your component has the required Makefile targets:

```makefile
install:
    # Create venv, install dependencies including orpheus-common
    python3 -m venv venv
    ./venv/bin/pip install -e ../platform/orpheus-common
    ./venv/bin/pip install -r requirements.txt

lint:
    # Run ruff linting
    ./venv/bin/ruff check .

coverage:
    # Run tests with coverage reporting
    ./venv/bin/pytest --cov=your_component --cov-report=term-missing --cov-report=xml
```

### Step 2: Add Path Filter

Edit `.github/workflows/pr-tests.yml` and add your component to the `changes` job:

```yaml
jobs:
  changes:
    name: Detect Changed Paths
    runs-on: ubuntu-latest
    outputs:
      # ... existing outputs ...
      your-component: ${{ steps.filter.outputs.your-component }}  # ADD THIS
    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Check changed paths
        uses: dorny/paths-filter@v4
        id: filter
        with:
          filters: |
            # ... existing filters ...
            your-component:  # ADD THIS
              - 'path/to/your-component/**'
```

### Step 3: Add Test Job

Add a new test job following the existing pattern:

```yaml
test-your-component:
  name: Test your-component
  runs-on: ubuntu-latest
  needs: [changes, check-dependencies]
  # Run if component or common changed, or workflow/root config changed
  if: |
    needs.changes.outputs.common == 'true' ||
    needs.changes.outputs.your-component == 'true' ||
    needs.changes.outputs.workflow == 'true' ||
    needs.changes.outputs.root-config == 'true'

  steps:
    - name: Checkout code
      uses: actions/checkout@v6

    - name: Set up Python ${{ env.PYTHON_VERSION }}
      uses: actions/setup-python@v6
      with:
        python-version: ${{ env.PYTHON_VERSION }}
        cache: 'pip'
        cache-dependency-path: |
          platform/orpheus-common/requirements.txt
          path/to/your-component/requirements.txt

    # Add any system dependencies your component needs
    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y your-system-packages

    - name: Install dependencies
      run: make install-your-component

    - name: Run linting
      run: make lint-your-component

    - name: Run tests with coverage
      env:
        COVERAGE_THRESHOLD: '70'  # Adjust as needed
      run: make coverage-your-component COV_REPORTS="${{ env.COV_REPORTS }}"

    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v5
      with:
        files: path/to/your-component/coverage.xml
        flags: your-component
        fail_ci_if_error: false
        token: ${{ secrets.CODECOV_TOKEN || '' }}

    - name: Upload coverage report
      uses: actions/upload-artifact@v6
      with:
        name: coverage-your-component
        path: path/to/your-component/coverage.xml
```

### Step 4: Add Coverage Threshold

Add an environment variable for your component's coverage threshold at the top of the workflow:

```yaml
env:
  # ... existing thresholds ...
  COVERAGE_THRESHOLD_YOUR_COMPONENT: '70'
```

### Step 5: Update Gate Job

Add your new component to the `ci-complete` gate job's `needs` list:

```yaml
ci-complete:
  name: CI Complete
  runs-on: ubuntu-latest
  needs:
    - changes
    - check-dependencies
    - test-orpheus-common
    # ... other test jobs ...
    - test-your-component  # ADD THIS
  if: always()
  # ... rest of job ...
```

### Step 6: Update Root Makefile (Optional)

If your component should be included in root-level targets, update the repository root `Makefile`:

```makefile
install-your-component:
    cd path/to/your-component && make install

test-your-component:
    cd path/to/your-component && make test

lint-your-component:
    cd path/to/your-component && make lint

coverage-your-component:
    cd path/to/your-component && make coverage
```

### Step 7: Test Your Changes

1. Create a PR with your workflow changes
2. Make a change to your component to trigger its test job
3. Verify that:
   - The `changes` job detects your component's changes
   - Your component's test job runs successfully
   - Other test jobs are skipped (if only your component changed)
   - Skipped jobs show as "Skipped" not "Failed" in the PR checks

## Related Documentation

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [dorny/paths-filter Action](https://github.com/dorny/paths-filter)
- [Repository README - CI/CD Section](https://github.com/scottchronicity/orpheus/blob/main/README.md#cicd)
- [CONTRIBUTING.md - PR Guidelines](contributing.md)
- [TESTING.md - Testing Standards](https://github.com/scottchronicity/orpheus/blob/main/docs/TESTING.md)

## History

- **2026-01-08**: Added path filtering system to optimize CI execution time ([Issue #84](https://github.com/scottchronicity/orpheus/issues/84))
- Initial workflow created with basic test jobs for all components
