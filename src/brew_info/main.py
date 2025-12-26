#!/usr/bin/env python3
import subprocess
import sys


def main():
    # 1. Get old formulas
    print("Fetching old formulas...")
    old_formulas = formulas()

    # 2. Update brew
    print("Updating Homebrew...")
    update_output = ""
    try:
        result = subprocess.run(["brew", "update"], capture_output=True, text=True, check=True)
        update_output = result.stdout
        print(update_output, end="")
    except subprocess.CalledProcessError as e:
        print(f"Brew update failed: {e}", file=sys.stderr)
        print(e.stdout, end="")
        print(e.stderr, file=sys.stderr)
        sys.exit(e.returncode)

    # 3. Check if anything was updated
    if "Already up-to-date." in update_output:
        print("No new formulas added.")
        return

    # 4. Get new formulas
    print("Fetching new formulas...")
    new_formulas = formulas()

    # 5. Find newly added formulas
    newly_added_formulas = sorted(list(new_formulas - old_formulas))

    if not newly_added_formulas:
        print("No new formulas added.")
        return

    print(f"Newly added formulas: {', '.join(newly_added_formulas)}")

    # 6. Run brew info on newly added formulas (simulating xargs)
    # chunk_size 100 is a safe bet for most OS argument limits
    chunk_size = 100
    for i in range(0, len(newly_added_formulas), chunk_size):
        chunk = newly_added_formulas[i : i + chunk_size]
        try:
            print(f"\n--- Fetching info for chunk {i // chunk_size + 1} ---")
            subprocess.run(["brew", "info"] + chunk, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error running brew info for a chunk: {e}", file=sys.stderr)


def run_command(command: list[str]) -> list[str]:
    """Runs a shell command and returns its output as a list of lines."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return result.stdout.strip().splitlines()
    except subprocess.CalledProcessError as e:
        print(f"Error running command {' '.join(command)}: {e.stderr}", file=sys.stderr)
        return []


def formulas() -> set[str]:
    return set(run_command(["brew", "search", "--formula", "/"]))


if __name__ == "__main__":
    main()
