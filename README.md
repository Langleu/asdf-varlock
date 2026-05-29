# asdf-varlock

`asdf` plugin for installing the official [Varlock](https://github.com/dmno-dev/varlock) CLI from GitHub Releases.

## Install

Add the plugin from the published repository:

```sh
asdf plugin add varlock https://github.com/Langleu/asdf-varlock.git
asdf install varlock latest
asdf global varlock latest
```

## What it installs

This plugin installs the standalone `varlock` binary, not the npm package.

## Supported platforms

- macOS `x86_64`
- macOS `arm64`
- Linux `x86_64`
- Linux `arm64`

## Requirements

- `python3`

## Links

- [Varlock installation docs](https://varlock.dev/getting-started/installation/)
- [Varlock CLI reference](https://varlock.dev/reference/cli-commands/)
- [Varlock releases](https://github.com/dmno-dev/varlock/releases)
- [asdf plugin creation guide](https://asdf-vm.com/plugins/create.html)

## Notes

- Version discovery comes from GitHub Releases.
- The plugin normalizes release tags like `v1.3.0` and `varlock@1.3.0` to plain semantic versions.
- The release download is verified with the SHA-256 digest from GitHub release metadata when available.
