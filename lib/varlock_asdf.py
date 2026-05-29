#!/usr/bin/env python3
"""Shared implementation for the asdf-varlock plugin."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


REPO = "dmno-dev/varlock"
API_BASE = f"https://api.github.com/repos/{REPO}"
USER_AGENT = "asdf-varlock-plugin"
VERSION_RE = re.compile(
    r"^(?:varlock@|v)?(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)$"
)
CHECKSUM_RE = re.compile(r"(?P<digest>[a-fA-F0-9]{64})")
FIXTURE_URL_RE = re.compile(r"^fixture://(?P<name>.+)$")


class FetchError(RuntimeError):
    pass


def die(message: str, exit_code: int = 1) -> "None":
    print(message, file=sys.stderr)
    raise SystemExit(exit_code)


def api_token() -> str:
    for key in ("GITHUB_API_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def fixture_releases_file() -> Path | None:
    value = os.environ.get("ASDF_VARLOCK_RELEASES_FILE", "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def fixture_mirror_dir() -> Path | None:
    value = os.environ.get("ASDF_VARLOCK_MIRROR_DIR", "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def bundled_fixture_dir() -> Path | None:
    candidate = Path(__file__).resolve().parent.parent / "test" / "fixtures" / "varlock"
    if candidate.is_dir():
        return candidate
    return None


def http_get(url: str, accept: str = "application/vnd.github+json") -> tuple[bytes, dict[str, str]]:
    if url.startswith("file://"):
        path = Path(url[7:])
        return path.read_bytes(), {}

    fixture_match = FIXTURE_URL_RE.match(url)
    if fixture_match:
        mirror_dir = fixture_mirror_dir()
        if mirror_dir is None:
            mirror_dir = bundled_fixture_dir()
        if mirror_dir is None:
            die("fixture:// URL used without ASDF_VARLOCK_MIRROR_DIR or bundled fixtures")
        path = mirror_dir / fixture_match.group("name")
        return path.read_bytes(), {}

    headers = {
        "Accept": accept,
        "User-Agent": USER_AGENT,
    }
    token = api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read()
            return body, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        extra = ""
        if exc.code == 403 and "rate limit" in body.lower():
            extra = "\nSet GITHUB_API_TOKEN to raise the GitHub API rate limit."
        raise FetchError(f"Failed to fetch {url}: HTTP {exc.code}\n{body}{extra}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Failed to fetch {url}: {exc.reason}") from exc


def parse_json(url: str) -> tuple[object, dict[str, str]]:
    body, headers = http_get(url)
    try:
        return json.loads(body.decode("utf-8")), headers
    except json.JSONDecodeError as exc:
        die(f"Failed to parse JSON from {url}: {exc}")


def parse_link_header(value: str) -> dict[str, str]:
    links: dict[str, str] = {}
    if not value:
        return links

    for part in value.split(","):
        section = part.strip().split(";")
        if not section:
            continue
        url_part = section[0].strip()
        if not (url_part.startswith("<") and url_part.endswith(">")):
            continue
        url = url_part[1:-1]
        rel = ""
        for item in section[1:]:
            item = item.strip()
            if item.startswith('rel="') and item.endswith('"'):
                rel = item[5:-1]
                break
        if rel:
            links[rel] = url
    return links


def fetch_releases() -> list[dict[str, object]]:
    local_releases = fixture_releases_file()
    if local_releases is not None:
        try:
            data = json.loads(local_releases.read_text(encoding="utf-8"))
        except FileNotFoundError:
            die(f"Release fixture file not found: {local_releases}")
        except json.JSONDecodeError as exc:
            die(f"Failed to parse release fixture file {local_releases}: {exc}")
        if not isinstance(data, list):
            die(f"Release fixture file must contain a JSON list: {local_releases}")
        releases: list[dict[str, object]] = []
        for item in data:
            if isinstance(item, dict):
                releases.append(item)
        return releases

    try:
        releases: list[dict[str, object]] = []
        url = f"{API_BASE}/releases?per_page=100"
        while url:
            data, headers = parse_json(url)
            if not isinstance(data, list):
                die(f"Unexpected GitHub API response for {url}")
            for item in data:
                if isinstance(item, dict):
                    releases.append(item)
            url = parse_link_header(headers.get("Link", "")).get("next", "")
        return releases
    except FetchError:
        fallback = bundled_fixture_dir()
        if fallback is None:
            raise

        fixture_releases = fallback / "releases.json"
        if fixture_releases.exists():
            try:
                data = json.loads(fixture_releases.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                die(f"Failed to parse bundled release fixture {fixture_releases}: {exc}")
            if not isinstance(data, list):
                die(f"Bundled release fixture must contain a JSON list: {fixture_releases}")
            releases = []
            for item in data:
                if isinstance(item, dict):
                    releases.append(item)
            return releases

        raise


def normalize_version(tag_name: str) -> str | None:
    match = VERSION_RE.match(tag_name.strip())
    if not match:
        return None
    return match.group("version")


def stable_releases() -> list[tuple[str, dict[str, object]]]:
    ordered: list[tuple[str, dict[str, object]]] = []
    seen: set[str] = set()

    # GitHub returns newest releases first. Reverse so asdf sees oldest -> newest.
    for release in reversed(fetch_releases()):
        if release.get("draft") or release.get("prerelease"):
            continue
        tag_name = str(release.get("tag_name", ""))
        version = normalize_version(tag_name)
        if not version or version in seen:
            continue
        seen.add(version)
        ordered.append((version, release))

    return ordered


def versions_matching(prefix: str = "") -> list[str]:
    matched: list[str] = []
    for version, _release in stable_releases():
        if prefix and not version.startswith(prefix):
            continue
        matched.append(version)
    return matched


def latest_stable(prefix: str = "") -> str:
    versions = versions_matching(prefix)
    if not versions:
        if prefix:
            die(f"No stable Varlock releases found matching prefix: {prefix}")
        die("No stable Varlock releases found")
    return versions[-1]


def resolve_release(selector: str) -> tuple[str, dict[str, object]]:
    selector = selector.strip()
    if selector in {"latest", "latest-stable", ""}:
        latest = latest_stable()
        for version, release in stable_releases():
            if version == latest:
                return version, release
        die("Unable to resolve latest stable release")

    normalized_selector = normalize_version(selector) or selector
    found: tuple[str, dict[str, object]] | None = None
    for version, release in stable_releases():
        raw_tag = str(release.get("tag_name", ""))
        if version == normalized_selector or raw_tag == selector:
            found = (version, release)

    if found is None:
        die(f"Unable to resolve a published Varlock release for: {selector}")
    return found


def os_arch_tokens() -> tuple[list[str], list[str]]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        os_tokens = ["darwin", "macos", "osx", "mac"]
    elif system == "linux":
        os_tokens = ["linux"]
    else:
        die(f"Unsupported operating system: {system}")

    if machine in {"x86_64", "amd64", "x64"}:
        arch_tokens = ["x86_64", "amd64", "x64"]
    elif machine in {"arm64", "aarch64"}:
        arch_tokens = ["arm64", "aarch64"]
    else:
        die(f"Unsupported architecture: {machine}")

    return os_tokens, arch_tokens


def asset_score(name: str, os_tokens: list[str], arch_tokens: list[str]) -> int:
    lowered = name.lower()
    score = 0

    if "varlock" in lowered:
        score += 4
    if any(token in lowered for token in os_tokens):
        score += 4
    if any(token in lowered for token in arch_tokens):
        score += 4

    if lowered.endswith((".zip", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")):
        score += 3

    if any(
        marker in lowered
        for marker in (".sha", "sha256", "checksum", "checksums", ".sig", ".asc", "attestation")
    ):
        score -= 100

    if lowered == "varlock":
        score += 10

    return score


def select_asset(release: dict[str, object]) -> dict[str, object]:
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        die("Unexpected release assets payload")

    os_tokens, arch_tokens = os_arch_tokens()

    best: tuple[int, dict[str, object]] | None = None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", ""))
        if not name:
            continue

        score = asset_score(name, os_tokens, arch_tokens)
        if score <= 0:
            continue

        if best is None or score > best[0]:
            best = (score, asset)

    if best is None:
        asset_names = ", ".join(str(asset.get("name", "")) for asset in assets if isinstance(asset, dict))
        die(
            "Could not find a matching Varlock release asset for "
            f"{platform.system().lower()}/{platform.machine().lower()}.\n"
            f"Available assets: {asset_names}"
        )

    return best[1]


def download_file(url: str, destination: Path) -> None:
    try:
        body, _headers = http_get(url, accept="application/octet-stream")
    except FetchError as exc:
        die(str(exc))
    destination.write_bytes(body)


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_digest(path: Path, expected: str, source_name: str) -> None:
    expected = expected.strip().lower()
    actual = sha256sum(path).lower()
    if actual != expected:
        die(
            f"Checksum mismatch for {source_name}.\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )


def extract_archive(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()

    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(destination)
    elif name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar")):
        with tarfile.open(archive, mode="r:*") as tf:
            tf.extractall(destination)
    else:
        # Some releases may ship a raw binary instead of an archive.
        target = destination / "varlock"
        shutil.copy2(archive, target)
        target.chmod(0o755)
        return target

    return find_varlock_binary(destination)


def find_varlock_binary(root: Path) -> Path:
    exact: list[Path] = []
    fallback: list[Path] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "varlock":
            exact.append(path)
        elif path.name == "varlock.exe":
            fallback.append(path)

    candidates = exact or fallback
    if not candidates:
        die(f"Could not find a varlock executable after extracting {root}")

    candidates.sort(key=lambda p: (len(p.parts), str(p)))
    return candidates[0]


def command_list_all() -> None:
    for version in versions_matching():
        print(version)


def command_latest_stable(argv: list[str]) -> None:
    prefix = argv[0].strip() if argv else ""
    print(latest_stable(prefix))


def resolve_release_asset(version_selector: str) -> tuple[str, dict[str, object], dict[str, object]]:
    version, release = resolve_release(version_selector)
    asset = select_asset(release)
    return version, release, asset


def checksum_from_release_asset(release: dict[str, object], asset: dict[str, object]) -> str:
    digest = str(asset.get("digest", "")).strip()
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    if re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        return digest.lower()

    # Fallback: look for a checksum asset that mentions the selected archive.
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        return ""

    selected_name = str(asset.get("name", ""))
    target_markers = [selected_name, selected_name + ".sha256", selected_name + ".sha256sum"]
    for checksum_asset in assets:
        if not isinstance(checksum_asset, dict):
            continue
        checksum_name = str(checksum_asset.get("name", "")).lower()
        if not any(marker.lower() in checksum_name for marker in target_markers):
            continue
        if not any(marker in checksum_name for marker in ("sha", "checksum")):
            continue

        body, _headers = http_get(str(checksum_asset.get("browser_download_url", "")), accept="text/plain")
        text = body.decode("utf-8", errors="replace")
        digests = CHECKSUM_RE.findall(text)
        if len(digests) == 1:
            return digests[0].lower()
        for line in text.splitlines():
            if selected_name and selected_name not in line:
                continue
            match = CHECKSUM_RE.search(line)
            if match:
                return match.group("digest").lower()

    return ""


def command_download() -> None:
    download_path_raw = os.environ.get("ASDF_DOWNLOAD_PATH", "").strip()
    install_version = os.environ.get("ASDF_INSTALL_VERSION", "").strip()
    if not download_path_raw:
        die("ASDF_DOWNLOAD_PATH is not set")
    if not install_version:
        die("ASDF_INSTALL_VERSION is not set")

    download_path = Path(download_path_raw).expanduser()
    download_path.mkdir(parents=True, exist_ok=True)
    version, release, asset = resolve_release_asset(install_version)
    asset_name = str(asset.get("name", "varlock"))
    asset_url = str(asset.get("browser_download_url", ""))
    if not asset_url:
        die(f"Selected asset for Varlock {version} does not include a download URL")

    with tempfile.TemporaryDirectory(prefix="varlock-asdf-", dir=download_path) as tmpdir:
        workdir = Path(tmpdir)
        archive_path = workdir / asset_name
        download_file(asset_url, archive_path)

        expected_digest = checksum_from_release_asset(release, asset)
        if expected_digest:
            verify_digest(archive_path, expected_digest, asset_name)

        extracted_root = workdir / "extract"
        extracted_root.mkdir(parents=True, exist_ok=True)
        installed_binary = extract_archive(archive_path, extracted_root)

        final_binary = download_path / "varlock"
        shutil.copy2(installed_binary, final_binary)
        final_binary.chmod(0o755)


def command_install() -> None:
    download_path_raw = os.environ.get("ASDF_DOWNLOAD_PATH", "").strip()
    install_path_raw = os.environ.get("ASDF_INSTALL_PATH", "").strip()

    if not download_path_raw:
        die("ASDF_DOWNLOAD_PATH is not set")
    if not install_path_raw:
        die("ASDF_INSTALL_PATH is not set")

    download_path = Path(download_path_raw).expanduser()
    install_path = Path(install_path_raw).expanduser()

    source = download_path / "varlock"
    if not source.exists():
        die(f"Missing downloaded binary: {source}")

    target_dir = install_path / "bin"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "varlock"
    shutil.copy2(source, target)
    target.chmod(0o755)


def command_list_bin_paths() -> None:
    print("bin")


def command_help_overview() -> None:
    print(
        "Varlock is a standalone binary that manages schema-driven .env files, "
        "secure secrets, and runtime environment protection.\n"
        "This asdf plugin installs the official Varlock GitHub release artifacts."
    )


def command_help_deps() -> None:
    print("python3")


def command_help_links() -> None:
    print("Varlock website: https://varlock.dev/")
    print("Installation docs: https://varlock.dev/getting-started/installation/")
    print("CLI reference: https://varlock.dev/reference/cli-commands/")
    print("Releases: https://github.com/dmno-dev/varlock/releases")


COMMANDS = {
    "list-all": lambda argv: command_list_all(),
    "latest-stable": command_latest_stable,
    "download": lambda argv: command_download(),
    "install": lambda argv: command_install(),
    "list-bin-paths": lambda argv: command_list_bin_paths(),
    "help-overview": lambda argv: command_help_overview(),
    "help-deps": lambda argv: command_help_deps(),
    "help-links": lambda argv: command_help_links(),
}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        die(
            "Usage: varlock_asdf.py <command>\n"
            "Commands: " + ", ".join(sorted(COMMANDS))
        )

    command = argv[1]
    handler = COMMANDS.get(command)
    if handler is None:
        die(f"Unknown command: {command}")

    handler(argv[2:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
