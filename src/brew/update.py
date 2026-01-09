#!/usr/bin/env python3
import subprocess
import sys

from util.command.command import capture_lines, capture_text


def update():
    """
    Updates Homebrew formulas and displays:
     - full info for new formulas
     - outdated formulas
    """
    print("Fetching old formulas...")
    old_formulas = brew_search()

    print("Updating Homebrew...")
    update_output = ""
    try:
        result = capture_text(["brew", "update"])
        update_output = result.stdout
        print(update_output, end="")
    except subprocess.CalledProcessError as e:
        print(f"Brew update failed: {e}", file=sys.stderr)
        print(e.stdout, end="")
        print(e.stderr, file=sys.stderr)
        sys.exit(e.returncode)

    if "Already up-to-date." not in update_output:
        print("Fetching new formulas...")
        new_formulas = brew_search()
        newly_added_formulas = sorted(list(new_formulas - old_formulas))
        if newly_added_formulas:
            brew_info(newly_added_formulas)
        else:
            print("No new formulas added.")

    outdated_formulas_command = ["brew", "upgrade", "--formula", "--dry-run"]
    if capture_lines(outdated_formulas_command):
        print("Upgrade outdated formulas...")
        subprocess.run(outdated_formulas_command)
    else:
        print("No outdated formulas.")


def brew_search() -> set[str]:
    return set(capture_lines(["brew", "search", "--formula", "/"]))


def brew_info(newly_added_formulas: list[str]):
    print(f"Newly added formulas: {', '.join(newly_added_formulas)}")

    # chunk_size 100 is a safe bet for most OS argument limits
    chunk_size = 100
    for i in range(0, len(newly_added_formulas), chunk_size):
        chunk = newly_added_formulas[i : i + chunk_size]
        try:
            # print(f"\n--- Fetching info for chunk {i // chunk_size + 1} ---")
            subprocess.run(["brew", "info"] + chunk, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error running brew info for a chunk: {e}", file=sys.stderr)


if __name__ == "__main__":
    update()
