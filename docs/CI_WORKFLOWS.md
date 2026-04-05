# CI Workflows Guide

This document describes the CI/CD workflows for the Orpheus project, with a focus on the path filtering system used to optimize test execution.

## Overview

The Orpheus project uses GitHub Actions for continuous integration. The main workflow file is `.github/workflows/pr-tests.yml`, which runs automated tests on all pull requests and pushes to the `main` branch.

## Path Filtering System

To optimize CI execution time and resource usage, the workflow uses **intelligent path filtering** via the `dorny/paths-filter@v3` action. This ensures that only tests for changed components are executed.

### How It Works

1. **Detection Phase**: The `changes` job runs first and detects which paths have changed in the PR
2. **Conditional Execution**: Each test job checks if its component or dependencies have changed
3. **Skipped Jobs**: Jobs for unchanged components are skipped (not failed), keeping PR status clean

### Path Filter Rules

| Component | Path | Triggers When... |
| ----------- | ------ | ------------------ |
| `common` | `platform/orpheus-common/**` | Any file in orpheus-common changes |
| `dashboard` | `services/orpheus-dashboard/**` | Any file in orpheus-dashboard changes |
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

### Job Definitions

1. **`changes`**: Detects changed paths using `dorny/paths-filter@v3`
   - Runs on: All PRs and pushes to main
   - Duration: ~5-10 seconds
   - Output: Boolean flags for each component

2. **`check-dependencies`**: Validates dependency version consistency
   - Runs on: Any component, workflow, or root config change
   - Duration: ~30-60 seconds
   - Purpose: Ensure all components use compatible dependency versions

3. **`test-orpheus-common`**: Tests the shared platform library
   - Runs on: common, workflow, or root config changes
   - Duration: ~1-2 minutes
   - Coverage threshold: 78%

4. **`test-orpheus-dashboard`**: Tests the web dashboard
   - Runs on: dashboard, common, workflow, or root config changes
   - Duration: ~1-2 minutes
   - Coverage threshold: 80%

5. **`test-orpheus-agent-*`**: Tests individual agents
   - Runs on: agent, common, workflow, or root config changes
   - Duration: Varies (bird/crow detection are slowest at ~3-5 minutes)
   - Coverage threshold: 70% (except audio-motion at 72%)

6. **`ci-complete`**: Gate job for branch protection
   - Runs on: Always (checks all other jobs)
   - Duration: ~5 seconds
   - Purpose: Allows skipped jobs while ensuring no failures occurred
   - **This is the only job that should be required in branch protection**

## Adding a New Component to CI

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
        uses: dorny/paths-filter@v3
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

## Best Practices

### For Component Developers

- **Always run tests locally first**: Use `make test` before pushing to avoid wasting CI minutes
- **Maintain coverage**: Keep coverage at or above the threshold (typically 70%)
- **Mock external dependencies**: Ensure tests don't require hardware, network, or external services
- **Test in isolation**: Components should not share state or files during testing

### For Workflow Maintainers

- **Keep path filters specific**: Use `/**` to match all files in a directory
- **Always include common trigger**: All component tests should trigger on `orpheus-common` changes
- **Always include workflow trigger**: All component tests should trigger on workflow file changes
- **Test workflow changes thoroughly**: Make a test PR that touches each component to verify filters work
- **Document new filters**: Update this file when adding new path filters

### For Code Reviewers

When reviewing PRs that modify `.github/workflows/pr-tests.yml`:

- [ ] Verify new components include all required conditionals (common, workflow, root-config)
- [ ] Check that path filters are accurate and specific
- [ ] Ensure coverage thresholds are set appropriately
- [ ] Confirm test job names are consistent with naming conventions
- [ ] Validate that dependencies are correctly listed in cache-dependency-path

## Troubleshooting

### Test Job Not Running When Expected

**Problem**: Made changes to a component but its test job didn't run.

**Solutions**:

1. Check that the path filter in the `changes` job matches your component's directory
2. Verify the conditional `if` statement includes the correct output variable
3. Ensure the `needs` dependency includes both `changes` and `check-dependencies`

### All Tests Running When Only One Component Changed

**Problem**: Changed a single component but all tests ran.

**Possible Causes**:

1. You changed `orpheus-common` (this is expected behavior)
2. You modified a workflow file (this is expected behavior)
3. You modified root config files like `pyproject.toml` (this is expected behavior)
4. Path filters are too broad (e.g., using `*` instead of `/**`)

### Tests Showing as Failed When They Should Be Skipped

**Problem**: Skipped tests appear as failed in PR checks.

**Solution**: This typically happens when the `if` condition is misconfigured. Ensure:

1. The condition uses `needs.changes.outputs.component == 'true'` format
2. Conditions are joined with `||` (OR) not `&&` (AND)
3. All required outputs are defined in the `changes` job

### Path Filter Not Detecting Changes

**Problem**: Made changes but the path filter output is 'false'.

**Debug Steps**:

1. Check the `changes` job logs to see what paths were detected
2. Verify your filter uses glob syntax correctly: `component/**` matches all files in subdirectories
3. Ensure there are no typos in the path
4. Confirm the `dorny/paths-filter` action version is `v3`

## Related Documentation

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [dorny/paths-filter Action](https://github.com/dorny/paths-filter)
- [Repository README - CI/CD Section](../README.md#cicd-workflows)
- [CONTRIBUTING.md - PR Guidelines](../CONTRIBUTING.md)
- [TESTING.md - Testing Standards](./TESTING.md)

## History

- **2026-01-08**: Added path filtering system to optimize CI execution time ([Issue #84](https://github.com/scottchronicity/orpheus/issues/84))
- Initial workflow created with basic test jobs for all components
