#!/usr/bin/env python3
"""Mirror the git-tracked website tree to the FTP server.

The script walks the list of files tracked in the current git working tree,
compares each one against the content hash recorded for it on the server,
uploads anything that's missing or different, and deletes any remote file or
directory that isn't tracked locally.

Content is compared via a SHA-256 manifest stored at the remote base as
`.ftp-sync-manifest.json`, written at the end of every successful run. Size
alone is not enough: a daily-regenerated CSV frequently changes content while
keeping the exact same byte count, and those edits were silently skipped.
Modtime is unusable too — in CI the local mtime is the checkout time (always
"now"), so any mtime comparison re-uploads everything on every run.

A file whose hash is absent from the manifest is always uploaded, so the
first run after this change (and any run against a server whose manifest was
lost) republishes the whole tree and re-syncs anything that had gone stale.
"""

from __future__ import annotations

import ftplib
import hashlib
import io
import json
import os
import posixpath
import random
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


# Remote-only bookkeeping file: path -> sha256 of the content last uploaded.
MANIFEST_NAME = ".ftp-sync-manifest.json"


def log(message: str) -> None:
    """Timestamped, unbuffered progress line.

    CI captures stdout as a block and flushes it when the step ends, so a run
    that hangs shows nothing until it dies and every line then carries the same
    useless end-of-step timestamp. Printing the clock ourselves and flushing
    makes the log usable while the run is still going.
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


class SyncFailure(RuntimeError):
    """Carries which step of the sync failed alongside the original error."""

    def __init__(self, phase: str, original: BaseException):
        super().__init__(f"{phase}: {type(original).__name__}: {original}")
        self.phase = phase
        self.original = original


def describe_host(host: str, port: int) -> None:
    """Log where the hostname points and whether the port answers.

    A host behind round-robin DNS can hand out one dead address, which looks
    exactly like the intermittent timeouts seen on 2026-08-09: same config,
    same code, works on one run and stalls on the next. Recording the address
    actually used makes that visible instead of guessable.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        log(f"DNS lookup for {host} failed: {exc}")
        return

    addresses = sorted({info[4][0] for info in infos})
    log(f"{host} resolves to: {', '.join(addresses)}")

    for address in addresses:
        started = time.monotonic()
        try:
            with socket.create_connection((address, port), timeout=15):
                elapsed = time.monotonic() - started
                log(f"  {address}:{port} accepted a connection in {elapsed:.1f}s")
        except OSError as exc:
            elapsed = time.monotonic() - started
            log(f"  {address}:{port} unreachable after {elapsed:.1f}s: {type(exc).__name__}: {exc}")


# Repo-root paths that should never be published to the web server.
# Matched as the first path segment of each tracked file.
EXCLUDED_TOP_LEVEL = {
    ".git",
    ".github",
    ".claude",
    ".venv",
    ".gitignore",
    ".python-version",
    "python",
    "scripts",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "node_modules",
    "tailwind.config.js",
    "README.md",
}

def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer.") from exc


def get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"Environment variable {name} must be a boolean.")


def run_git_command(args: list[str]) -> bytes:
    result = subprocess.run(args, check=True, capture_output=True)
    return result.stdout


def parse_null_separated_paths(blob: bytes) -> list[str]:
    text = blob.decode("utf-8", errors="surrogateescape")
    return [entry for entry in text.split("\0") if entry]


def get_tracked_files(repo_root: Path) -> list[str]:
    raw = run_git_command(["git", "ls-files", "-z"])
    files = []
    for rel_path in parse_null_separated_paths(raw):
        # First segment determines whether the path is publishable.
        first = rel_path.split("/", 1)[0]
        if first in EXCLUDED_TOP_LEVEL:
            continue
        candidate = (repo_root / rel_path).resolve()
        try:
            candidate.relative_to(repo_root)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        files.append(rel_path)
    return files


@dataclass
class RemoteEntry:
    name: str
    is_dir: bool
    size: int | None


