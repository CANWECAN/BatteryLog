# Release artifacts

The CI workflow builds distributions on pull requests, main pushes, and `v*` tag pushes.
`python -m build` creates an sdist and builds the wheel from that sdist in an isolated
build environment. Both distributions pass strict metadata checks and are installed
in separate virtual environments outside the checkout. The installed CLI must produce
a PASS result that validates against the installed result schema.

Only a tag push can publish a GitHub Release. Publication depends on the complete
Linux Python matrix, Windows tests, and package checks in the same workflow run.
The release job downloads that run's artifacts, verifies SHA256SUMS, and attaches
the wheel, sdist, and checksums to the existing remote tag using `--verify-tag`.
It never creates a tag or uploads to PyPI.

Before tagging:

1. Set the intended release version in both `pyproject.toml` and `CITATION.cff`.
   Development versions are rejected.
2. Finalize CHANGELOG.md and refresh the README preview if the report changed.
3. Merge the reviewed changes and wait for CI.
4. Create and push the corresponding tag, for example `v0.7.0` for version `0.7.0`.

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

Local builds are for verification. Published artifacts come from the tagged CI run.

To regenerate the README screenshot from current code, install Playwright in the
development environment, run `python -m playwright install chromium`, then run
`python scripts/render_report_preview.py`. The script uses the vendor sample and
its YAML configuration, with a fixed UTC generation timestamp for a stable preview.
Pre-release package versions (for example `0.7.0rc1`) are marked as GitHub prereleases
and do not replace the latest stable release.
