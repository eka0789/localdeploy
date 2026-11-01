"""Git operations via the git CLI (argument lists only — never shell=True)."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from ..core.config import settings


@dataclass
class GitResult:
    commit_sha: str
    commit_message: str
    branch: str


class GitError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path | None = None, env_extra: dict | None = None) -> str:
    # Pass the parent environment through (proxy, SSL certs, DNS settings) and
    # only override what git needs to stay non-interactive.
    import os

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
    if env_extra:
        env.update(env_extra)
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=settings.git_clone_timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out") from exc
    except FileNotFoundError as exc:
        raise GitError("git executable not found on the host") from exc
    if result.returncode != 0:
        raise GitError(redact_url(result.stderr.strip() or f"git {args[0]} failed"))
    return result.stdout.strip()


def redact_url(text: str) -> str:
    """Strip credentials from any URL found in git output before logging."""
    return re.sub(r"(https?://)[^@/\s]+@", r"\1", text)


def build_authenticated_url(url: str, username: str | None, password: str | None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not (username or password):
        return url
    netloc = parsed.netloc
    auth = username or ""
    if password:
        auth += f":{password}"
    return urlunparse(parsed._replace(netloc=f"{auth}@{netloc}"))


def clone(
    url: str,
    branch: str | None,
    dest: Path,
    username: str | None = None,
    password: str | None = None,
    commit: str | None = None,
) -> GitResult:
    """Shallow clone into `dest`. Returns the checked-out commit info."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _rmtree(dest)
    authed = build_authenticated_url(url, username, password)
    args = ["clone", "--quiet", "--depth", "1", "--single-branch"]
    if branch:
        args += ["--branch", branch]
    args += [authed, str(dest)]
    try:
        _run(args)
    except GitError as exc:
        raise GitError(f"clone failed: {exc}") from exc

    if commit:  # shallow clone may not contain the requested commit
        _run(["fetch", "--quiet", "--unshallow"], cwd=dest)
        _run(["checkout", "--quiet", commit], cwd=dest)

    sha = _run(["rev-parse", "HEAD"], cwd=dest)
    message = _run(["log", "-1", "--pretty=%s"], cwd=dest)
    branch_name = branch or "default"
    return GitResult(commit_sha=sha, commit_message=message, branch=branch_name)


def extract_upload_archive(archive_path: Path, dest: Path) -> None:
    """Extract an uploaded .zip/.tar.gz source archive into `dest`."""
    import shutil
    import tarfile
    import zipfile

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _rmtree(dest)
    dest.mkdir(parents=True)
    name = archive_path.name.lower()
    try:
        if name.endswith((".zip",)):
            with zipfile.ZipFile(archive_path) as zf:
                _safe_zip_extract(zf, dest)
        elif name.endswith((".tar.gz", ".tgz", ".tar")):
            with tarfile.open(archive_path) as tf:
                tf.extractall(dest, filter="data")
        else:
            raise GitError("Unsupported archive type. Use .zip, .tar.gz or .tgz")
    except (zipfile.BadZipFile, tarfile.TarError) as exc:
        raise GitError(f"Invalid archive: {exc}") from exc

    # If everything is inside a single top-level folder, unwrap it.
    entries = list(dest.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        top = entries[0]
        tmp = dest.parent / (dest.name + "-unwrapped")
        shutil.move(str(top), str(tmp))
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(tmp), str(dest))


def _safe_zip_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not str(target).startswith(str(dest.resolve())):
            raise GitError("Archive contains unsafe path traversal entries")
    zf.extractall(dest)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