def list_remote(ftp: ftplib.FTP_TLS, remote_dir: str) -> dict[str, RemoteEntry]:
    """Return {name: RemoteEntry} for the given remote directory.

    Uses MLSD when available (one round-trip for the whole listing) and falls
    back to NLST + per-file SIZE otherwise. Returns an empty dict if the
    directory doesn't exist.
    """
    entries: dict[str, RemoteEntry] = {}

    try:
        ftp.cwd(remote_dir)
    except ftplib.error_perm:
        return entries

    try:
        for name, facts in ftp.mlsd():
            if name in (".", ".."):
                continue
            entry_type = facts.get("type", "").lower()
            is_dir = entry_type in {"dir", "cdir", "pdir"}
            size_raw = facts.get("size")
            size = int(size_raw) if size_raw and size_raw.isdigit() else None
            entries[name] = RemoteEntry(name=name, is_dir=is_dir, size=size)
        return entries
    except ftplib.error_perm:
        # MLSD not supported — fall back to NLST + SIZE.
        pass

    names: list[str] = []
    try:
        ftp.retrlines("NLST", names.append)
    except ftplib.error_perm:
        return entries

    for raw in names:
        name = posixpath.basename(raw.strip())
        if name in (".", "..", ""):
            continue
        size: int | None = None
        is_dir = False
        try:
            size = ftp.size(name)
        except (ftplib.error_perm, ftplib.error_reply):
            # SIZE on a directory usually errors — treat as directory.
            is_dir = True

        entries[name] = RemoteEntry(name=name, is_dir=is_dir, size=size)

    return entries


def ensure_remote_dir(ftp: ftplib.FTP_TLS, remote_dir: str) -> None:
    normalized = posixpath.normpath(remote_dir)
    if normalized in {"", "."}:
        return

    parts = [part for part in normalized.split("/") if part]
    current = "/" if normalized.startswith("/") else ""

    for part in parts:
        if current == "":
            current = part
        elif current == "/":
            current = f"/{part}"
        else:
            current = f"{current}/{part}"

        try:
            ftp.mkd(current)
        except ftplib.error_perm as exc:
            message = str(exc).lower()
            if "exist" not in message and not message.startswith("550"):
                raise


def hash_file(local_path: Path) -> str:
    digest = hashlib.sha256()
    with local_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_remote_manifest(ftp: ftplib.FTP_TLS, remote_base: str) -> dict[str, str]:
    """Read the remote hash manifest. Missing/corrupt manifest == empty dict."""
    buffer = io.BytesIO()
    try:
        ftp.cwd(remote_base)
        ftp.retrbinary(f"RETR {MANIFEST_NAME}", buffer.write)
    except (ftplib.error_perm, ftplib.error_temp, OSError):
        return {}

    try:
        payload = json.loads(buffer.getvalue().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}

    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, dict):
        return {}
    return {k: v for k, v in files.items() if isinstance(k, str) and isinstance(v, str)}


def store_remote_manifest(ftp: ftplib.FTP_TLS, remote_base: str, manifest: dict[str, str]) -> None:
    payload = json.dumps({"version": 1, "files": manifest}, sort_keys=True).encode("utf-8")
    ftp.cwd(remote_base)
    ftp.storbinary(f"STOR {MANIFEST_NAME}", io.BytesIO(payload))


def needs_upload(
    local_path: Path,
    local_hash: str,
    known_hash: str | None,
    remote: RemoteEntry | None,
    force: bool,
) -> bool:
    if force or remote is None or remote.is_dir:
        return True
    if known_hash is None or known_hash != local_hash:
        # Never uploaded by a hash-aware run, or content changed since.
        return True
    try:
        local_size = local_path.stat().st_size
    except OSError:
        return True
    if remote.size is None:
        # No reliable remote size — be safe and re-upload.
        return True
    # Manifest agrees but the server disagrees: something changed out of band.
    return remote.size != local_size


def remote_path_join(*parts: str) -> str:
    cleaned = [p for p in parts if p not in ("", ".")]
    if not cleaned:
        return "/"
    joined = posixpath.normpath(posixpath.join(*cleaned))
    return joined


def delete_remote_tree(ftp: ftplib.FTP_TLS, remote_path: str) -> None:
    """Recursively delete a remote file or directory."""
    # Try file delete first — cheaper than detecting type.
    try:
        ftp.delete(remote_path)
        print(f"Deleted remote file: {remote_path}")
        return
    except ftplib.error_perm:
        pass

    # Treat as directory: enumerate, recurse, then rmd.
    parent, name = posixpath.split(remote_path)
    try:
        ftp.cwd(remote_path)
    except ftplib.error_perm:
        return

    children = list_remote(ftp, remote_path)
    for child_name, child in children.items():
        child_path = remote_path_join(remote_path, child_name)
        delete_remote_tree(ftp, child_path)

    try:
        ftp.cwd(parent if parent else "/")
    except ftplib.error_perm:
        pass
    try:
        ftp.rmd(remote_path)
        print(f"Deleted remote directory: {remote_path}")
    except ftplib.error_perm as exc:
        print(f"Could not remove remote directory {remote_path}: {exc}")


