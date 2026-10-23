# Licensing and unified package scope

Status: unified public development integration, 20 October 2026.
Owner-authorized direction: one free Apache-2.0 BatteryLog product.
The unchanged official LICENSE and retained NOTICE apply to first-party Core
and experimental code. Commercial use is allowed under Apache-2.0; no extra
competitor-use, contribution or payment condition applies.

## Inventory

| Material | Terms | Distribution |
| --- | --- | --- |
| batterylog package, schemas and prior public PR code | Apache-2.0; existing rights preserved | One batterylog wheel/sdist |
| 28 top-level batterylog_research Python modules | Apache-2.0; SPDX headers replace proprietary notices | Same wheel/sdist; experimental |
| Two authored precharge CSV/context fixtures | Apache-2.0; software examples, not physical reference captures | Same wheel/sdist |
| Model 3 profile JSON files | First-party profiles with consulted MIT definitions credited | Same wheel/sdist with Josh Wardell MIT notice |
| First-party tests/docs, campaign code and authored aggregate reports | Apache-2.0 for first-party material; source-data terms and dated qualification scopes retained | Source distribution; wheel includes runtime code/resources only |
| External Python dependencies | Original licenses | Dependencies, not relicensed or source-vendored |
| Raw external captures, DBCs and datasets | Original source terms; no new grant | Not bundled |
| Internal BUG_HUNT notes and retired evaluation template | Not package inputs | Excluded |

The Git history identifies explicit first-party copyright notices and owner
commits, including the two BMW scripts without prior file headers. This records
the repository basis for the authorized change; it does not establish ownership
of external materials or grant an external-data license.

Model 3 definitions were consulted at model3dbc commit
c56c113c353d09b1a5dd57677461f02fe8b7c6ca. The source DBC is not bundled.
Its MIT text remains in
[third_party_model3dbc_NOTICE.txt](../batterylog_research/third_party_model3dbc_NOTICE.txt),
also declared as a license file in package metadata.

## Package and compatibility

There is one distribution/version: batterylog 0.11.0.dev0. There is no
batterylog-research dependency or separate alpha version.
The internal batterylog_research namespace stays importable for existing code.
Public v0.10.0 remains the last published release until a new version is accepted.

Base installation includes precharge review/HTML and exact-clock offline replay.
The optional [can] extra supplies DBC backends; [mf4] retains MDF/MF4 support.
Neither extra is a paid feature. The recommended root interface is
`batterylog experimental can|precharge|replay`.

Dated Research notes describe their original revisions. Former private/evaluation
distribution statements in those records are superseded by this inventory and
RESEARCH_LICENSE.md for the current candidate.

## Build checks

Build with `python -m build`, then verify both artifacts:

    python scripts/validation/check_distribution.py dist/*.whl dist/*.tar.gz
    python scripts/check_experimental_package.py --artifacts dist
    python scripts/check_sdist_test_fixtures.py dist/batterylog-0.11.0.dev0.tar.gz
    python -m twine check --strict dist/*

Install each wheel/sdist outside the checkout, exercise the base CLI and
precharge/replay, then install the same artifact with [can,mf4] and run
`scripts/check_experimental_package.py --installed` and the MF4 checks.
The artifact audit compares runtime source/resources and license bytes against
the checkout. It is not a physical qualification or signature.

Public release remains subject to supported platform/GUI checks and the
existing 95% coverage gate. Independent results must identify their actual environment and source revision;
local verification does not imply a hosted CI pass.
