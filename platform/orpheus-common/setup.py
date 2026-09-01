"""
Setup script for orpheus-common package.

This exists for compatibility with older pip versions that don't support
editable installs from pyproject.toml alone.
"""

from setuptools import setup, find_packages

# Read requirements from requirements.txt
with open("requirements.txt") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="orpheus-common",
    # version omitted on purpose: it is dynamic, sourced from the VERSION
    # file via [tool.setuptools.dynamic] in pyproject.toml (the SSoT).
    description="Shared platform library for Orpheus cross-species communication system",
    author="Orpheus Project",
    author_email="scottchronicity@gmail.com",
    url="https://github.com/scottchronicity/orpheus",
    package_dir={"": "src"},
    packages=find_packages(where="src", include=["orpheus_common", "orpheus_common.*"]),
    package_data={
        "orpheus_common": [
            "sounds/*.wav",
            "sounds/*.mp3",
            "sounds/*.flac",
            "sounds/*.ogg",
            "sounds/*.m4a",
            "sounds/*.aiff",
        ],
        # Data-driven entity taxonomy (must ship in the wheel for the Jetson
        # install, where code runs from the installed package, not the tree).
        "orpheus_common.detection": [
            "data/*.yaml",
        ],
    },
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=requirements,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
