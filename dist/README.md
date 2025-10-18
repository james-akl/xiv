## APT Repository

Debian package metadata for self-hosted APT repository.

On tagged releases, GitHub Actions builds the .deb and deploys an APT repo to GitHub Pages.

### User installation

```bash
echo "deb [trusted=yes] https://james-akl.github.io/xiv stable main" | sudo tee /etc/apt/sources.list.d/xiv.list
sudo apt update
sudo apt install xiv
```

### Release process

1. Update version in `xiv.py` and `debian/DEBIAN/control`
2. Tag: `git tag v1.0.0 && git push --tags`
3. GitHub Actions deploys automatically
