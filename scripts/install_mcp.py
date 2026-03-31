#!/usr/bin/env python3
"""
install_mcp.py — Register the Regression Tracker MCP server with Claude Code.

Run this once on any machine to let Claude query the regression tracker:

    python3 scripts/install_mcp.py

By default it points to http://10.68.137.99/mcp. Override with --url:

    python3 scripts/install_mcp.py --url http://myserver:8000/mcp

Safe to re-run: merges with existing ~/.claude/settings.json.
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_URL = "http://10.68.137.99/mcp"
SERVER_NAME = "regression-tracker"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL, help=f"MCP server URL (default: {DEFAULT_URL})")
    parser.add_argument("--remove", action="store_true", help="Remove the MCP server instead of adding it")
    args = parser.parse_args()

    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing settings (or start fresh)
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError as e:
            print(f"Error: {settings_path} contains invalid JSON: {e}")
            sys.exit(1)
    else:
        settings = {}

    if args.remove:
        removed = settings.get("mcpServers", {}).pop(SERVER_NAME, None)
        if removed:
            settings_path.write_text(json.dumps(settings, indent=2) + "\n")
            print(f"Removed '{SERVER_NAME}' from {settings_path}")
        else:
            print(f"'{SERVER_NAME}' was not configured — nothing to remove.")
        return

    # Add / update the MCP server entry
    settings.setdefault("mcpServers", {})[SERVER_NAME] = {
        "type": "http",
        "url": args.url,
    }

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    print(f"Configured '{SERVER_NAME}' MCP server in {settings_path}")
    print(f"  URL: {args.url}")
    print()
    print("Restart Claude Code (or run /mcp to reload), then try:")
    print('  "List all releases in the regression tracker"')
    print('  "What failed in 7.0 routing for the latest run?"')
    print('  "Compare the two most recent 7.0 runs"')


if __name__ == "__main__":
    main()
