# Licence Audit

> Audit date: 2026-10-30, at the end of the licensing milestone (before Milestone 2).
> Statuses: **Verified** · **Requires manual review** · **Not applicable** · **Blocked**.
> This audit does **not** declare the repository fully licence-compliant. The open items in §3
> are unresolved.

## 1. How the audit was done

| Step | Tool / method | Output |
|---|---|---|
| Python licences | pip-licenses 5.5.5 against `backend/.venv` (all dependency groups); runtime/dev split from `uv export` | `compliance/licenses/inventory.json` |
| npm licences | `pnpm licenses list --json` (installed: all and `--prod`) | same inventory |
| Platform-specific npm packages not installed on Linux x64 | cdxgen 12.9.0 with npm-registry licence lookup | same inventory, scope `optional-other-platform` |
| SBOMs | cyclonedx-bom 7.6.0 (backend), cdxgen 12.9.0 (frontend), CycloneDX 1.6 JSON | `compliance/sbom/*.cdx.json` |
| Classification | `scripts/compliance.py` against `compliance/license-policy.json` | `THIRD_PARTY_NOTICES.md` |
| Ambiguous metadata | Bundled licence files read by hand (httpx, uvloop, colorama) | `overrides` in the policy, with evidence |
| Container images | Reviewed by hand | `container_images` in the policy |

Reproducibility: four consecutive `python3 scripts/compliance.py generate` runs, plus a run in a
separate fresh clone, produced byte-identical outputs. Registry-derived package statistics that
change over time (version counts, last-modified times, release cadence) are excluded, and so
are maintainer and publisher names and emails: third-party personal data an inventory does not
need. Both SBOMs validate against the CycloneDX 1.6 JSON schema
(cyclonedx-python-lib strict validator).

## 2. Results

| Ecosystem | Runtime | Dev / build | Other-platform optional | Total |
|---|---|---|---|---|
| Python | 28 | 18 | — | 46 |
| npm | 67 | 373 | 96 | 536 |

| Category | Count | Meaning |
|---|---|---|
| allowed | 540 | Permissive licence on the policy allow-list |
| conditional-reviewed | 42 | MPL-2.0, LGPL-3.0-or-later or CC-BY-4.0, each with a recorded review decision |
| conditional-unreviewed | 0 | — |
| disallowed | 0 | — |
| unknown | 0 | — |

Reviewed conditional licences:

| Licence | Packages | Scope | Decision |
|---|---|---|---|
| MPL-2.0 | certifi, pathspec | Python dev | Accepted: unmodified, not in the runtime image |
| MPL-2.0 | axe-core, lightningcss (+ platform builds) | npm build/test | Accepted: unmodified, not in the runtime image |
| LGPL-3.0-or-later | @img/sharp-libvips-\* (+ sharp wasm/win32 builds) | npm runtime, optional (via `next → sharp`) | Accepted with obligations. **Ships in the frontend Docker image** (verified: `libvips-cpp.so` under `/app/node_modules`). Not used by the app (no `next/image`). |
| CC-BY-4.0 | caniuse-lite | npm (build data) | Accepted with attribution in `THIRD_PARTY_NOTICES.md` |

## 3. Checklist (build spec §22)

| Item | Status | Evidence / note |
|---|---|---|
| Licence selection approved by the owner | Verified | MIT, approved 2026-10-30 (`docs/licensing-policy.md`) |
| Full LICENSE file present | Verified | SPDX License List v6.12.0 MIT text, word-for-word apart from the holder and year |
| NOTICE present where needed | Not applicable | MIT requires no NOTICE file. No Apache-2.0 code is vendored; Apache NOTICE obligations travel with each package |
| README identifies the project licence | Verified | README "Licence" section |
| SPDX information in source files | Verified | `scripts/add_spdx_headers.py --check` in `make lint` and CI |
| Dependencies audited | Verified, with limitation | All 582 packages classified, 0 unknown. For non-ambiguous packages the declared SPDX metadata is used. Bundled licence files were read by hand only for the 3 ambiguous packages. |
| Third-party asset permissions checked | Verified | No images, icons, logos, fonts or sample data in the repository |
| Fonts and icons suitably licensed | Not applicable | None bundled; system font stacks only |
| Synthetic audio redistribution permissions | **Blocked** until Milestone 5 | No audio exists yet. TTS provider output terms must be checked and recorded before any clip is committed. |
| No third-party copyright notices removed | Verified | No third-party files are vendored. The removed template favicon was a brand asset, not a notice. |
| No unknown licence silently treated as permissive | Verified | The classifier treats missing or unrecognised licences as `unknown` (requires review), never as allowed |
| SBOM generated | Verified | `compliance/sbom/backend.cdx.json`, `compliance/sbom/frontend.cdx.json` |
| Dependency licence scan runs in CI | Verified locally; GitHub run pending | `.github/workflows/licenses.yml` runs `scripts/compliance.py check`; `make license-check` is part of `make verify`. Not yet run on GitHub Actions. |
| No employer or client material | Verified (owner-confirmed) | `docs/ownership-and-provenance.md` §1 |
| Project ownership documented | Verified | `docs/ownership-and-provenance.md` |
| Licence history recorded | Verified | `docs/licensing-policy.md`, including the unapproved MIT metadata in `176b349` |

## 4. Open items for the owner

| Item | Status | Options |
|---|---|---|
| LGPL libvips in the frontend image | Requires manual review | (a) Keep it, and meet the LGPL obligations if the image is ever distributed. (b) Drop sharp, since image optimisation is unused: `images.unoptimized` plus excluding the optional dependency. Option (b) removes the obligation. |
| Copyrightability of AI-generated code | Requires manual review | Legal question; see `docs/ownership-and-provenance.md` §2 |
| OS packages in Docker base images | Not applicable while images aren't distributed | If images are published to a registry, base-image OS package obligations (incl. GPL components) apply |
| Synthetic patient audio | Blocked (Milestone 5) | Check the TTS provider's output and redistribution terms first |
| Licence scan on GitHub Actions | Requires manual review | Confirm after the first push |

## 5. Regenerating

```bash
make compliance        # regenerate SBOMs, inventory and THIRD_PARTY_NOTICES.md after a dependency change
make license-check     # what CI runs: exit 1 on policy violations or unregenerated changes
```

`check` fails when: a licence is disallowed; a conditional licence has no recorded review; a
licence is unknown or not machine-readable (never assumed permissive); dependencies differ from the
committed inventory; or any generated file is out of date. Resolve violations with an evidence-backed
`overrides` or `reviewed` entry in `compliance/license-policy.json`, or by removing the dependency.

Requires `uv`, `pnpm` and installed dependencies (`make install`). Tool versions are pinned in
`scripts/compliance.py`.
