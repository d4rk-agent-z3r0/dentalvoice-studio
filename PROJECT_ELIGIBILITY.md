# Project Eligibility & Data Boundaries

DentalVoice Studio is an independently owned engineering portfolio project by Siddharth Majhi,
developed with AI assistance (Claude, Anthropic) under his direction. It is **not** a production
healthcare platform.

## Ownership statement

- Created in a new, empty repository for this project. Every non-original file (framework
  templates, generated lockfiles, licence text) is listed in
  [docs/ownership-and-provenance.md](docs/ownership-and-provenance.md).
- Contains **no** code, data, designs, documents or credentials belonging to any employer, client,
  university, or any party bound by a non-disclosure agreement. The owner has confirmed that his
  employment agreement does not claim this project.
- AI-assisted commits are marked with `Co-Authored-By` trailers. Open questions about the status of
  AI-generated material are tracked as *requires manual review* in the provenance document, not
  asserted away.
- Third-party software is used only through public packages under their published licences, as
  inventoried in `THIRD_PARTY_NOTICES.md`.
- Released under the [MIT License](LICENSE), as approved by the owner.

## Data boundaries (enforced, not aspirational)

| Rule | Enforcement mechanism | Delivered in |
|---|---|---|
| Fictional clinics, generated patient identities, fictional appointments only | Generated seed data; DB `CHECK` constraints on contact columns | M2 |
| Reserved / non-routable contact values only | Emails limited to `example.com`, `example.org`, `example.net` (RFC 2606); phones limited to the `555-0100`–`555-0199` fictional range | M2 |
| Synthetic audio only; all STT input comes from predefined fixtures | The browser never sends audio — the server streams allow-listed fixture files (ADR-0002) | M5 |
| No microphone access | No `getUserMedia` usage; asserted in frontend tests | M7 |
| No arbitrary file uploads | No upload endpoints exist | M1 ✓ |
| No real SMS, email, or calendar delivery | No such integrations exist | M1 ✓ |
| No clinical diagnosis or treatment advice | Receptionist prompt forbids it; emergency scenario follows a scripted escalation protocol only | M3–M4 |
| No real patient data sent to AI providers | Only synthetic fixture transcripts and synthetic intake values reach Gemini/Deepgram | M4–M5 |
| No secrets in the repository or in prompts | `.env` git-ignored; `.env.example` placeholders only; `DATABASE_URL` has no default | M1 ✓ |
| Persistent synthetic-data notice | Root layout banner, asserted by a frontend test | M1 ✓ |

Every page displays: **DEMO ENVIRONMENT — ALL PATIENTS AND CONVERSATIONS ARE SYNTHETIC.**

## Claims this project does not make

It is not HIPAA-compliant, not clinically validated, and not ready for deployment in a healthcare
practice. It is not an AI model benchmarking or evaluation platform.
