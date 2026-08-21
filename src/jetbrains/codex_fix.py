from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

_REQUIRED_RE = re.compile(r"Codex CLI version mismatch:.*required=(?P<ver>[0-9]+(?:\.[0-9]+)*)")


@dataclass(frozen=True)
class IdePaths:
    ide_dir: Path
    log_file: Path
    codex_bin_dir: Path
    expected_binary: Path


def _iter_candidate_ide_dirs(cache_root: Path) -> list[Path]:
    if not cache_root.is_dir():
        raise FileNotFoundError(f"JetBrains cache root not found: {cache_root}")

    dirs = [p for p in cache_root.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs


def _find_idea_log(ide_dir: Path) -> Path | None:
    log_dir = ide_dir / "log"
    if not log_dir.is_dir():
        return None

    for name in ("idea.log", "idea.log.1"):
        p = log_dir / name
        if p.is_file():
            return p

    matches = sorted(log_dir.glob("idea.log*"))
    for p in reversed(matches):
        if p.is_file():
            return p

    return None


def _extract_required_version(log_file: Path) -> str | None:
    text = log_file.read_text(encoding="utf-8", errors="replace")
    matches = list(_REQUIRED_RE.finditer(text))
    if not matches:
        return None
    return matches[-1].group("ver")


def _detect_paths(ide_dir: Path, log_file: Path) -> IdePaths:
    codex_bin_dir = ide_dir / "aia" / "codex" / "bin"
    expected_binary = codex_bin_dir / "codex-x86_64-unknown-linux-gnu"
    return IdePaths(
        ide_dir=ide_dir,
        log_file=log_file,
        codex_bin_dir=codex_bin_dir,
        expected_binary=expected_binary,
    )


def _sourceforge_url(version: str) -> str:
    return (
        "https://sourceforge.net/projects/openai-codex.mirror/files/"
        f"rust-v{version}/codex-x86_64-unknown-linux-musl.tar.gz/download"
    )


def _download(url: str, dest: Path, *, timeout_s: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "mikebd-py-scripts/0.1"})
    with urlopen(req, timeout=timeout_s) as r, dest.open("wb") as f:  # noqa: S310
        shutil.copyfileobj(r, f)


def _safe_extract_tar_gz(tar_path: Path, extract_dir: Path) -> None:
    """
    Extract tar safely by preventing path traversal.
    """
    extract_dir.mkdir(parents=True, exist_ok=True)
    base = extract_dir.resolve()

    with tarfile.open(tar_path, "r:gz") as tf:
        members = tf.getmembers()
        for m in members:
            target = (extract_dir / m.name).resolve()
            if not target.is_relative_to(base):
                raise RuntimeError(f"Unsafe tar member path: {m.name}")
        tf.extractall(extract_dir, members=members)  # noqa: S202


def _find_codex_binary(extract_dir: Path) -> Path:
    for p in extract_dir.rglob("*"):
        if p.is_file() and p.name in {"codex", "codex-x86_64-unknown-linux-musl"}:
            return p
    raise FileNotFoundError(f"Could not find codex binary inside: {extract_dir}")


def _backup_if_exists(path: Path) -> Path | None:
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{ts}")
    path.rename(backup)
    return backup


