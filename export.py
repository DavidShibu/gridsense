from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "project_export.md"

# Human-maintained source and documentation files.
INCLUDE_EXTENSIONS = {
    ".py", ".md", ".toml", ".sh", ".yaml", ".yml",
    ".json", ".ini", ".cfg", ".txt", ".sql",
}

# Explicitly excluded directories.
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

# Generated data, logs, databases, and common backup files.
EXCLUDED_NAMES = {
    "project_export.md",
    "uv.lock",          # Remove this entry if you want the lockfile.
    "acn_sessions.json",
    "gridsense.db",
    "scheduler.log",
    "simulator.log",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".log",
}

# Files you explicitly want to preserve despite their names.
INCLUDE_FILES = {
    "README.md",
    "pyproject.toml",
    "main.py",
    "app.py",
    "battery_model.py",
    "database.py",
    "ev_data.py",
    "ml_module.py",
    "scheduler.py",
    "simulator.py",
    "acndata_client.py",
    "reset_db.py",
    "test_mqtt.py",
    "start.sh",
    "clean.sh",
}


def should_include(path: Path) -> bool:
    relative = path.relative_to(ROOT)

    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False

    if path.name in EXCLUDED_NAMES:
        return False

    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False

    # Explicit allowlist takes precedence over extension filtering.
    if path.name in INCLUDE_FILES:
        return True

    # Ignore backups and temporary copies.
    name = path.stem.lower()
    if (
        name.startswith(".")
        or " copy" in name
        or name.startswith("old_")
        or name.endswith("_old")
        or name.endswith("_backup")
        or name.endswith("~")
    ):
        return False

    return path.suffix.lower() in INCLUDE_EXTENSIONS


def language_for(path: Path) -> str:
    return {
        ".py": "python",
        ".md": "markdown",
        ".toml": "toml",
        ".sh": "bash",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".sql": "sql",
    }.get(path.suffix.lower(), "")


def export_project() -> None:
    start_time = perf_counter()

    print("=" * 65)
    print("[START] GridSense Project Export")
    print(f"[INFO] Root directory : {ROOT}")
    print(f"[INFO] Output file    : {OUTPUT}")
    print("=" * 65)

    try:
        # Milestone 1: Discover files.
        print("\n[MILESTONE 1/7] Scanning project directory...")

        discovered_files = list(ROOT.rglob("*"))
        all_files = [p for p in discovered_files if p.is_file()]

        print(f"[INFO] Total filesystem entries : {len(discovered_files)}")
        print(f"[INFO] Total files discovered   : {len(all_files)}")

        # Milestone 2: Apply filtering rules.
        print("\n[MILESTONE 2/7] Applying inclusion and exclusion rules...")

        files = sorted(
            (
                p for p in all_files
                if p != OUTPUT and should_include(p)
            ),
            key=lambda p: str(p.relative_to(ROOT)).lower(),
        )

        print(f"[INFO] Files selected for export : {len(files)}")
        print(f"[INFO] Files excluded             : {len(all_files) - len(files)}")

        if not files:
            print("[WARNING] No eligible files found.")

        # Milestone 3: Prepare the document header.
        print("\n[MILESTONE 3/7] Building document header and table of contents...")

        sections = [
            "# GridSense Project Export",
            "",
            f"Source directory: `{ROOT.name}`",
            "",
            "## Table of Contents",
            "",
        ]

        for index, path in enumerate(files, start=1):
            relative = path.relative_to(ROOT).as_posix()
            anchor = (
                relative.lower()
                .replace("/", "")
                .replace(".", "")
                .replace("_", "-")
            )

            sections.append(f"- [`{relative}`](#{anchor})")

            if index % 25 == 0 or index == len(files):
                print(
                    f"[TOC] Processed {index}/{len(files)} entries"
                )

        sections.extend(["", "---", ""])

        # Milestone 4: Read and append file contents.
        print("\n[MILESTONE 4/7] Reading source files and generating sections...")

        total_bytes = 0

        for index, path in enumerate(files, start=1):
            relative = path.relative_to(ROOT).as_posix()
            language = language_for(path)

            print(f"[FILE {index}/{len(files)}] Reading: {relative}")

            content = path.read_text(
                encoding="utf-8",
                errors="replace",
            ).rstrip()

            total_bytes += path.stat().st_size

            sections.extend([
                f"## `{relative}`",
                "",
                f"```{language}",
                content,
                "```",
                "",
            ])

            if index % 10 == 0 or index == len(files):
                elapsed = perf_counter() - start_time
                print(
                    f"[PROGRESS] {index}/{len(files)} files processed | "
                    f"{total_bytes:,} bytes read | "
                    f"{elapsed:.2f}s elapsed"
                )

        # Milestone 5: Assemble final Markdown.
        print("\n[MILESTONE 5/7] Assembling Markdown document...")

        document = "\n".join(sections)

        print(f"[INFO] Markdown sections : {len(files)}")
        print(f"[INFO] Document characters: {len(document):,}")

        # Milestone 6: Write output.
        print("\n[MILESTONE 6/7] Writing export file...")

        OUTPUT.write_text(
            document,
            encoding="utf-8",
        )

        output_size = OUTPUT.stat().st_size

        print(f"[SUCCESS] Export written: {OUTPUT}")
        print(f"[INFO] Output size: {output_size:,} bytes")

        # Milestone 7: Verify and summarize.
        print("\n[MILESTONE 7/7] Verifying export...")

        if not OUTPUT.exists():
            raise RuntimeError("Export file was not created.")

        if OUTPUT.stat().st_size == 0 and files:
            raise RuntimeError("Export file is unexpectedly empty.")

        elapsed = perf_counter() - start_time

        print("[VERIFY] Output file exists: YES")
        print(f"[VERIFY] Exported files: {len(files)}")
        print(f"[VERIFY] Output size: {output_size:,} bytes")

        print("\n[EXPORTED FILES]")
        for index, path in enumerate(files, start=1):
            print(f"  [{index:03d}] {path.relative_to(ROOT)}")

        print("\n" + "=" * 65)
        print("[COMPLETE] GridSense Project Export finished successfully.")
        print(f"[SUMMARY] Files exported : {len(files)}")
        print(f"[SUMMARY] Source bytes   : {total_bytes:,}")
        print(f"[SUMMARY] Export size    : {output_size:,} bytes")
        print(f"[SUMMARY] Total time     : {elapsed:.2f} seconds")
        print("=" * 65)

    except Exception as exc:
        elapsed = perf_counter() - start_time
        print("\n" + "!" * 65)
        print("[ERROR] Project export failed.")
        print(f"[ERROR] Type    : {type(exc).__name__}")
        print(f"[ERROR] Details : {exc}")
        print(f"[INFO] Elapsed time: {elapsed:.2f} seconds")
        print("!" * 65)
        raise


if __name__ == "__main__":
    print("[BOOT] Initializing export script...")
    export_project()
    print("[EXIT] Script execution finished.")
