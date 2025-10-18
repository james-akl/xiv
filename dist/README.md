## Debian Package

Debian package metadata. On tagged releases, GitHub Actions builds the .deb and attaches it to the release.

### Installation

Download and install the latest .deb from [Releases](https://github.com/james-akl/xiv/releases):

```bash
curl -fsSL https://github.com/james-akl/xiv/releases/latest/download/xiv_1.0.0_all.deb -o xiv.deb
sudo dpkg -i xiv.deb
```

### Release process

1. Update version in `xiv.py` and `debian/DEBIAN/control`
2. Tag: `git tag v1.0.0 && git push --tags`
3. GitHub Actions builds and attaches .deb to release
