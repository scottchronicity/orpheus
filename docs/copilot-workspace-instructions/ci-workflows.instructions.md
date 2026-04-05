# GitHub Actions CI Workflow Instructions

**For AI Coding Agents: When modifying or extending the CI workflow**

## Quick Reference

- **Main workflow file**: `.github/workflows/pr-tests.yml`
- **Human documentation**: `docs/CI_WORKFLOWS.md`
- **System**: Path filtering with `dorny/paths-filter@v3`

## Core Principles

1. **Path filtering is mandatory**: Every component test job MUST use path filters to optimize CI costs
2. **orpheus-common triggers all**: Changes to `platform/orpheus-common/**` MUST trigger all component tests
3. **Workflow changes trigger all**: Changes to `.github/workflows/**` MUST trigger all tests
4. **Root config triggers all**: Changes to `pyproject.toml` or `requirements*.txt` MUST trigger all tests
5. **Gate job for branch protection**: The `ci-complete` job is the ONLY job that should be required in branch protection settings

## When Adding a New Component Test Job

### Checklist

- [ ] Component has `Makefile` with `install`, `lint`, and `coverage` targets
- [ ] Added component to `changes` job outputs
- [ ] Added component path filter in `changes` job filters
- [ ] Created test job with proper `needs` dependency
- [ ] Added conditional `if` statement with all required triggers
- [ ] Set appropriate coverage threshold environment variable
- [ ] Added Codecov upload step
- [ ] Added coverage artifact upload step
- [ ] Added component to `ci-complete` gate job's `needs` list
- [ ] Updated root `Makefile` with component-specific targets
- [ ] Tested by making a change to the component

### Template for New Test Job

```yaml
# 1. Add to 'changes' job outputs:
outputs:
  # ... existing ...
  your-component: ${{ steps.filter.outputs.your-component }}

# 2. Add to 'changes' job filters:
filters: |
  # ... existing ...
  your-component:
    - 'path/to/your-component/**'

# 3. Add test job:
test-your-component:
  name: Test your-component
  runs-on: ubuntu-latest
  needs: [changes, check-dependencies]
  # CRITICAL: Must check common, workflow, and root-config
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

    # Add system dependencies if needed
    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y required-packages

    - name: Install dependencies
      run: make install-your-component

    - name: Run linting
      run: make lint-your-component

    - name: Run tests with coverage
      env:
        COVERAGE_THRESHOLD: ${{ env.COVERAGE_THRESHOLD_YOUR_COMPONENT }}
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

## Critical Rules

### DO

✅ **Always include these four triggers** in component test jobs:
- `needs.changes.outputs.common == 'true'` (shared library dependency)
- `needs.changes.outputs.your-component == 'true'` (component itself changed)
- `needs.changes.outputs.workflow == 'true'` (CI changes need validation)
- `needs.changes.outputs.root-config == 'true'` (dependency changes may affect all)

✅ **Use specific path filters**: `component/**` matches all files in subdirectories

✅ **Update both workflow and documentation** when adding components

✅ **Test your changes** by creating a PR that modifies the new component

### DO NOT

❌ **Never forget the orpheus-common trigger**: All components depend on it, so all tests must run when it changes

❌ **Never use `&&` (AND) between triggers**: Use `||` (OR) so any trigger runs the job

❌ **Never skip the workflow and root-config triggers**: These ensure CI integrity

❌ **Never add a test job without path filtering**: It wastes CI resources

## Path Filter Patterns

### Standard Component Patterns

```yaml
# Agent
agents/orpheus-agent-name/**

# Service
services/orpheus-service-name/**

# Platform
platform/orpheus-common/**
```

### Special Patterns

```yaml
# Workflow files (triggers all tests)
.github/workflows/**

# Root config files (triggers all tests)
pyproject.toml
requirements*.txt
```

## Conditional Logic Patterns

### For All Component Tests

```yaml
if: |
  needs.changes.outputs.common == 'true' ||
  needs.changes.outputs.component == 'true' ||
  needs.changes.outputs.workflow == 'true' ||
  needs.changes.outputs.root-config == 'true'
```

### For check-dependencies Job

```yaml
if: |
  needs.changes.outputs.common == 'true' ||
  needs.changes.outputs.dashboard == 'true' ||
  needs.changes.outputs.audio-motion == 'true' ||
  needs.changes.outputs.audio-playback == 'true' ||
  needs.changes.outputs.video-motion == 'true' ||
  needs.changes.outputs.bird-detection == 'true' ||
  needs.changes.outputs.crow-detection == 'true' ||
  needs.changes.outputs.workflow == 'true' ||
  needs.changes.outputs.root-config == 'true'
```

**Note**: When adding a new component, update the check-dependencies conditional to include it.

## Validation Steps

After modifying the workflow:

1. **Syntax validation**: Run `yamllint .github/workflows/pr-tests.yml`
2. **Test single component change**: Make a change to one component, verify only its test runs
3. **Test common change**: Make a change to orpheus-common, verify all tests run
4. **Test workflow change**: Make a change to the workflow file, verify all tests run
5. **Test root config change**: Make a change to requirements.txt, verify all tests run
6. **Verify skipped jobs**: Check that skipped jobs show "Skipped" not "Failed" in PR checks

## Debugging

### Path filter not working

1. Check `changes` job logs for detected paths
2. Verify glob pattern syntax: `/**` for subdirectories
3. Ensure output variable name matches filter name

### Test running when it shouldn't

1. Check if orpheus-common, workflow, or root config changed (expected behavior)
2. Verify path filter isn't too broad
3. Check conditional logic uses `||` not `&&`

### Test not running when it should

1. Verify path filter matches your component directory
2. Check conditional includes the component output variable
3. Ensure `needs` dependency includes `changes`

## Example: Real Implementation

See current implementation in `.github/workflows/pr-tests.yml`:

- `changes` job: Lines 25-66
- `check-dependencies` job: Lines 68-93
- Component test jobs: Lines 95-458

Each component follows the same pattern:
1. Depends on `[changes, check-dependencies]`
2. Conditional checks 4 triggers (common, component, workflow, root-config)
3. Standard steps: checkout, setup Python, install, lint, test, upload coverage

## Related Files

- `.github/workflows/pr-tests.yml` - Main workflow file
- `docs/CI_WORKFLOWS.md` - Detailed human documentation
- `README.md` - High-level CI overview
- `Makefile` - Root-level targets for all components
- `platform/orpheus-common/` - Shared library that triggers all tests
