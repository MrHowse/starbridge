#!/usr/bin/env python3
"""
Starbridge — Entry Point

Starts the Starbridge game server. Other devices on the local network
can connect by navigating to the printed URL in a web browser.
"""
from __future__ import annotations

import socket
import sys

import uvicorn


def get_local_ip() -> str:
    """Get the local network IP address for LAN connections."""
    try:
        # Connect to an external address to determine the local interface IP.
        # No data is actually sent.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    """Start the Starbridge server."""
    host = "0.0.0.0"
    port = 8666
    local_ip = get_local_ip()

    print()
    print("=" * 56)
    print("  ╔═╗╔╦╗╔═╗╦═╗╔╗ ╦═╗╦╔╦╗╔═╗╔═╗")
    print("  ╚═╗ ║ ╠═╣╠╦╝╠╩╗╠╦╝║ ║║║ ╦║╣ ")
    print("  ╚═╝ ╩ ╩ ╩╩╚═╚═╝╩╚═╩═╩╝╚═╝╚═╝")
    print("  Bridge Crew Simulator v0.0.1")
    print("=" * 56)
    print()
    print(f"  Server running on: http://{local_ip}:{port}")
    print(f"  Lobby:             http://{local_ip}:{port}/client/lobby/")
    print()
    print("  Share the lobby URL with your crew to connect.")
    print("  Press Ctrl+C to stop the server.")
    print()
    print("=" * 56)
    print()

    uvicorn.run(
        "server.main:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
