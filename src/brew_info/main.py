#!/usr/bin/env python3
import subprocess
import sys

def run_command(command):
    """Runs a shell command and returns its output as a list of lines."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return result.stdout.strip().splitlines()
    except subprocess.CalledProcessError as e:
        print(f"Error running command {' '.join(command)}: {e.stderr}", file=sys.stderr)
        return []

def main():
    # 1. Get old formulas
    print("Fetching old formulas...")
    old_formulas = set(run_command(["brew", "search", "--formula", "/"]))
    
    # 2. Update brew
    print("Updating Homebrew...")
    try:
        subprocess.run(["brew", "update"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Brew update failed: {e}", file=sys.stderr)
        # We can still proceed if we want to see if anything changed, 
        # but usually brew update failure means no new formulas.
        pass

    # 3. Get new formulas
    print("Fetching new formulas...")
    new_formulas = set(run_command(["brew", "search", "--formula", "/"]))

    # 4. Find newly added formulas
    newly_added_formulas = sorted(list(new_formulas - old_formulas))

    if not newly_added_formulas:
        print("No new formulas added.")
        return

    print(f"Newly added formulas: {', '.join(newly_added_formulas)}")

    # 5. Run brew info on newly added formulas
    # Using xargs-like behavior: passing all formulas to one brew info call
    try:
        subprocess.run(["brew", "info"] + newly_added_formulas, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running brew info: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
