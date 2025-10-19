## Debian Package

Package metadata for building `.deb` releases.

On tagged releases, GitHub Actions builds the Debian package and standalone script, then attaches both to the release.

### For users

**Latest version:**

Debian/Ubuntu:
```bash
curl -fsSL https://github.com/james-akl/xiv/releases/latest/download/xiv.deb -o xiv.deb
sudo dpkg -i xiv.deb
```

Other systems:
```bash
curl -fsSL https://github.com/james-akl/xiv/releases/latest/download/xiv -o xiv
chmod +x xiv
sudo mv xiv /usr/local/bin/
```

**Specific version** (e.g., v1.0.1):

Debian/Ubuntu:
```bash
curl -fsSL https://github.com/james-akl/xiv/releases/download/v1.0.1/xiv.deb -o xiv.deb
sudo dpkg -i xiv.deb
```

Other systems:
```bash
curl -fsSL https://github.com/james-akl/xiv/releases/download/v1.0.1/xiv -o xiv
chmod +x xiv
sudo mv xiv /usr/local/bin/
```

Uninstall: `sudo dpkg -r xiv` (Debian) or `sudo rm /usr/local/bin/xiv` (other)

### Releasing

1. Update version in `xiv.py` and `debian/DEBIAN/control`
2. Commit and tag: `git tag v1.0.1 && git push --tags`
3. GitHub Actions builds and attaches to release automatically
