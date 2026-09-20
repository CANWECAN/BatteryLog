import pytest

from scripts.check_release_version import check_release_version


@pytest.mark.parametrize(
    ("tag", "package", "citation"),
    [
        ("v0.7.1", "0.7.0", "0.7.0"),
        ("0.7.0", "0.7.0", "0.7.0"),
        ("v0.7.0", "0.7.0", "0.6.1"),
        ("v0.7.0.dev0", "0.7.0.dev0", "0.7.0.dev0"),
    ],
)
def test_release_rejects_inconsistent_or_development_versions(tag, package, citation):
    with pytest.raises(ValueError):
        check_release_version(tag, package, citation)


def test_release_accepts_matching_stable_version():
    check_release_version("v0.7.0", "0.7.0", "0.7.0")
