"""Setup script for orpheus-dashboard package."""

from setuptools import setup, find_packages

setup(
    name="orpheus-dashboard",
    version="0.1.0",
    description="Wildlife Monitoring Status Interface",
    author="Orpheus Project",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    package_data={
        "orpheus_dashboard": ["static/*", "static/**/*"],
    },
    include_package_data=True,
    python_requires=">=3.9.5",
    install_requires=[
        # Dependencies are managed in requirements.txt
        # This is intentionally minimal to avoid duplication
    ],
    entry_points={
        "console_scripts": [
            "orpheus-dashboard=orpheus_dashboard.main:main",
        ],
    },
)
