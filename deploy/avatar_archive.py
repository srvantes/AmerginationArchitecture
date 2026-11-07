"""Stream and validate the flat profile media store inside the app container."""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile
from typing import BinaryIO


AVATAR_DIR = Path("/app/var/avatars")
MAX_FILES = 100_000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024 * 1024
FILENAME = re.compile(r"(?:[a-z0-9-]{1,160}\.png|bg-[a-z0-9-]{1,100}\.webp|shop-[a-z0-9-]{1,100}\.(?:gif|webp|jpg))\Z")


class ArchiveError(ValueError):
    pass


def avatar_root() -> Path:
    # Docker mounts this exact directory. Never follow a substituted root link.
    if AVATAR_DIR.is_symlink() or AVATAR_DIR.resolve() != AVATAR_DIR:
        raise ArchiveError("The avatar directory must be the configured absolute mount.")
    if not AVATAR_DIR.is_dir():
        raise ArchiveError("The avatar volume is missing.")
    return AVATAR_DIR


def backup(output: BinaryIO) -> None:
    root = avatar_root()
    files = []
    total = 0
    for path in sorted(root.iterdir()):
        # A failed restore can leave a private staging directory for inspection.
        # It is not part of the live avatar store and must not enter new backups.
        if path.name.startswith(".restore-") and path.is_dir() and not path.is_symlink():
            continue
        if path.name == ".gitkeep" and path.is_file() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file() or not FILENAME.fullmatch(path.name):
            raise ArchiveError("The avatar store contains an unexpected file type or name.")
        size = path.stat().st_size
        total += size
        if not 0 < size <= MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
            raise ArchiveError("The avatar store exceeds the supported backup limits.")
        files.append(path)

    def metadata(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mode = 0o700 if info.isdir() else 0o600
        return info

    with tarfile.open(fileobj=output, mode="w|gz", format=tarfile.USTAR_FORMAT) as archive:
        archive.add(root, arcname="avatars", recursive=False, filter=metadata)
        for path in files:
            archive.add(path, arcname="avatars/" + path.name, recursive=False, filter=metadata)


def read_archive(source: BinaryIO, staging: Path | None = None) -> list[str]:
    names: set[str] = set()
    files: list[str] = []
    total = 0
    with tarfile.open(fileobj=source, mode="r|gz") as archive:
        for member in archive:
            if member.name in names:
                raise ArchiveError("The avatar archive contains duplicate entries.")
            names.add(member.name)
            if member.name == "avatars" and member.isdir() and member.size == 0:
                continue
            parts = member.name.split("/")
            if (len(parts) != 2 or parts[0] != "avatars" or not FILENAME.fullmatch(parts[1])
                    or not member.isfile() or member.issym() or member.islnk()):
                raise ArchiveError("The avatar archive contains an unsafe path or file type.")
            total += member.size
            if (not 0 < member.size <= MAX_FILE_BYTES or total > MAX_TOTAL_BYTES
                    or len(files) >= MAX_FILES):
                raise ArchiveError("The avatar archive exceeds the supported restore limits.")
            contents = archive.extractfile(member)
            if contents is None:
                raise ArchiveError("The avatar archive contains an unreadable file.")
            output = (staging / parts[1]).open("xb") if staging else None
            try:
                remaining = member.size
                while remaining:
                    chunk = contents.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise ArchiveError("The avatar archive is truncated.")
                    if output:
                        output.write(chunk)
                    remaining -= len(chunk)
            finally:
                contents.close()
                if output:
                    output.close()
                    (staging / parts[1]).chmod(0o600)
            files.append(parts[1])
    if "avatars" not in names:
        raise ArchiveError("The avatar archive has no expected root directory.")
    return files


def restore(source: BinaryIO) -> None:
    root = avatar_root()
    staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=root))
    # Fully check/extract to a private directory before replacing any live file.
    # No extractall(), links, special files, arbitrary paths or recursive deletes.
    names = read_archive(source, staging)
    for name in names:
        target = root / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ArchiveError("An avatar restore target is not a regular file.")
    for name in names:
        os.replace(staging / name, root / name)
    staging.rmdir()
    # Existing files absent from the snapshot remain as harmless orphans. Their
    # generated names are not referenced by the restored database.


def main() -> int:
    os.umask(0o077)
    try:
        if sys.argv[1:] == ["backup"]:
            backup(sys.stdout.buffer)
        elif sys.argv[1:] == ["validate"]:
            read_archive(sys.stdin.buffer)
        elif sys.argv[1:] == ["restore"]:
            restore(sys.stdin.buffer)
        else:
            print("Usage: avatar_archive.py backup|validate|restore", file=sys.stderr)
            return 2
    except (ArchiveError, OSError, tarfile.TarError, EOFError) as error:
        # Do not echo untrusted archive names, database values or credentials.
        message = str(error) if isinstance(error, ArchiveError) else type(error).__name__
        print("Avatar archive operation failed: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
