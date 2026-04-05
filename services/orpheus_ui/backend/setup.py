"""Setup script for orpheus-ui package."""

from setuptools import find_packages, setup

setup(
    name="orpheus-ui",
    version="0.1.0",
    description="Modern React/FastAPI UI for Orpheus Wildlife Monitoring",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9.5",
    include_package_data=True,
    package_data={
        "orpheus_ui": ["static/*", "static/**/*"],
    },
)