def _run_version(binary: Path) -> str:
    proc = subprocess.run(
        [str(binary), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        raise RuntimeError(f"Binary did not run (exit {proc.returncode}). Output:\n{out}")
    return out


def _apply_filters(
    ide_dirs: Iterable[Path],
    include: re.Pattern[str] | None,
    exclude: re.Pattern[str] | None,
) -> list[Path]:
    out: list[Path] = []
    for d in ide_dirs:
        name = d.name
        if include is not None and include.search(name) is None:
            continue
        if exclude is not None and exclude.search(name) is not None:
            continue
        out.append(d)
    return out


def _default_pick(ide_dirs: list[Path]) -> list[Path]:
    goland = [p for p in ide_dirs if p.name.startswith("GoLand")]
    if goland:
        goland.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [goland[0]]
    return [ide_dirs[0]] if ide_dirs else []


def main(argv: list[str] | None = None) -> int:
    """
    Install musl Codex binaries into JetBrains IDE caches to avoid GLIBC mismatch.

    This tool:
    - detects one or more JetBrains IDE cache directories under ~/.cache/JetBrains
    - reads each IDE's idea.log to find the required Codex version
    - downloads the matching musl Codex tarball
    - installs it as codex-x86_64-unknown-linux-gnu in that IDE's cache
    """
    parser = argparse.ArgumentParser(
        prog="codex_fix",
        description=(
            "Install musl Codex binaries into JetBrains IDE caches to avoid GLIBC mismatch "
            "(handles multiple IDEs)."
        ),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path.home() / ".cache" / "JetBrains",
        help="JetBrains cache root (default: ~/.cache/JetBrains).",
    )
    parser.add_argument(
        "--ide-dir",
        type=Path,
        action="append",
        default=[],
        help="Specific IDE cache dir(s), e.g. ~/.cache/JetBrains/GoLand2025.3 (repeatable).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Apply to all IDE cache dirs under cache-root (after include/exclude filtering).",
    )
    parser.add_argument(
        "--include",
        type=str,
        default=None,
        help=r"Regex on directory name to include (e.g. '^(GoLand|IntelliJIdea)').",
    )
    parser.add_argument(
        "--exclude",
        type=str,
        default=None,
        help=r"Regex on directory name to exclude.",
    )
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        help="Override Codex version for all targets (otherwise parsed per-IDE from idea.log).",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=30.0,
        help="HTTP timeout for downloading Codex tarballs.",
    )
    args = parser.parse_args(argv)

    include_re = re.compile(args.include) if args.include else None
    exclude_re = re.compile(args.exclude) if args.exclude else None

    if args.ide_dir:
        targets = args.ide_dir
    else:
        candidates = _iter_candidate_ide_dirs(args.cache_root)
        candidates = _apply_filters(candidates, include_re, exclude_re)
        targets = candidates if args.all else _default_pick(candidates)

    if not targets:
        print("No IDE cache dirs selected.")
        return 2

    by_version: dict[str, list[IdePaths]] = {}
    skipped: list[tuple[Path, str]] = []

    for ide_dir in targets:
        if not ide_dir.is_dir():
            skipped.append((ide_dir, "not a directory"))
            continue

        log_file = _find_idea_log(ide_dir)
        if log_file is None:
            skipped.append((ide_dir, "no idea.log found"))
            continue

        ver = args.version or _extract_required_version(log_file)
        if ver is None:
            skipped.append((ide_dir, "no 'Codex CLI version mismatch ... required=...' line found"))
            continue

        by_version.setdefault(ver, []).append(_detect_paths(ide_dir, log_file))

    if not by_version:
        print("No IDEs had a detectable required Codex version.")
        for ide, reason in skipped:
            print(f"  - SKIP {ide.name}: {reason}")
        return 2

    failures: list[tuple[Path, str]] = []
    successes: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="codex-fix-") as td:
        tmpdir = Path(td)

        for ver, ide_paths_list in by_version.items():
            url = _sourceforge_url(ver)
            tar_path = tmpdir / f"codex-musl-{ver}.tar.gz"
            extract_dir = tmpdir / f"extract-{ver}"

            print(f"\n== Version {ver} ==")
            print(f"Downloading: {url}")

            try:
                _download(url, tar_path, timeout_s=args.timeout_s)
                print("Extracting…")
                _safe_extract_tar_gz(tar_path, extract_dir)
                codex_src = _find_codex_binary(extract_dir)
                os.chmod(codex_src, 0o755)
            except Exception as e:
                for p in ide_paths_list:
                    failures.append((p.ide_dir, f"download/extract failed for version {ver}: {e}"))
                continue

            for p in ide_paths_list:
                print(f"\nTarget IDE: {p.ide_dir.name}")
                print(f"  idea.log: {p.log_file}")
                print(f"  target:   {p.expected_binary}")

                try:
                    p.codex_bin_dir.mkdir(parents=True, exist_ok=True)

                    backup = _backup_if_exists(p.expected_binary)
                    if backup is not None:
                        print(f"  backup:   {backup.name}")

                    shutil.copy2(codex_src, p.expected_binary)
                    os.chmod(p.expected_binary, 0o755)

                    ver_out = _run_version(p.expected_binary)
                    print(f"  verify:   {ver_out}")

                    successes.append(p.ide_dir)
                except Exception as e:
                    failures.append((p.ide_dir, str(e)))

    print("\n== Summary ==")
    for ide, reason in skipped:
        print(f"  - SKIP {ide.name}: {reason}")
    for ide in successes:
        print(f"  - OK   {ide.name}")
    for ide, reason in failures:
        print(f"  - FAIL {ide.name}: {reason}")

    return 1 if failures else 0


def _entrypoint() -> int:
    """
    Run the CLI, converting unexpected exceptions into a clean message and exit code.
    """
    try:
        return main()
    except Exception as e:
        print(f"ERROR: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
