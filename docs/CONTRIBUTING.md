# Technical documentation and pull requests

Pull request descriptions explain the concrete problem, resulting behavior and
validation relevant to the diff. Assume the reviewer has not read previous
conversations. Define unfamiliar project abbreviations and keep branch dependencies
explicit when they affect review.

Technical notes record reproducible methods, source revisions, input identity,
results and material limitations. Distinguish software checks from physical
qualification, and attach test counts to their actual revision and environment.
Preserve negative findings and unresolved measurement assumptions.

Repository documentation does not serve as a personal activity journal. Omit
conversation transcripts, personal device identifiers and paths, remote-access
troubleshooting, elapsed work periods, individual permissions and conversational
next-action notes. Keep operational notes outside tracked project content.

Update CURRENT_STATE.md as a concise technical overview with links to the relevant
contracts and evidence. Replace superseded status rather than appending a running
chronology. Roadmaps describe capabilities and acceptance conditions; they do not
record conversation history.

Before submitting documentation, check relative links, code examples, source/test
revision references and consistency with the actual diff. Documentation edits do
not establish new runtime, physical-data or release qualification.

Run Core coverage with `python -m pytest -q --cov=batterylog
--cov-report=term-missing --cov-fail-under=95`. The root `pyproject.toml` enables
coverage.py's `subprocess` patch so real CLI/desktop-worker tests contribute
child-process measurements under pytest-cov 7; see its
[migration instructions](https://pytest-cov.readthedocs.io/en/stable/subprocess-support.html).
Keep the 95% gate and report display/platform skips separately. A statement
missing from a coverage report is not, by itself, proof that no subprocess test
exercised it. Coverage measures execution, not assertion quality or physical accuracy.
