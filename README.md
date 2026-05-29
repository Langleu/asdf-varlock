# asdf-varlock

`asdf` plugin for installing the official [Varlock](https://github.com/dmno-dev/varlock) CLI from GitHub Releases.

This plugin follows the shell-based layout from the [asdf plugin template](https://github.com/asdf-vm/asdf-plugin-template/tree/main): `bin/list-all`, `bin/latest-stable`, `bin/download`, and `bin/install` are all implemented in shell.

## Install

Add the plugin from the published repository:

```sh
asdf plugin add varlock https://github.com/Langleu/asdf-varlock.git
asdf install varlock latest
asdf global varlock latest
```

## What it installs

This plugin installs the standalone `varlock` CLI from GitHub Releases.

## Supported platforms

- macOS `x86_64`
- macOS `arm64`
- Linux `x86_64`
- Linux `arm64`
- Linux musl `x86_64`
- Linux musl `arm64`

## Requirements

- `bash`
- `curl`
- `git`
- `tar`
- `sha256sum` or `shasum`

## Links

- [Varlock installation docs](https://varlock.dev/getting-started/installation/)
- [Varlock CLI reference](https://varlock.dev/reference/cli-commands/)
- [Varlock releases](https://github.com/dmno-dev/varlock/releases)
- [asdf plugin creation guide](https://asdf-vm.com/plugins/create.html)
- [asdf plugin template](https://github.com/asdf-vm/asdf-plugin-template/tree/main)

## Notes

- Version discovery comes from GitHub release tags.
- The plugin normalizes release tags like `v1.3.0` and `varlock@1.3.0` to plain semantic versions.
- Downloads are verified with the release `checksums.txt` asset when available.
