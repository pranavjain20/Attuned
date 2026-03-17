"""Attuned — WHOOP-informed Spotify playlist generator."""

import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <command>")
        print("Commands: generate")
        sys.exit(1)

    command = sys.argv[1]

    if command == "generate":
        print("Not yet implemented — build starts Day 1.")
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