def build_local_tree(files: list[str]) -> dict[str, set[str]]:
    """Return {dir_path: {entry_names}} describing what *should* exist remotely.

    Dir paths are POSIX, relative to the remote base (empty string == base).
    Each entry is just a name (file or subdir); we recurse using the map.
    """
    tree: dict[str, set[str]] = {"": set()}
    for rel in files:
        parts = rel.replace("\\", "/").split("/")
        for depth in range(len(parts)):
            parent = "/".join(parts[:depth])
            entry = parts[depth]
            tree.setdefault(parent, set()).add(entry)
            if depth < len(parts) - 1:
                tree.setdefault("/".join(parts[: depth + 1]), set())
    return tree


def sync_directory(
    ftp: ftplib.FTP_TLS,
    repo_root: Path,
    remote_base: str,
    local_tree: dict[str, set[str]],
    rel_dir: str,
    stats: dict[str, int],
    force: bool,
    known_hashes: dict[str, str],
    new_hashes: dict[str, str],
) -> None:
    """Sync one directory level, then recurse into subdirectories."""
    remote_dir = remote_path_join(remote_base, rel_dir) if rel_dir else remote_base
    ensure_remote_dir(ftp, remote_dir)
    remote_entries = list_remote(ftp, remote_dir)
    # list_remote left us CWD'd into remote_dir, so subsequent STORs don't need
    # to re-issue CWD for each file.

    expected = local_tree.get(rel_dir, set())

    # 1. Delete remote entries that shouldn't be here.
    for name, entry in list(remote_entries.items()):
        if name in expected:
            continue
        if rel_dir == "" and name == MANIFEST_NAME:
            # Our own bookkeeping file — never tracked locally, never deleted.
            remote_entries.pop(name, None)
            continue
        target = remote_path_join(remote_dir, name)
        delete_remote_tree(ftp, target)
        remote_entries.pop(name, None)
        stats["deleted"] += 1
        # delete_remote_tree may have CWD'd elsewhere — restore.
        ftp.cwd(remote_dir)

    # 2. Upload / refresh files at this level.
    for name in expected:
        child_rel = f"{rel_dir}/{name}" if rel_dir else name
        local_path = repo_root / child_rel
        if local_path.is_file():
            remote_entry = remote_entries.get(name)
            if remote_entry and remote_entry.is_dir:
                # Remote has a directory where we want a file — remove it first.
                delete_remote_tree(ftp, remote_path_join(remote_dir, name))
                remote_entry = None
                stats["deleted"] += 1
                ftp.cwd(remote_dir)
            local_hash = hash_file(local_path)
            if needs_upload(local_path, local_hash, known_hashes.get(child_rel), remote_entry, force):
                with local_path.open("rb") as source:
                    ftp.storbinary(f"STOR {name}", source)
                stats["uploaded"] += 1
                print(f"Uploaded: {child_rel} -> {remote_dir}/{name}")
            else:
                stats["skipped"] += 1
            new_hashes[child_rel] = local_hash

    # 3. Recurse into subdirectories.
    for name in expected:
        child_rel = f"{rel_dir}/{name}" if rel_dir else name
        local_path = repo_root / child_rel
        if local_path.is_dir():
            remote_entry = remote_entries.get(name)
            if remote_entry and not remote_entry.is_dir:
                # Remote has a file where we want a directory — delete it.
                try:
                    ftp.delete(remote_path_join(remote_dir, name))
                    stats["deleted"] += 1
                except ftplib.error_perm:
                    pass
            sync_directory(
                ftp,
                repo_root,
                remote_base,
                local_tree,
                child_rel,
                stats,
                force,
                known_hashes,
                new_hashes,
            )


