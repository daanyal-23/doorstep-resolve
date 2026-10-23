"""
Doorstep Resolve - Configuration and Environment Management.

Loads configuration from project-root .env file automatically at startup.
Ensures explicit process environment variables always take precedence (override=False).
"""

import os
from pathlib import Path
from typing import Optional


def load_project_env(env_path: Optional[Path] = None, override: bool = False) -> bool:
    """
    Automatically loads environment variables from project-root .env file.
    Does NOT override existing environment variables by default, preserving
    explicit environment variable overrides.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False

    if env_path is not None:
        target_path = Path(env_path)
    else:
        # Resolve project root by navigating up from doorstep_resolve package
        current_dir = Path(__file__).resolve().parent
        target_path = current_dir.parent / ".env"
        if not target_path.exists():
            # Fallback to current working directory
            cwd_path = Path.cwd() / ".env"
            if cwd_path.exists():
                target_path = cwd_path

    if target_path.exists() and target_path.is_file():
        return load_dotenv(dotenv_path=target_path, override=override)
    return False


# Automatically load .env on module import
load_project_env()
