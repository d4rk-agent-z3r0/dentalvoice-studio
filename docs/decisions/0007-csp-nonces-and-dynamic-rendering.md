# ADR-0007: Nonce-based CSP, so every page is rendered per request

**Status:** Accepted · 2026-10-31 (Milestone 8)

## Context
The dashboard keeps its access token in memory and `sessionStorage` (per tab). Any script injected
into the page could read it, so the page needs a Content-Security-Policy that allows only the app's
own scripts. A list of allowed script URLs is not enough: Next.js also emits inline bootstrap
scripts. The Next.js 16 documentation's answer is a per-request nonce, set by the proxy (formerly
middleware) and applied by Next to its scripts. A nonce cannot be placed on HTML that was
prerendered at build time: a test build with only the proxy served static pages whose 18 scripts
had no nonce, and the CSP blocked them.

## Decision
- The proxy (`frontend/src/proxy.ts`) generates a nonce per request and sends
  `script-src 'self' 'nonce-…' 'strict-dynamic'` and `style-src 'self' 'nonce-…'` in production,
  with `connect-src` limited to the API origin and its `ws(s)` counterpart and `media-src` adding
  `blob:` for caller clips. The full policy and its reasons are in
  `frontend/src/lib/security/headers.ts` and the verification report.
- The root layout awaits `connection()` (with `export const instant = false`), so every page is
  rendered on request and receives the nonce.
- Development adds `'unsafe-eval'` (React debugging) and inline styles (the dev overlay); production
  never does.

## Consequences
- No static shells: each navigation renders on the server. That costs little here, because every
  page renders its content on the client behind the session check anyway.
- Injected inline or third-party script cannot run, which is what makes keeping the token in
  `sessionStorage` an acceptable risk (docs/security/threat-model.md, I4 and §4).
- Verified in a browser against the real API: no CSP violations across sign-in, clinic switching,
  the voice simulator's WebSocket and `blob:` audio, and sign-out.

## Alternatives considered
- **A hash-based CSP with static pages:** Next's inline scripts change per build and per page, so
  the hashes would have to be generated into the headers at build time; Next 16 offers no supported
  way to do that.
- **`'unsafe-inline'` scripts:** this would defeat the reason for having the policy.
- **Token in an httpOnly cookie instead:** a stronger fix for token theft, but it brings
  cross-site request forgery protection and a same-site deployment requirement with it. It is
  recorded as a production follow-up in the threat model.
