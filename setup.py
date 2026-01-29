from setuptools import setup, find_packages
import os

# Read the README file for long description
def read_readme():
    with open("README.md", "r", encoding="utf-8") as fh:
        return fh.read()

# Read requirements if they exist
def read_requirements():
    requirements = []
    if os.path.exists("requirements.txt"):
        with open("requirements.txt", "r", encoding="utf-8") as fh:
            requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]
    return requirements

setup(
    name="potato-annotation",
    version='2.0.0',
    author="Potato Development Team",
    author_email="jurgens@umich.edu",
    description="A flexible, stand-alone, web-based platform for text annotation tasks",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/davidjurgens/potato",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Text Processing :: Linguistic",
    ],
    python_requires=">=3.7",
    install_requires=read_requirements(),
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "potato=potato.flask_server:main",
        ],
    },
    package_data={
        "potato": [
            "templates/*.html",
            "base_html/*.html",
            "base_html/examples/*.html",
            "static/*",
            "static/styles/*",
            "static/survey_assets/*",
        ],
    },
)