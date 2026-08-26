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
# All AI SDKs are imported lazily (see potato/ai/ai_endpoint.py's lazy
# endpoint registry), so none of these are needed for basic server startup.
_AI_DEPS = [
    "ollama>=0.6.0",
    "openai>=1.0.0",
    "anthropic>=0.30.0",
    "google-genai>=1.0.0",
]
_FORMAT_DEPS = [
    "pdfplumber>=0.10.0",
    "python-docx>=1.0.0",
    "mammoth>=1.6.0",
    "mistune>=3.0.0",
    "pygments>=2.17.0",
    "openpyxl>=3.1.0",
]
# Headless-browser rendering for `potato preview --screenshot`, which boots a
# task and reports what the browser did with it. Optional: without it preview
# still validates and still returns the server-rendered HTML.
# Model Context Protocol server, so coding agents can discover annotation types,
# validate configs and render tasks. Imported lazily by `potato mcp`.
_MCP_DEPS = [
    "mcp>=1.2.0",
]
_PREVIEW_DEPS = [
    "playwright>=1.40.0",
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
# Optional server-side vision stack. Browser segmentation needs none of this:
# ONNX Runtime Web is vendored under potato/static/ and runs the default models
# with no Python dependency at all. These cover the server endpoints
# (`ai_type: sam`, `sam3`, SAM 2 video propagation) and decoding the image
# formats browsers cannot display.
#
# segment-anything is deliberately absent. Meta publishes it from GitHub, not
# PyPI, and the `segment-anything` name on PyPI is an anonymous upload with no
# homepage -- not something to pull into every `potato[vision]` install. The
# endpoint's error message names the official source instead.
_VISION_DEPS = [
    "onnxruntime>=1.17.0",
    "torch>=2.0.0",
    "torchvision>=0.15.0",
    "pillow-heif>=0.15.0",
    "rawpy>=0.19.0",
    "imageio>=2.31.0",
]
# SQL data sources, including live cursor-based ingestion. The driver is
# separate and backend-specific: psycopg2-binary for PostgreSQL, pymysql for
# MySQL. SQLite needs nothing beyond the standard library.
_DB_DEPS = [
    "sqlalchemy>=2.0",
]
# `potato deploy` to a VM provider. Only the SSH transport is extra: the API
# clients use `requests` and the templates use Jinja2, both core dependencies.
# paramiko 3.0+ is required for Ed25519Key.generate.
_DEPLOY_DEPS = [
    "paramiko>=3.0.0",
]

setup(
    name="potato-annotation",
    version='2.8.1',
    author="Potato Development Team",
    author_email="jurgens@umich.edu",
    description="A flexible, stand-alone, web-based platform for text annotation tasks",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/davidjurgens/potato",
    project_urls={
        "Documentation": "https://www.potatoannotator.com/docs",
        "Technical Reference": "https://potatoannotator.readthedocs.io/",
        "Source": "https://github.com/davidjurgens/potato",
        "Website": "https://www.potatoannotator.com",
    },
    license="GPL-3.0-or-later",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
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
        "preview": _PREVIEW_DEPS,
        "mcp": _MCP_DEPS,
        # Everything a coding agent needs: the MCP server plus browser rendering.
        "agent": _MCP_DEPS + _PREVIEW_DEPS,
        "export": _EXPORT_DEPS,
        "huggingface": _HF_DEPS,
        # Dataset publishing: HuggingFace push + parquet output. Zenodo and the
        # local archive need only `requests` (a core dependency), so no extra
        # deps beyond these.
        "publish": _HF_DEPS + _EXPORT_DEPS,
        "auth": _AUTH_DEPS,
        "langchain": _LANGCHAIN_DEPS,
        "db": _DB_DEPS,
        "deploy": _DEPLOY_DEPS,
        "vision": _VISION_DEPS,
        # `all` deliberately excludes `vision`: torch is a multi-gigabyte
        # install, and nothing in the default experience needs it.
        "all": _AI_DEPS + _FORMAT_DEPS + _VIZ_DEPS + _EXPORT_DEPS + _HF_DEPS + _AUTH_DEPS + _LANGCHAIN_DEPS + _DB_DEPS + _DEPLOY_DEPS + _PREVIEW_DEPS + _MCP_DEPS,
    },
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "potato=potato.flask_server:main",
        ],
        # Pytest plugin for Potato evaluations (markers, the potato_eval fixture,
        # --potato-threshold gating). Inert unless eval tests run / thresholds set.
        "pytest11": [
            "potato_eval=potato.testing.pytest_plugin",
        ],
    },
    package_data={
        # Templates and static assets are shipped recursively via MANIFEST.in
        # together with include_package_data=True above. Do not add per-folder
        # globs here; new nested asset directories should be included without
        # requiring packaging changes.
        "potato": [
            "i18n/*.yaml",
            # Generated specs: the config JSON Schema and the examples catalog.
            # Shipped so editors, agents and the MCP server resolve them offline
            # from an installed wheel, without reaching the docs site. The
            # examples catalog especially -- `examples/` itself is not packaged,
            # so this JSON is the only record of it a wheel has. Regenerate:
            #   python scripts/generate_config_schema.py
            #   python scripts/generate_examples_manifest.py
            "schemas/*.json",
            # cloud-init, Caddyfile and systemd unit templates. A provider
            # renders these from an installed wheel, so they must ship.
            "deploy/templates/*.j2",
        ],
    },
)
