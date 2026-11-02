# Release artifacts

The CI workflow builds distributions on pull requests, main pushes, `release/v*` branch pushes,
and `v*` tag pushes.
`python -m build` creates an sdist and builds the wheel from that sdist in an isolated
build environment. Both distributions pass strict metadata checks and are installed
in separate virtual environments outside the checkout. The installed CLI must produce
a PASS result that validates against the installed result schema.

Publication depends on the complete Linux Python matrix, Windows tests, minimum
runtime, optional MF4 jobs, package checks and final gate in the same workflow run.
The release job downloads that run's artifacts and verifies SHA256SUMS before
attaching the wheel, sdist and checksums using `--verify-tag`. It never uploads to PyPI.

To publish a reviewed main commit:

1. Set the intended release version in both `pyproject.toml` and `CITATION.cff`.
   Development versions are rejected.
2. Finalize CHANGELOG.md and `docs/releases/vVERSION.md`; refresh the README preview
   if the report changed. The curated notes are prepended to generated GitHub notes.
3. Merge the reviewed changes and wait for the complete main CI run.
4. Create `release/vVERSION` at that exact main commit, for example
   `release/v0.11.0`. This is an explicit request to publish, not a working branch.
5. Its fresh complete CI run validates the requested version and builds the artifacts.
   After the gate, the publisher requires that source to still equal current main,
   creates the missing `vVERSION` tag at that SHA, and publishes the verified artifacts.
   An existing tag must resolve to the same commit; tags are never moved.

The tag created with GITHUB_TOKEN does not trigger another push workflow. The
release-branch run is the complete qualification and the source of published
artifacts. Both request paths share per-version publication concurrency.

The original path is also supported: create and push a matching `v*` tag at the
reviewed source and let its complete CI run publish against the existing tag.
Ordinary main/PR/manual runs cannot publish, and release branches whose source
has not been merged into current main fail before tag creation. If main advances
while release CI is running, inspect the new main and prepare a fresh reviewed
release request; do not move a published tag or bypass the source check.

The tag, package version, and citation version must match exactly. For example,
`0.7.0.dev0` cannot be published as `v0.7.0`.

Release publication deliberately does not overwrite existing release assets. If a
release with the same tag already exists, inspect it and the failed run before retrying;
do not delete or replace published artifacts automatically. Checksums establish file
integrity; they are not cryptographic signatures or reproducible-build attestations.

For a local packaging check:

```sh
python -m pip install build twine
python -m build
python -m twine check --strict dist/*
```

Local builds are for verification. Published artifacts come from the qualifying tag or explicit release-branch CI run.

To regenerate the README screenshot from current code, install Playwright in the
development environment, run `python -m playwright install chromium`, then run
`python scripts/render_report_preview.py`. The script uses the vendor sample and
its YAML configuration, with a fixed UTC generation timestamp for a stable preview.
Pre-release package versions (for example `0.7.0rc1`) are marked as GitHub prereleases
and do not replace the latest stable release.
