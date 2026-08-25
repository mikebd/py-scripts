from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from jetbrains import codex_fix


def _write_idea_log(log_file: Path, required_versions: list[str]) -> None:
    """
    Write an idea.log that includes multiple Codex version mismatch lines.
    The implementation should select the LAST required version.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    lines = ["2026-01-01 00:00:00,000 INFO - some other log line\n"]
    for ver in required_versions:
        lines.append(
            "2026-01-01 00:00:00,000 INFO - "
            "#c.i.m.l.a.c.i.CodexInstallerService - "
            f"Codex CLI version mismatch: installed=null, required={ver}\n"
        )
    log_file.write_text("".join(lines), encoding="utf-8")


def _touch_dir_with_mtime(dir_path: Path, mtime: float) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    os.utime(dir_path, (mtime, mtime))


def test_extract_required_version_uses_last_match(tmp_path: Path) -> None:
    log_file = tmp_path / "idea.log"
    _write_idea_log(log_file, ["0.86.0", "0.87.0", "0.99.9"])
    assert codex_fix._extract_required_version(log_file) == "0.99.9"


def test_extract_required_version_returns_none_when_missing(tmp_path: Path) -> None:
    log_file = tmp_path / "idea.log"
    log_file.write_text("no mismatch lines here\n", encoding="utf-8")
    assert codex_fix._extract_required_version(log_file) is None


def test_apply_filters_include_exclude(tmp_path: Path) -> None:
    dirs = [
        tmp_path / "GoLand2025.3",
        tmp_path / "IntelliJIdea2025.3",
        tmp_path / "Rider2025.3",
    ]
    for d in dirs:
        d.mkdir()

    include = re.compile(r"^(GoLand|IntelliJIdea)")
    exclude = re.compile(r"^Rider")

    out = codex_fix._apply_filters(dirs, include=include, exclude=exclude)
    assert [p.name for p in out] == ["GoLand2025.3", "IntelliJIdea2025.3"]


def test_default_pick_prefers_newest_goland(tmp_path: Path) -> None:
    goland_old = tmp_path / "GoLand2025.2"
    goland_new = tmp_path / "GoLand2025.3"
    idea_new = tmp_path / "IntelliJIdea2025.3"

    _touch_dir_with_mtime(goland_old, 10.0)
    _touch_dir_with_mtime(goland_new, 20.0)
    _touch_dir_with_mtime(idea_new, 30.0)

    picked = codex_fix._default_pick([idea_new, goland_old, goland_new])
    assert [p.name for p in picked] == ["GoLand2025.3"]


def test_iter_candidate_ide_dirs_sorted_newest_first(tmp_path: Path) -> None:
    d1 = tmp_path / "GoLand2025.1"
    d2 = tmp_path / "GoLand2025.2"
    d3 = tmp_path / "GoLand2025.3"

    _touch_dir_with_mtime(d1, 1.0)
    _touch_dir_with_mtime(d2, 2.0)
    _touch_dir_with_mtime(d3, 3.0)

    out = codex_fix._iter_candidate_ide_dirs(tmp_path)
    assert [p.name for p in out][:3] == ["GoLand2025.3", "GoLand2025.2", "GoLand2025.1"]


def test_find_idea_log_prefers_idea_log_then_idea_log_1(tmp_path: Path) -> None:
    ide_dir = tmp_path / "GoLand2025.3"
    log_dir = ide_dir / "log"
    log_dir.mkdir(parents=True)

    idea_log_1 = log_dir / "idea.log.1"
    idea_log_1.write_text("x\n", encoding="utf-8")
    assert codex_fix._find_idea_log(ide_dir) == idea_log_1

    idea_log = log_dir / "idea.log"
    idea_log.write_text("y\n", encoding="utf-8")
    assert codex_fix._find_idea_log(ide_dir) == idea_log


def test_backup_if_exists_creates_backup(tmp_path: Path) -> None:
    target = tmp_path / "codex-x86_64-unknown-linux-gnu"
    target.write_text("old", encoding="utf-8")

    backup = codex_fix._backup_if_exists(target)
    assert backup is not None
    assert not target.exists()
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "old"
    assert re.match(r"codex-x86_64-unknown-linux-gnu\.bak\.\d{14}$", backup.name)


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    tar_path = tmp_path / "bad.tar.gz"
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    import tarfile  # stdlib

    with tarfile.open(tar_path, "w:gz") as tf:
        ti = tarfile.TarInfo(name="../evil")
        ti.size = 0
        tf.addfile(ti)

    with pytest.raises(RuntimeError, match="Unsafe tar member path"):
        codex_fix._safe_extract_tar_gz(tar_path, extract_dir)


def test_main_applies_to_multiple_ides_grouped_by_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    End-to-end-ish test of main() without network or executing real binaries:
    - create two IDE dirs
    - each has idea.log specifying different required versions
    - monkeypatch download/extract/run_version so main() is deterministic
    - assert both IDE target binaries exist
    - assert we "downloaded" once per version (grouping works)
    """
    cache_root = tmp_path / "JetBrains"

    goland = cache_root / "GoLand2025.3"
    idea = cache_root / "IntelliJIdea2025.3"

    _touch_dir_with_mtime(goland, 2.0)
    _touch_dir_with_mtime(idea, 1.0)

    _write_idea_log(goland / "log" / "idea.log", ["0.87.0"])
    _write_idea_log(idea / "log" / "idea.log", ["0.88.0"])

    downloads: list[str] = []

    def fake_download(url: str, dest: Path, *, timeout_s: float) -> None:
        _ = timeout_s
        downloads.append(url)
        dest.write_bytes(b"not-a-real-tarball")

    def fake_safe_extract(_tar_path: Path, extract_dir: Path) -> None:
        extract_dir.mkdir(parents=True, exist_ok=True)
        (extract_dir / "codex").write_text("fake", encoding="utf-8")

    def fake_run_version(_binary: Path) -> str:
        return "codex 0.0.0 (fake)"

    monkeypatch.setattr(codex_fix, "_download", fake_download)
    monkeypatch.setattr(codex_fix, "_safe_extract_tar_gz", fake_safe_extract)
    monkeypatch.setattr(codex_fix, "_run_version", fake_run_version)

    rc = codex_fix.main(["--cache-root", str(cache_root), "--all"])
    assert rc == 0

    goland_target = goland / "aia" / "codex" / "bin" / "codex-x86_64-unknown-linux-gnu"
    idea_target = idea / "aia" / "codex" / "bin" / "codex-x86_64-unknown-linux-gnu"

    assert goland_target.exists()
    assert idea_target.exists()

    assert len(downloads) == 2
    assert any("rust-v0.87.0" in u for u in downloads)
    assert any("rust-v0.88.0" in u for u in downloads)


