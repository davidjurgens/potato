"""
Entry point for running the simulator as a module.

Usage:
    python -m potato.simulator --server http://localhost:8000 --users 10
"""

from .cli import main

if __name__ == "__main__":
    main()
