"""Setup script for orpheus-ui package."""

from setuptools import find_packages, setup

setup(
    name="orpheus-ui",
    # version omitted on purpose: dynamic, sourced from the VERSION file via
    # [tool.setuptools.dynamic] in pyproject.toml (the SSoT).
    description="Modern React/FastAPI UI for Orpheus Wildlife Monitoring",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9.5",
    include_package_data=True,
    package_data={
        "orpheus_ui": ["static/*", "static/**/*"],
    },
)
