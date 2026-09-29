"""Waypoint Contracts - Teams-first contract intake autopilot."""

from agent.app import build_app

app = build_app()


if __name__ == "__main__":
    app.run()
