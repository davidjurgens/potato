from setuptools import setup, find_packages
import os

# Read the README file for long description
def read_readme():
    readme_path = os.path.join(os.path.dirname(__file__), "README.md")
    with open(readme_path, "r", encoding="utf-8") as fh:
        return fh.read()

# Core dependencies required for basic server startup and annotation.
# These are imported unconditionally at module level by flask_server.py,
# routes.py, config_module.py, and other core modules.
_CORE_DEPS = [
    "beautifulsoup4>=4.10.0",
    "click>=8.0.3",
    "Flask>=3.0.0",
    "itsdangerous>=2.1.0",
    "Jinja2>=3.1.6",
    "joblib>=1.2.0",
    "MarkupSafe>=2.1.0",
    "numpy>=1.21.0",
    "pandas>=1.3.5",
    "pydantic>=2.11.9",
    "python-dateutil>=2.8.2",
    "pytz>=2021.3",
    "PyYAML>=6.0.1",
    "requests>=2.31.0",
    "scikit-learn>=1.0.2",
    "scipy>=1.7.3",
    "simpledorff>=0.0.2",
    "six>=1.16.0",
    "soupsieve>=2.3.1",
    "threadpoolctl>=3.0.0",
    "tqdm>=4.62.3",
    "ujson>=5.4.0",
    "Werkzeug>=3.0.6",
]

# Optional dependency groups for specific features.
# Install with: pip install potato-annotation[ai,formats]
_AI_DEPS = [
    "ollama>=0.6.0",
    "openai>=1.0.0",
]
_FORMAT_DEPS = [
    "pdfplumber>=0.10.0",
    "python-docx>=1.0.0",
    "mammoth>=1.6.0",
    "mistune>=3.0.0",
    "pygments>=2.17.0",
    "openpyxl>=3.1.0",
]
_VIZ_DEPS = [
    "umap-learn>=0.5.0",
]
_EXPORT_DEPS = [
    "pyarrow>=12.0.0",
]
_HF_DEPS = [
    "huggingface_hub>=0.20.0",
    "datasets>=2.14.0",
]
_AUTH_DEPS = [
    "Authlib>=1.3.0",
]
_LANGCHAIN_DEPS = [
    "langchain-core>=0.1.0",
]

setup(
    name="potato-annotation",
    version='2.4.1',
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
    install_requires=_CORE_DEPS,
    extras_require={
        "ai": _AI_DEPS,
        "formats": _FORMAT_DEPS,
        "viz": _VIZ_DEPS,
        "export": _EXPORT_DEPS,
        "huggingface": _HF_DEPS,
        "auth": _AUTH_DEPS,
        "langchain": _LANGCHAIN_DEPS,
        "all": _AI_DEPS + _FORMAT_DEPS + _VIZ_DEPS + _EXPORT_DEPS + _HF_DEPS + _AUTH_DEPS + _LANGCHAIN_DEPS,
    },
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