# Releasing

1. Update `VERSION` and `CHANGELOG.md` (`## [X.Y.Z] - date`). Merge to `main`.
2. Tag and push the tag: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.
3. Build in a clean Arch environment (container, or `extra-x86_64-build` from `devtools`):

   ```bash
   cd packaging/arch
   extra-x86_64-build        # runs check(): the test suite, no network, temporary HOME
   ```

4. Lint the package: `namcap PKGBUILD` and `namcap *.pkg.tar.zst`.
5. Verify the generated units with systemd. Create a mapping whose folder contains a space, a quote and a `%`, schedule it in the GUI, then:

   ```bash
   systemd-analyze --user verify ~/.config/systemd/user/proton-sync.service
   systemctl --user cat proton-sync.service   # ExecStart=/usr/bin/proton-drive-sync, quoted paths
   ```

6. Install on a test machine (`makepkg -si`) and run `proton-drive-sync-doctor --redact`.
7. Optional AUR update: copy `PKGBUILD` and `proton-drive-cli-sync-git.install`, run `makepkg --printsrcinfo > .SRCINFO`, commit and push to `ssh://aur@aur.archlinux.org/proton-drive-cli-sync-git.git`.
8. Announce the release. This project is not affiliated with Proton AG.
