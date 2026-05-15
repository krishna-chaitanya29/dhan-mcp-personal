"""Load and validate environment variables for the Dhan MCP server."""

import os
from dotenv import load_dotenv

load_dotenv()

DHAN_CLIENT_ID: str = os.environ.get("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN: str = os.environ.get("DHAN_ACCESS_TOKEN", "")

INSTRUMENT_MASTER_URL: str = "https://images.dhan.co/api-data/api-scrip-master.csv"
INSTRUMENT_MASTER_CSV: str = "instrument_master.csv"
INSTRUMENT_MASTER_TIMESTAMP: str = "instrument_master_timestamp.txt"
INSTRUMENT_CACHE_TTL_HOURS: int = 24

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(PROJECT_ROOT, "mcp_server.log")

# Rate limits (seconds between calls)
OPTION_CHAIN_RATE_LIMIT: float = 5.0
DEFAULT_RATE_LIMIT: float = 0.5


def validate_credentials() -> None:
    """Raise ValueError if credentials are missing."""
    if not DHAN_CLIENT_ID:
        raise ValueError("DHAN_CLIENT_ID is not set in .env")
    if not DHAN_ACCESS_TOKEN:
        raise ValueError("DHAN_ACCESS_TOKEN is not set in .env")