def sync_once(
    files: list[str],
    repo_root: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    remote_base: str,
    timeout_seconds: int,
    verify_certificate: bool,
    force: bool,
) -> dict[str, int]:
    context = ssl.create_default_context() if verify_certificate else ssl._create_unverified_context()
    ftp = ftplib.FTP_TLS(timeout=timeout_seconds, context=context)
    stats = {"uploaded": 0, "skipped": 0, "deleted": 0}
    phase = "connect"
    try:
        try:
            log(f"connecting to {host}:{port} (timeout {timeout_seconds}s)")
            ftp.connect(host=host, port=port)

            phase = "tls-handshake"
            log("negotiating TLS")
            ftp.auth()

            phase = "login"
            log("logging in")
            ftp.login(user=user, passwd=password)

            phase = "protect-data-channel"
            ftp.prot_p()

            phase = "read-manifest"
            log(f"reading {MANIFEST_NAME}")
            known_hashes = load_remote_manifest(ftp, remote_base)
            if not known_hashes:
                log(f"No usable {MANIFEST_NAME} on the server — republishing every file this run.")

            phase = "sync"
            log("mirroring tree")
            new_hashes: dict[str, str] = {}
            local_tree = build_local_tree(files)
            sync_directory(
                ftp,
                repo_root,
                remote_base,
                local_tree,
                "",
                stats,
                force,
                known_hashes,
                new_hashes,
            )

            phase = "write-manifest"
            # Only after a complete pass, so a mid-run failure can't record
            # hashes for files that never made it to the server.
            store_remote_manifest(ftp, remote_base, new_hashes)
        except Exception as exc:
            # Which step hung matters: a stall in `connect` or `tls-handshake`
            # is the network or the host refusing us, while one in `sync` is a
            # transfer that died partway. The bare message never said which.
            raise SyncFailure(phase, exc) from exc
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    return stats


def main() -> int:
    repo_root = Path.cwd().resolve()

    host = get_required_env("FTP_HOST")
    user = get_required_env("FTP_USER")
    password = get_required_env("FTP_PASSWORD")
    remote_dir = get_required_env("FTP_REMOTE_DIR")
    port = get_int_env("FTP_PORT", 21)

    timeout_seconds = get_int_env("FTP_TIMEOUT_SECONDS", 60)
    max_retries = get_int_env("FTP_MAX_RETRIES", 10)
    retry_delay_seconds = get_int_env("FTP_RETRY_DELAY_SECONDS", 5)
    retry_max_delay_seconds = get_int_env("FTP_RETRY_MAX_DELAY_SECONDS", 300)
    verify_certificate = get_bool_env("FTP_VERIFY_CERTIFICATE", False)
    force = get_bool_env("FTP_FORCE", False)

    remote_base = remote_dir.rstrip("/")
    if not remote_base:
        remote_base = "/"

    files = get_tracked_files(repo_root)
    if not files:
        print("No tracked publishable files found — refusing to sync.")
        return 1

    mode = "force-republish" if force else "hash-diff"
    log(f"Mirroring {len(files)} tracked files to {host}:{port}{remote_base} ({mode}) ...")
    describe_host(host, port)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        attempt_started = time.monotonic()
        try:
            stats = sync_once(
                files=files,
                repo_root=repo_root,
                host=host,
                port=port,
                user=user,
                password=password,
                remote_base=remote_base,
                timeout_seconds=timeout_seconds,
                verify_certificate=verify_certificate,
                force=force,
            )
            log(
                "FTP mirror completed: "
                f"{stats['uploaded']} uploaded, "
                f"{stats['skipped']} unchanged, "
                f"{stats['deleted']} deleted."
            )
            return 0
        except Exception as exc:
            last_error = exc
            elapsed = time.monotonic() - attempt_started
            log(f"Sync attempt {attempt}/{max_retries} failed after {elapsed:.0f}s: {exc}")
            if attempt >= max_retries:
                break
            # Back off exponentially: when the server refuses connections it is
            # usually holding a dead session or throttling us, and neither
            # clears within the couple of seconds a flat delay would wait.
            # Jitter keeps the scheduled and push-triggered runs from lining up.
            delay = min(retry_delay_seconds * 2 ** (attempt - 1), retry_max_delay_seconds)
            delay += random.uniform(0, delay * 0.25)
            log(f"Retrying in {delay:.0f} seconds...")
            time.sleep(delay)

    if isinstance(last_error, SyncFailure) and last_error.phase in {"connect", "tls-handshake"}:
        # Every attempt died before we ever spoke FTP — re-probe so the log ends
        # with the state of the host rather than another anonymous timeout.
        log("All attempts failed before the FTP session opened. Re-probing host:")
        describe_host(host, port)

    raise RuntimeError(f"FTP mirror failed after {max_retries} attempts: {last_error}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
