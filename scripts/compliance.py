# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
"""Dependency licence inventory and SBOM generation.

    python3 scripts/compliance.py generate   # rewrite compliance/ and THIRD_PARTY_NOTICES.md
    python3 scripts/compliance.py check [--report FILE]
        # regenerate in memory; exit 1 on policy violations, dependency changes not yet
        # reflected in the committed inventory, or stale generated files

Outputs are normalised (no timestamps, serial numbers or absolute paths, stable ordering) so that
regenerating from the same lockfiles gives byte-identical files.

Sources (pinned):
  Python licences  pip-licenses 5.5.5 against backend/.venv (all dependency groups)
  Python SBOM      cyclonedx-bom 7.6.0 (`cyclonedx-py environment`)
  npm licences     `pnpm licenses list --json` (installed packages, prod and all)
  npm SBOM         @cyclonedx/cdxgen 12.9.0 with registry licence lookup (whole pnpm lockfile)
Licence conclusions that differ from declared metadata come only from compliance/license-policy.json
"overrides", each with recorded evidence.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
COMPLIANCE = ROOT / "compliance"
POLICY_FILE = COMPLIANCE / "license-policy.json"
INVENTORY_FILE = COMPLIANCE / "licenses" / "inventory.json"
SBOM_DIR = COMPLIANCE / "sbom"
NOTICES_FILE = ROOT / "THIRD_PARTY_NOTICES.md"

PIP_LICENSES = "pip-licenses==5.5.5"
CYCLONEDX_PY = "cyclonedx-bom==7.6.0"
CDXGEN = "@cyclonedx/cdxgen@12.9.0"
PLATFORM_NOTE = "Not installed on Linux x64; licence from npm registry metadata."


@dataclass(frozen=True)
class Dependency:
    ecosystem: str
    name: str
    version: str
    declared: str
    concluded: str
    scope: str  # runtime | dev | optional-other-platform
    direct: bool
    source: str
    category: str  # allowed | conditional-reviewed | conditional-unreviewed | disallowed | unknown
    note: str


# --------------------------------------------------------------------------- helpers


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    # Fixed argv lists of pinned tools; no shell, no untrusted input.
    result = subprocess.run(  # noqa: S603
        cmd,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_policy() -> dict[str, Any]:
    policy: dict[str, Any] = json.loads(POLICY_FILE.read_text())
    return policy


# --------------------------------------------------------------------------- classification


def normalise(expression: str, policy: dict[str, Any]) -> str:
    expression = expression.strip()
    if expression in policy["normalize"]:
        return str(policy["normalize"][expression])
    return expression


def classify(ecosystem: str, name: str, concluded: str, policy: dict[str, Any]) -> tuple[str, str]:
    """Return (category, note). AND: every term must pass; OR: the most permissive term wins."""
    if not concluded or concluded.upper() in {"UNKNOWN", "NOASSERTION"} or "(" in concluded:
        return "unknown", "Licence missing or not machine-readable: requires manual review."

    rank = {"allowed": 0, "conditional": 1, "disallowed": 2, "unknown": 3}

    def term_category(term: str) -> str:
        if term in policy["allowed"]:
            return "allowed"
        if term in policy["conditional"]:
            return "conditional"
        if term in policy["disallowed"]:
            return "disallowed"
        return "unknown"

    if " AND " in concluded:
        worst = max((term_category(t) for t in concluded.split(" AND ")), key=rank.__getitem__)
        base, terms = worst, concluded.split(" AND ")
    elif " OR " in concluded:
        best = min((term_category(t) for t in concluded.split(" OR ")), key=rank.__getitem__)
        base, terms = best, concluded.split(" OR ")
    else:
        base, terms = term_category(concluded), [concluded]

    if base == "allowed":
        return "allowed", ""
    if base == "disallowed":
        return "disallowed", "Licence is on the project's disallowed list."
    if base == "unknown":
        return "unknown", "Licence not in policy: requires manual review."

    conditional_terms = [t for t in terms if t in policy["conditional"]]
    for review in policy["reviewed"]:
        if review["ecosystem"] != ecosystem or review["license"] not in conditional_terms:
            continue
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in review["names"]):
            return "conditional-reviewed", f"{review['decision']}: {review['rationale']}"
    return "conditional-unreviewed", "Conditional licence without a recorded review."


def apply_override(ecosystem: str, name: str, declared: str, policy: dict[str, Any]) -> str | None:
    for override in policy["overrides"]:
        if override["ecosystem"] == ecosystem and pep503(override["name"]) == pep503(name):
            return str(override["concluded"])
    return None


# --------------------------------------------------------------------------- python


def python_inventory(policy: dict[str, Any]) -> list[Dependency]:
    python = str(BACKEND / ".venv" / "bin" / "python")
    raw = json.loads(
        run(
            [
                "uvx",
                "--from",
                PIP_LICENSES,
                "pip-licenses",
                "--python",
                python,
                "--from=mixed",
                "--with-urls",
                "--format=json",
            ],
            ROOT,
        )
    )
    installed = {pep503(p["Name"]): p for p in raw}

    def exported(*extra: str) -> dict[str, str]:
        out = run(["uv", "export", "--frozen", "--no-hashes", "--no-emit-project", *extra], BACKEND)
        pins = {}
        for line in out.splitlines():
            match = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)", line)
            if match:
                pins[pep503(match.group(1))] = match.group(2)
        return pins

    all_pins = exported("--all-groups")
    runtime = set(exported("--no-dev"))
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    direct_specs = [*project["project"]["dependencies"]]
    for group in project.get("dependency-groups", {}).values():
        direct_specs.extend(group)
    direct = {pep503(re.split(r"[\[<>=!~ ;]", spec, maxsplit=1)[0]) for spec in direct_specs}

    deps = []
    for key, version in sorted(all_pins.items()):
        meta = installed.get(key)
        declared = meta["License"] if meta else "not installed on this platform"
        concluded = apply_override("python", key, declared, policy) or normalise(declared, policy)
        if meta is None and concluded == declared:
            concluded = "UNKNOWN"
        category, note = classify("python", key, concluded, policy)
        deps.append(
            Dependency(
                ecosystem="python",
                name=meta["Name"] if meta else key,
                version=version,
                declared=declared,
                concluded=concluded,
                scope="runtime" if key in runtime else "dev",
                direct=key in direct,
                source=(
                    meta["URL"]
                    if meta and meta["URL"] != "UNKNOWN"
                    else f"https://pypi.org/project/{key}/"
                ),
                category=category,
                note=note,
            )
        )
    return deps


def python_sbom() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "backend.cdx.json"
        run(
            [
                "uvx",
                "--from",
                CYCLONEDX_PY,
                "cyclonedx-py",
                "environment",
                "--output-reproducible",
                "--of",
                "JSON",
                "--pyproject",
                "pyproject.toml",
                "-o",
                str(out),
                ".venv",
            ],
            BACKEND,
        )
        sbom: dict[str, Any] = json.loads(out.read_text())
    return sbom


# --------------------------------------------------------------------------- npm


def npm_inventory(policy: dict[str, Any], sbom: dict[str, Any]) -> list[Dependency]:
    def listing(*extra: str) -> dict[str, list[dict[str, Any]]]:
        data: dict[str, list[dict[str, Any]]] = json.loads(
            run(["pnpm", "licenses", "list", "--json", *extra], FRONTEND)
        )
        return data

    everything, prod = listing(), listing("--prod")
    prod_names = {p["name"] for pkgs in prod.values() for p in pkgs}
    package = json.loads((FRONTEND / "package.json").read_text())
    direct = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))

    deps: dict[tuple[str, str], Dependency] = {}
    for declared, pkgs in everything.items():
        for pkg in pkgs:
            for version in pkg["versions"]:
                concluded = normalise(declared, policy)
                category, note = classify("npm", pkg["name"], concluded, policy)
                deps[(pkg["name"], version)] = Dependency(
                    ecosystem="npm",
                    name=pkg["name"],
                    version=version,
                    declared=declared,
                    concluded=concluded,
                    scope="runtime" if pkg["name"] in prod_names else "dev",
                    direct=pkg["name"] in direct,
                    source=pkg.get("homepage") or f"https://www.npmjs.com/package/{pkg['name']}",
                    category=category,
                    note=note,
                )

    # Lockfile entries not installed here (other OS/CPU builds of optional native packages).
    for component in sbom.get("components", []):
        name = (
            f"{component['group']}/{component['name']}"
            if component.get("group")
            else component["name"]
        )
        version = component.get("version", "")
        if (name, version) in deps:
            continue
        terms = []
        for entry in component.get("licenses", []):
            if "expression" in entry:
                terms.append(entry["expression"])
            else:
                terms.append(entry["license"].get("id") or entry["license"].get("name", ""))
        declared = " AND ".join(t for t in terms if t) or "UNKNOWN"
        concluded = normalise(declared, policy)
        category, note = classify("npm", name, concluded, policy)
        deps[(name, version)] = Dependency(
            ecosystem="npm",
            name=name,
            version=version,
            declared=declared,
            concluded=concluded,
            scope="optional-other-platform",
            direct=False,
            source=f"https://www.npmjs.com/package/{name}",
            category=category,
            note=f"{note} {PLATFORM_NOTE}".strip(),
        )
    return sorted(deps.values(), key=lambda d: (d.name, d.version))


def npm_sbom() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frontend.cdx.json"
        run(
            [
                "pnpm",
                "dlx",
                CDXGEN,
                "-t",
                "js",
                "--no-recurse",
                "--no-install-deps",
                "--spec-version",
                "1.6",
                "-o",
                str(out),
                ".",
            ],
            FRONTEND,
            env={"FETCH_LICENSE": "true", "CDXGEN_NO_BANNER": "true"},
        )
        sbom: dict[str, Any] = json.loads(out.read_text())
    return sbom


# --------------------------------------------------------------------------- normalisation

# cdxgen's registry lookup adds `cdx:npm:*` properties. Only facts fixed for the locked version are
# kept. Package-level statistics (version counts, last-modified times, release cadence) change
# whenever a package publishes anything, and maintainer/publisher fields carry third parties'
# personal data (names, emails) that an inventory does not need.
NPM_STABLE_PROPERTIES = frozenset(
    {
        "cdx:npm:artifactIntegrity",
        "cdx:npm:artifactShasum",
        "cdx:npm:bin",
        "cdx:npm:buildScripts",
        "cdx:npm:cpu",
        "cdx:npm:has_binary",
        "cdx:npm:hasInstallScript",
        "cdx:npm:libc",
        "cdx:npm:os",
        "cdx:npm:package:development",
        "cdx:npm:package:optional",
        "cdx:npm:package:type-only",
        "cdx:npm:provenanceUrl",
        "cdx:npm:publishTime",
        "cdx:npm:risky_scripts",
        "cdx:npm:scripts",
        "cdx:npm:trustedPublishing",
    }
)


def _drop_volatile_properties(node: Any) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("properties"), list):
            node["properties"] = [
                prop
                for prop in node["properties"]
                if not str(prop.get("name", "")).startswith("cdx:npm:")
                or prop["name"] in NPM_STABLE_PROPERTIES
            ]
        for value in node.values():
            _drop_volatile_properties(value)
    elif isinstance(node, list):
        for item in node:
            _drop_volatile_properties(item)


def normalise_sbom(sbom: dict[str, Any]) -> dict[str, Any]:
    """Strip run-specific, time-varying and personal fields so regeneration is byte-identical."""
    sbom.pop("serialNumber", None)
    _drop_volatile_properties(sbom)
    # cdxgen adds a prose annotation stamped with the run time; it carries no inventory data.
    sbom.pop("annotations", None)
    metadata = sbom.get("metadata", {})
    metadata.pop("timestamp", None)
    # cdxgen's evidence.occurrences lists the source lines that import each package. It changes
    # with every application code edit, not with dependencies; identity evidence is kept.
    for component in sbom.get("components", []):
        evidence = component.get("evidence")
        if isinstance(evidence, dict):
            evidence.pop("occurrences", None)
            if not evidence:
                component.pop("evidence")
    text = json.dumps(sbom)
    for path in (str(ROOT), str(Path(tempfile.gettempdir()))):
        text = text.replace(path, ".")
    data: dict[str, Any] = json.loads(text)

    def sort_lists(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: sort_lists(v) for k, v in node.items()}
        if isinstance(node, list):
            items = [sort_lists(v) for v in node]
            if all(isinstance(i, dict) and "bom-ref" in i for i in items):
                return sorted(items, key=lambda i: str(i["bom-ref"]))
            if all(isinstance(i, dict) and "ref" in i for i in items):
                return sorted(items, key=lambda i: str(i["ref"]))
            if all(isinstance(i, str) for i in items):
                return sorted(items)
            # CycloneDX arrays are unordered collections; some generators emit them in varying
            # order (e.g. async property collection), so sort the rest canonically too.
            return sorted(items, key=lambda i: json.dumps(i, sort_keys=True))
        return node

    return dict(sort_lists(data))


# --------------------------------------------------------------------------- outputs


def render_notices(deps: list[Dependency], policy: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for dep in deps:
        counts[dep.category] = counts.get(dep.category, 0) + 1
    lines = [
        "# Third-Party Notices",
        "",
        "<!-- Generated by `python3 scripts/compliance.py generate`. Do not edit by hand: change",
        "     compliance/license-policy.json and regenerate. -->",
        "",
        "DentalVoice Studio's original code is MIT-licensed (see `LICENSE`). It depends on the",
        "third-party packages below, which remain under their own licences. Nothing here is",
        "relicensed by this project. Copyright notices and full licence texts ship inside each",
        "package as installed. Inclusion in this list is not an endorsement.",
        "",
        "## Attribution notices",
        "",
        "- **caniuse-lite** (CC-BY-4.0): browser-support data from [Can I Use](https://caniuse.com)",
        "  by Alexis Deveria, used by the frontend build toolchain.",
        "- **libvips via @img/sharp-libvips-\\*** (LGPL-3.0-or-later): shipped unmodified inside",
        "  the frontend container image as an optional dependency of Next.js. Source:",
        "  https://github.com/libvips/libvips. Licence: https://www.gnu.org/licenses/lgpl-3.0.html",
        "- **MPL-2.0 packages** (certifi, pathspec, axe-core, lightningcss): development and build",
        "  tooling, used unmodified; sources at the links below.",
        "",
        "## Summary",
        "",
        "| Category | Packages |",
        "|---|---|",
    ]
    for category in (
        "allowed",
        "conditional-reviewed",
        "conditional-unreviewed",
        "disallowed",
        "unknown",
    ):
        lines.append(f"| {category} | {counts.get(category, 0)} |")
    lines += [
        "",
        "## Container base images",
        "",
        "| Image | Used in | Licence | Notes |",
        "|---|---|---|---|",
    ]
    for image in policy["container_images"]:
        lines.append(
            f"| `{image['image']}` | {image['used_in']} | {image['license']} | {image['notes']} |"
        )
    for ecosystem, title in (("python", "Python packages"), ("npm", "npm packages")):
        lines += [
            "",
            f"## {title}",
            "",
            "| Package | Version | Licence (SPDX) | Declared | Scope | Direct | Category "
            "| Source |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for dep in deps:
            if dep.ecosystem != ecosystem:
                continue
            declared = "" if dep.declared == dep.concluded else dep.declared
            lines.append(
                f"| {dep.name} | {dep.version} | {dep.concluded} | {declared} | {dep.scope} | "
                f"{'yes' if dep.direct else ''} | {dep.category} | {dep.source} |"
            )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- policy enforcement

BLOCKING_CATEGORIES = ("conditional-unreviewed", "disallowed", "unknown")


@dataclass(frozen=True)
class InventoryDiff:
    added: list[str]
    removed: list[str]
    changed: list[str]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def violations(deps: list[Dependency]) -> list[Dependency]:
    """Dependencies the policy does not allow to merge without a human decision."""
    return [d for d in deps if d.category in BLOCKING_CATEGORIES]


def diff_inventories(committed: list[Dependency], fresh: list[Dependency]) -> InventoryDiff:
    def versions(deps: list[Dependency]) -> dict[tuple[str, str], dict[str, Dependency]]:
        index: dict[tuple[str, str], dict[str, Dependency]] = {}
        for dep in deps:
            index.setdefault((dep.ecosystem, dep.name), {})[dep.version] = dep
        return index

    old, new = versions(committed), versions(fresh)
    added, removed, changed = [], [], []
    for key in sorted(new.keys() - old.keys()):
        added.append(f"{key[0]} {key[1]} {', '.join(sorted(new[key]))}")
    for key in sorted(old.keys() - new.keys()):
        removed.append(f"{key[0]} {key[1]} {', '.join(sorted(old[key]))}")
    for key in sorted(old.keys() & new.keys()):
        before, after = old[key], new[key]
        if set(before) != set(after):
            changed.append(
                f"{key[0]} {key[1]} {', '.join(sorted(before))} -> {', '.join(sorted(after))}"
            )
            continue
        for version in sorted(before):
            if before[version].concluded != after[version].concluded:
                changed.append(
                    f"{key[0]} {key[1]} {version}: licence "
                    f"{before[version].concluded} -> {after[version].concluded}"
                )
    return InventoryDiff(added=added, removed=removed, changed=changed)


# --------------------------------------------------------------------------- commands


def json_text(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_outputs(policy: dict[str, Any]) -> tuple[list[Dependency], dict[Path, str]]:
    backend_sbom = normalise_sbom(python_sbom())
    frontend_raw = npm_sbom()
    deps = python_inventory(policy) + npm_inventory(policy, frontend_raw)
    outputs = {
        SBOM_DIR / "backend.cdx.json": json_text(backend_sbom),
        SBOM_DIR / "frontend.cdx.json": json_text(normalise_sbom(frontend_raw)),
        INVENTORY_FILE: json_text([asdict(d) for d in deps]),
        NOTICES_FILE: render_notices(deps, policy),
    }
    return deps, outputs


def category_counts(deps: list[Dependency]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for dep in deps:
        counts[dep.category] = counts.get(dep.category, 0) + 1
    return counts


def generate() -> int:
    deps, outputs = build_outputs(load_policy())
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    print(f"inventory: {len(deps)} packages {category_counts(deps)}")
    blocking = violations(deps)
    for dep in blocking:
        print(
            f"needs review: {dep.ecosystem} {dep.name} {dep.version} {dep.concluded!r}: {dep.note}"
        )
    return 0


def render_report(
    deps: list[Dependency], blocking: list[Dependency], diff: InventoryDiff, stale: list[str]
) -> str:
    lines = ["# Dependency licence check", "", "| Category | Packages |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(category_counts(deps).items())]
    lines += ["", "## Policy violations", ""]
    if blocking:
        lines += [
            "| Ecosystem | Package | Version | Licence | Scope | Why |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {d.ecosystem} | {d.name} | {d.version} | {d.concluded or '(none)'} | {d.scope} "
            f"| {d.category}: {d.note} |"
            for d in blocking
        ]
        lines += [
            "",
            "Resolve each by recording evidence in `compliance/license-policy.json` (an "
            "`overrides` entry for mis-declared metadata, or a `reviewed` entry for a conditional "
            "licence), or by removing the dependency. Unknown licences are never assumed "
            "permissive.",
        ]
    else:
        lines.append("None.")
    lines += ["", "## Dependency changes since the committed inventory", ""]
    if diff.is_empty:
        lines.append("None.")
    for title, items in (
        ("Added", diff.added),
        ("Removed", diff.removed),
        ("Changed", diff.changed),
    ):
        if items:
            lines += [f"**{title}**", ""] + [f"- {item}" for item in items] + [""]
    lines += ["", "## Out-of-date generated files", ""]
    lines += [f"- `{path}`" for path in stale] or ["None."]
    if stale:
        lines += ["", "Run `make compliance` and commit the regenerated files after review."]
    return "\n".join(lines) + "\n"


def check(report_path: Path | None) -> int:
    policy = load_policy()
    deps, outputs = build_outputs(policy)
    committed_raw = json.loads(INVENTORY_FILE.read_text()) if INVENTORY_FILE.exists() else []
    committed = [Dependency(**item) for item in committed_raw]
    diff = diff_inventories(committed, deps)
    stale = [
        str(path.relative_to(ROOT))
        for path, text in outputs.items()
        if not path.exists() or path.read_text() != text
    ]
    blocking = violations(deps)
    report = render_report(deps, blocking, diff, stale)
    if report_path is not None:
        report_path.write_text(report)
    print(report)
    return 1 if (blocking or stale or not diff.is_empty) else 0


def main() -> int:
    args = sys.argv[1:]
    command = args[0] if args else ""
    if command == "generate":
        return generate()
    if command == "check":
        report = Path(args[args.index("--report") + 1]) if "--report" in args else None
        return check(report)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
