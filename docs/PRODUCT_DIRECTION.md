# BatteryLog product direction

Accepted: 19 October 2026. Package/license implementation: review candidate,
20 October 2026. Public integration and release acceptance remain pending.

BatteryLog is one free Apache-2.0 product, with one recommended installation and
release version. Reviewed Core and experimental workflows share LICENSE/NOTICE.
Commercial use and derivatives are allowed under Apache-2.0. Third-party terms
are preserved. Research names qualification and internal module organization;
there is no paid Research edition or separate evaluation-access requirement.

Implementation and file scope are in [LICENSING.md](LICENSING.md). The internal
batterylog_research namespace remains importable to avoid a cosmetic rewrite.
The old two-wheel add-on builders are retired. The development tree packages
the common file operator, precharge HTML and replay with Core. The latest published release remains v0.10.0 while the unified source tree is
available for development and review.

Optional paid support, BMS integration, workflow automation and application-specific
verification may be explored after independent user feedback. Software access is
not conditional on buying those services. Demand and pricing remain unvalidated.

A release needs working wheel/sdist installs and supported platform/GUI
verification with the existing 95% coverage gate. Development source can be
reviewed with those checks explicitly pending. Independent results must name
their actual runner and revision; they do not imply a hosted CI pass.

Experimental tools retain timing/topology/measurement limitations and explicit
unknown outcomes. Publishing experimental code does not establish physical
fault accuracy, calibrated thresholds or HIL performance. Physical evidence is
required for corresponding physical claims, not for every software workflow.

The source-clock fix rejects ordering regressions before binary64 coercion; it
cannot recover precision already lost by the caller or change report/model
arithmetic to arbitrary precision. The parser cost remains a measured tradeoff.

The first demonstration uses an authored example, declared illustrative limits,
a selected rule and source-linked JSON/HTML evidence. Show workflows included in
the demonstrated installation. Seek feedback on clean installation, interpretation
and practical usefulness before wider promotion.
