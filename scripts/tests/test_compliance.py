# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
from typing import Any

import compliance
import pytest
from compliance import Dependency, classify, diff_inventories, normalise_sbom, violations

POLICY: dict[str, Any] = {
    "allowed": {"MIT": "", "Apache-2.0": "", "BSD-3-Clause": ""},
    "conditional": {"MPL-2.0": "", "LGPL-3.0-or-later": ""},
    "disallowed": ["GPL-3.0-only", "AGPL-3.0-only"],
    "normalize": {"MIT License": "MIT"},
    "overrides": [
        {"ecosystem": "python", "name": "Some_Pkg", "concluded": "BSD-3-Clause", "evidence": "x"}
    ],
    "reviewed": [
        {
            "ecosystem": "npm",
            "names": ["@img/sharp-libvips-*"],
            "license": "LGPL-3.0-or-later",
            "decision": "accepted",
            "rationale": "dynamically linked",
        }
    ],
}


def dep(name: str = "pkg", version: str = "1.0.0", category: str = "allowed") -> Dependency:
    return Dependency(
        ecosystem="npm",
        name=name,
        version=version,
        declared="MIT",
        concluded="MIT",
        scope="runtime",
        direct=False,
        source="https://example.com",
        category=category,
        note="",
    )


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("MIT", "allowed"),
        ("MIT OR GPL-3.0-only", "allowed"),  # OR: the licensee may pick the permissive option
        ("MIT AND GPL-3.0-only", "disallowed"),  # AND: every term applies
        ("GPL-3.0-only", "disallowed"),
        ("WTFPL", "unknown"),  # not in policy: never silently treated as permissive
        ("UNKNOWN", "unknown"),
        ("", "unknown"),
        ("(MIT OR Apache-2.0) AND BSD-3-Clause", "unknown"),  # nested: needs a human
        ("MPL-2.0", "conditional-unreviewed"),
    ],
)
def test_classify_expressions(expression: str, expected: str) -> None:
    category, _ = classify("npm", "some-package", expression, POLICY)
    assert category == expected


def test_conditional_licence_needs_matching_review() -> None:
    reviewed, note = classify("npm", "@img/sharp-libvips-linux-x64", "LGPL-3.0-or-later", POLICY)
    assert reviewed == "conditional-reviewed"
    assert "dynamically linked" in note
    # Same licence, different package: the review does not carry over.
    other, _ = classify("npm", "some-other-lib", "LGPL-3.0-or-later", POLICY)
    assert other == "conditional-unreviewed"
    # Same package name in another ecosystem: no carry-over either.
    wrong_ecosystem, _ = classify("python", "@img/sharp-libvips-x", "LGPL-3.0-or-later", POLICY)
    assert wrong_ecosystem == "conditional-unreviewed"


def test_override_matches_normalised_python_names() -> None:
    assert compliance.apply_override("python", "some-pkg", "BSD License", POLICY) == "BSD-3-Clause"
    assert compliance.apply_override("npm", "some-pkg", "BSD License", POLICY) is None


def test_normalise_maps_classifier_names() -> None:
    assert compliance.normalise(" MIT License ", POLICY) == "MIT"
    assert compliance.normalise("Apache-2.0", POLICY) == "Apache-2.0"


def test_violations_lists_blocking_categories_only() -> None:
    deps = [
        dep("a"),
        dep("b", category="conditional-reviewed"),
        dep("c", category="conditional-unreviewed"),
        dep("d", category="disallowed"),
        dep("e", category="unknown"),
    ]
    assert [d.name for d in violations(deps)] == ["c", "d", "e"]


def test_diff_inventories_reports_added_removed_and_changed() -> None:
    committed = [dep("kept"), dep("removed"), dep("bumped", "1.0.0")]
    fresh = [dep("kept"), dep("bumped", "2.0.0"), dep("added")]

    diff = diff_inventories(committed, fresh)

    assert diff.added == ["npm added 1.0.0"]
    assert diff.removed == ["npm removed 1.0.0"]
    assert diff.changed == ["npm bumped 1.0.0 -> 2.0.0"]
    assert not diff.is_empty


def test_diff_inventories_detects_licence_change_at_same_version() -> None:
    committed = [dep("pkg")]
    relicensed = Dependency(**{**dep("pkg").__dict__, "concluded": "GPL-3.0-only"})

    diff = diff_inventories(committed, [relicensed])

    assert diff.changed == ["npm pkg 1.0.0: licence MIT -> GPL-3.0-only"]


def test_identical_inventories_have_empty_diff() -> None:
    assert diff_inventories([dep("a")], [dep("a")]).is_empty


def test_normalise_sbom_is_order_and_run_independent() -> None:
    run_a = {
        "serialNumber": "urn:uuid:1",
        "metadata": {
            "timestamp": "2026-01-01T00:00:00Z",
            "properties": [{"name": "b"}, {"name": "a"}],
        },
        "annotations": [{"text": "created on Monday"}],
        "components": [{"bom-ref": "z"}, {"bom-ref": "a"}],
    }
    run_b = {
        "serialNumber": "urn:uuid:2",
        "metadata": {
            "timestamp": "2026-02-02T00:00:00Z",
            "properties": [{"name": "a"}, {"name": "b"}],
        },
        "annotations": [{"text": "created on Tuesday"}],
        "components": [{"bom-ref": "a"}, {"bom-ref": "z"}],
    }
    assert normalise_sbom(run_a) == normalise_sbom(run_b)
    assert "serialNumber" not in normalise_sbom(run_a)
