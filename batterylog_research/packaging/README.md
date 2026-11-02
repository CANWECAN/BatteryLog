# Retired separate Research packaging

BatteryLog now builds one Apache-2.0 wheel and sdist from the root pyproject.
The 0.1.0a1 add-on and alpha2 packaging path are historical candidates.
Their staging builder and verifier have been removed.

Use `python -m build`, then the archive scan and
`scripts/check_experimental_package.py` described in
[licensing/package scope](../../docs/LICENSING.md).