def test_main_respects_include_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_root = tmp_path / "JetBrains"
    goland = cache_root / "GoLand2025.3"
    idea = cache_root / "IntelliJIdea2025.3"

    _touch_dir_with_mtime(goland, 2.0)
    _touch_dir_with_mtime(idea, 1.0)

    _write_idea_log(goland / "log" / "idea.log", ["0.87.0"])
    _write_idea_log(idea / "log" / "idea.log", ["0.87.0"])

    def fake_download(_url: str, dest: Path, *, timeout_s: float) -> None:
        _ = timeout_s
        dest.write_bytes(b"x")

    def fake_safe_extract(_tar_path: Path, extract_dir: Path) -> None:
        extract_dir.mkdir(parents=True, exist_ok=True)
        (extract_dir / "codex").write_text("x", encoding="utf-8")

    monkeypatch.setattr(codex_fix, "_download", fake_download)
    monkeypatch.setattr(codex_fix, "_safe_extract_tar_gz", fake_safe_extract)

    def fake_run_version(_binary: Path) -> str:
        return "codex fake"

    monkeypatch.setattr(codex_fix, "_run_version", fake_run_version)

    rc = codex_fix.main(
        [
            "--cache-root",
            str(cache_root),
            "--all",
            "--include",
            "^GoLand",
        ]
    )
    assert rc == 0

    goland_target = goland / "aia" / "codex" / "bin" / "codex-x86_64-unknown-linux-gnu"
    idea_target = idea / "aia" / "codex" / "bin" / "codex-x86_64-unknown-linux-gnu"

    assert goland_target.exists()
    assert not idea_target.exists()
