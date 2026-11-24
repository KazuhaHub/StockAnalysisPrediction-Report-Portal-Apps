"""Loaded by every Python process a market-monitor job starts (job_env puts
this directory first on PYTHONPATH)."""
try:
    import https_only
    https_only.install()
except ImportError:  # requests is not installed in this interpreter
    pass
