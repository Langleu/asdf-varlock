#!/usr/bin/env bash

set -euo pipefail

GH_REPO="https://github.com/dmno-dev/varlock"
TOOL_NAME="varlock"
TOOL_TEST="varlock --help"

fail() {
	echo -e "asdf-$TOOL_NAME: $*" >&2
	exit 1
}

curl_opts=(-fsSL)

if [ -n "${GITHUB_API_TOKEN:-}" ]; then
	curl_opts+=(-H "Authorization: token $GITHUB_API_TOKEN")
fi

sort_versions() {
	sed 'h; s/[+-]/./g; s/.p\([[:digit:]]\)/.z\1/; s/$/.z/; G; s/\n/ /' |
		LC_ALL=C sort -t. -k 1,1 -k 2,2n -k 3,3n -k 4,4n -k 5,5n |
		awk '{print $2}'
}

list_github_tags() {
	git ls-remote --tags --refs "$GH_REPO" |
		awk '{print $2}' |
		sed -n -e 's|refs/tags/varlock@||p' -e 's|refs/tags/v||p' |
		awk '/^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$/ { print }'
}

list_all_versions() {
	list_github_tags
}

release_tag_for_version() {
	printf 'varlock@%s' "$1"
}

encode_release_tag() {
	printf '%s' "$1" | sed 's/@/%40/g'
}

release_url_for_asset() {
	local version="$1"
	local asset_name="$2"
	local tag_url

	tag_url="$(encode_release_tag "$(release_tag_for_version "$version")")"
	printf '%s/releases/download/%s/%s' "$GH_REPO" "$tag_url" "$asset_name"
}

platform_name() {
	case "$(uname -s)" in
		Darwin) printf 'macos' ;;
		Linux) printf 'linux' ;;
		*) fail "Unsupported operating system: $(uname -s)" ;;
	esac
}

arch_name() {
	case "$(uname -m)" in
		x86_64 | amd64) printf 'x64' ;;
		arm64 | aarch64) printf 'arm64' ;;
		*) fail "Unsupported architecture: $(uname -m)" ;;
	esac
}

is_musl() {
	if [ "$(platform_name)" != "linux" ]; then
		return 1
	fi

	if command -v ldd >/dev/null 2>&1 && ldd --version 2>&1 | grep -qi musl; then
		return 0
	fi

	case "$(uname -m)" in
		x86_64 | amd64)
			[ -e /lib/ld-musl-x86_64.so.1 ] && return 0
			;;
		arm64 | aarch64)
			[ -e /lib/ld-musl-aarch64.so.1 ] && return 0
			[ -e /lib/ld-musl-arm64.so.1 ] && return 0
			;;
	esac

	return 1
}

asset_name_for_current_platform() {
	local platform arch

	platform="$(platform_name)"
	arch="$(arch_name)"

	case "$platform" in
		macos) printf 'varlock-macos-%s.tar.gz' "$arch" ;;
		linux)
			if is_musl; then
				printf 'varlock-linux-musl-%s.tar.gz' "$arch"
			else
				printf 'varlock-linux-%s.tar.gz' "$arch"
			fi
			;;
		*) fail "Unsupported platform: $platform" ;;
	esac
}

download_release_asset() {
	local version="$1"
	local asset_name="$2"
	local filename="$3"
	local url

	url="$(release_url_for_asset "$version" "$asset_name")"
	printf '* Downloading %s release %s (%s)...\n' "$TOOL_NAME" "$version" "$asset_name"
	curl "${curl_opts[@]}" -o "$filename" -C - "$url" || fail "Could not download $url"
}

maybe_download_checksums() {
	local version="$1"
	local checksum_file="$2"
	local url

	url="$(release_url_for_asset "$version" checksums.txt)"
	if curl "${curl_opts[@]}" -o "$checksum_file" -C - "$url"; then
		return 0
	fi

	rm -f "$checksum_file"
	return 1
}

verify_checksum() {
	local checksum_file="$1"
	local asset_name="$2"
	local release_file="$3"
	local expected_checksum actual_checksum

	expected_checksum="$(awk -v name="$asset_name" '$2 == name { print $1; exit }' "$checksum_file")"
	if [ -z "$expected_checksum" ]; then
		fail "No checksum entry found for $asset_name in $checksum_file"
	fi

	if command -v sha256sum >/dev/null 2>&1; then
		actual_checksum="$(sha256sum "$release_file" | awk '{print $1}')"
	elif command -v shasum >/dev/null 2>&1; then
		actual_checksum="$(shasum -a 256 "$release_file" | awk '{print $1}')"
	else
		fail "Neither sha256sum nor shasum is available"
	fi

	if [ "$actual_checksum" != "$expected_checksum" ]; then
		fail "Checksum mismatch for $asset_name"
	fi
}

extract_release() {
	local release_file="$1"
	local download_path="$2"

	tar -xzf "$release_file" -C "$download_path" || fail "Could not extract $release_file"
}

version_exists() {
	local version="$1"

	list_all_versions | grep -Fxq "$version"
}

resolve_install_version() {
	local requested_version="$1"

	case "$requested_version" in
		latest | latest-stable)
			latest_stable
			return 0
			;;
	esac

	if version_exists "$requested_version"; then
		printf '%s\n' "$requested_version"
		return 0
	fi

	local fallback_version
	fallback_version="$(latest_stable)"
	printf 'Requested Varlock version %s was not published; installing latest stable %s instead.\n' \
		"$requested_version" "$fallback_version" >&2
	printf '%s\n' "$fallback_version"
}

latest_stable() {
	list_all_versions | sort_versions | tail -n1 | xargs echo
}

download_version() {
	local requested_version="$1"
	local version asset_name release_file checksum_file

	version="$(resolve_install_version "$requested_version")"
	asset_name="$(asset_name_for_current_platform)"
	release_file="$ASDF_DOWNLOAD_PATH/$asset_name"
	checksum_file="$ASDF_DOWNLOAD_PATH/checksums.txt"

	mkdir -p "$ASDF_DOWNLOAD_PATH"
	download_release_asset "$version" "$asset_name" "$release_file"

	if maybe_download_checksums "$version" "$checksum_file"; then
		verify_checksum "$checksum_file" "$asset_name" "$release_file"
		rm -f "$checksum_file"
	fi

	extract_release "$release_file" "$ASDF_DOWNLOAD_PATH"
	rm -f "$release_file"
}

install_version() {
	local install_type="$1"
	local version="$2"
	local install_path="${3%/bin}/bin"

	if [ "$install_type" != "version" ]; then
		fail "asdf-$TOOL_NAME supports release installs only"
	fi

	(
		mkdir -p "$install_path"
		cp -r "$ASDF_DOWNLOAD_PATH"/* "$install_path"

		local tool_cmd
		tool_cmd="$(printf '%s' "$TOOL_TEST" | cut -d' ' -f1)"
		test -x "$install_path/$tool_cmd" || fail "Expected $install_path/$tool_cmd to be executable."

		printf '%s %s installation was successful!\n' "$TOOL_NAME" "$version"
	) || (
		rm -rf "$install_path"
		fail "An error occurred while installing $TOOL_NAME $version."
	)
}
