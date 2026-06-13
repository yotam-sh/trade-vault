"""Library update reminder — prints a console warning every 2 months."""

import json
import os
import sys
import subprocess
from datetime import date, datetime

_CHECK_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'lib_check.json')
_CHECK_INTERVAL_DAYS = 60  # ~2 months

# ANSI colours — work on Linux/macOS and Windows 10+ terminals
_YELLOW = '\033[93m'
_CYAN   = '\033[96m'
_GREEN  = '\033[92m'
_RED    = '\033[91m'
_BOLD   = '\033[1m'
_RESET  = '\033[0m'


def _load():
    path = os.path.normpath(_CHECK_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data):
    path = os.path.normpath(_CHECK_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def startup_check():
    """Print a console reminder if libraries haven't been checked in 2 months.

    Called from server.py on Flask startup. Silent when the check is recent;
    noisy (but non-blocking) when overdue.
    """
    data = _load()
    last_str = data.get('last_checked')
    today = date.today()

    if last_str:
        try:
            last = datetime.strptime(last_str, '%Y-%m-%d').date()
            days_since = (today - last).days
            if days_since < _CHECK_INTERVAL_DAYS:
                return  # still fresh, stay silent
        except ValueError:
            days_since = _CHECK_INTERVAL_DAYS + 1
    else:
        days_since = None

    msg_days = f"{days_since} days ago" if days_since else "never"
    print(
        f"\n{_BOLD}{_YELLOW}⚠  Library update reminder{_RESET}  "
        f"(last checked: {msg_days})",
        file=sys.stderr,
    )
    print(
        f"   {_CYAN}Settings → Maintenance{_RESET}  — check for / upgrade outdated packages\n",
        file=sys.stderr,
    )


def run_check_libs():
    """Print a table of outdated packages (pip list --outdated)."""
    print(f"{_BOLD}Checking for outdated packages...{_RESET}")
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'list', '--outdated', '--format=columns'],
        capture_output=True, text=True,
    )
    output = result.stdout.strip()
    if output:
        print(output)
    else:
        print(f"{_GREEN}All packages are up to date.{_RESET}")
    if result.stderr:
        # filter pip's own upgrade notice — not useful here
        for line in result.stderr.splitlines():
            if 'pip install --upgrade pip' not in line:
                print(line, file=sys.stderr)

    # Update the last-checked timestamp
    data = _load()
    data['last_checked'] = date.today().isoformat()
    _save(data)
    print(f"\n{_CYAN}Last-checked date updated to {data['last_checked']}.{_RESET}")


def run_upgrade_libs():
    """Upgrade all packages listed in requirements.txt to their latest versions."""
    req_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', 'requirements.txt')
    )
    if not os.path.exists(req_path):
        print(f"{_RED}requirements.txt not found at {req_path}{_RESET}", file=sys.stderr)
        return

    print(f"{_BOLD}Upgrading packages from requirements.txt...{_RESET}")
    print(f"  {_CYAN}{sys.executable} -m pip install --upgrade -r {req_path}{_RESET}\n")

    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--upgrade', '-r', req_path],
        text=True,
    )

    if result.returncode == 0:
        print(f"\n{_GREEN}Upgrade complete.{_RESET}")
        data = _load()
        data['last_checked'] = date.today().isoformat()
        _save(data)
        print(f"{_CYAN}Last-checked date updated to {data['last_checked']}.{_RESET}")
    else:
        print(f"\n{_RED}Upgrade finished with errors (exit code {result.returncode}).{_RESET}",
              file=sys.stderr)
