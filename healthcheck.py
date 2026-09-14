"""Container health check for the moderation dashboard."""
import sys
from urllib.request import urlopen

from src.config import Config


def main():
    """Probe the dashboard, or report healthy when it is not meant to be running."""
    if not Config.DASHBOARD_ENABLED:
        return 0

    # The dashboard binds a wildcard address by default, which cannot be
    # connected to from inside the container.
    host = Config.DASHBOARD_HOST
    if host in ('0.0.0.0', '::', ''):
        host = '127.0.0.1'

    try:
        with urlopen(f"http://{host}:{Config.DASHBOARD_PORT}/healthz", timeout=5) as response:
            return 0 if response.status == 200 else 1
    except Exception as e:
        print(f"Dashboard health check failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
