<!-- SPDX-FileCopyrightText: 2026 Siddharth Majhi -->
<!-- SPDX-License-Identifier: MIT -->
# Reply guard

Milestone 8. Code: `backend/app/orchestrators/reply_guard.py`, wired into
`ConversationOrchestrator._reply`.

## The gap

ADR-0003 makes the model's *action* a request: the decision layer validates it against the intake
and the state machine. The model's *words* were not checked. When a provider writes its own replies
(`writes_responses = True`, Gemini in live mode), `assistant_response` was stored as the
receptionist turn and spoken by TTS exactly as written. A model, possibly steered by a caller saying
"ignore your instructions…", could claim a booking that never happened, quote its prompt, read out a
phone number or link nobody gave, or give clinical advice.

## What happens now

When the orchestrator would speak model text (provider writes replies, the state is not one with
fixed wording, no action was ignored, no value was rejected), it first calls
`check_reply(text, guard_context(state, live_values))`. The check is pure and deterministic. If it
returns any reason:

- the deterministic reply from `compose_reply(...)` is stored and spoken instead;
- a `reply_filtered` conversation event is recorded with payload `{"reasons": [...]}` only;
- a structured `reply_filtered` warning is logged with `conversation_id`, `state`, `reasons` and
  `provider`.

The text and the intake values never appear in the event, the log or the verdict, because the
reply may echo either. The mock provider (`writes_responses = False`) never reaches the guard.
Intake, state transitions and side effects are decided before the reply is chosen and are not
affected.

## What the engine actually commits to

Found by reading the code, and the basis of the commitment rules:

| Claim | When it is true | Guard |
|---|---|---|
| An appointment is booked, scheduled, reserved or confirmed | Never during a call. Appointments are created only by `ReservationService`, which only the staff appointments API (`api/v1/appointments.py`) calls. A call records an appointment *request*; the clinic confirms it later (the prompt's rule 3 says the same). | `false_booking_claim` in every state |
| The intake is confirmed | On entering `CONFIRMATION_PENDING` (`confirm_all`) | |
| The patient is registered; details saved; request submitted or recorded | On entering `COMPLETED`: the intake snapshot is created and the patient record is created or matched | `false_registration_claim` except in `COMPLETED` |

`CONFIRMATION_PENDING`, `COMPLETED`, `ESCALATED` and `ABANDONED` already use fixed wording, so in
practice a model never speaks in a state where a registration claim is true. The guard is still
state-aware so the rule is correct on its own.

The clinic model has no published contact details (only name, slug and timezone), so the only
contact values a reply may contain are the caller's own live email and phone.

## Rules and reason codes

| Reason code | Refuses | Allows (tested) |
|---|---|---|
| `false_booking_claim` | "your appointment (on Tuesday) is booked/confirmed", "I've booked you in", "you're all booked in", "we've reserved the slot", "Booked! See you Tuesday.", confirmation numbers | "Could you confirm…?", "The clinic will confirm the appointment time", "Once your appointment is confirmed, …", "I can't book appointments", "isn't confirmed yet" |
| `false_registration_claim` | "you're now registered", "your details are saved", "everything is confirmed", "I've submitted your registration", "your request has been submitted" (outside `COMPLETED`) | "I'll note that down", "I've noted that", "I've updated your email", "Shall I submit your registration…?", "Are you registered with us already?" |
| `system_disclosure` | system prompt, "my instructions/prompt/configuration", "ignore previous instructions", "I'm programmed to", "developer mode", "my developers", the `<<<CALLER>>>` fence markers, the prompt version | "I'm your virtual receptionist", "I can only help with registration" |
| `provider_disclosure` | Gemini, Google, OpenAI, GPT, Claude, Anthropic and similar names; "language model", "LLM", "AI model" | a provider word that is the caller's own name ("Thanks, Claude") |
| `schema_leak` | every snake_case or SCREAMING_CASE identifier of the contract, derived from code (`assistant_response`, `next_action`, `IDENTITY_COLLECTION`, `provide_information`…), "JSON", "schema", `{"key":` | ordinary words |
| `prompt_echo` | any 8 consecutive words from `receptionist_v1.md` | 7 shared words |
| `unlisted_email` | any email, written or spoken ("x dot y at example dot net"), that is not the caller's live email | the caller's own email, written or spoken |
| `unlisted_phone` | any number of 7 or more digits (digits, spoken digit words, full-width digits) that is not the caller's live phone | the caller's own phone in any spelling (`+1-555-0101`, `555 0101`, "five five five…"); dates, ISO dates, times |
| `link` | `http(s)://`, `www.`, bare domains, spoken domains ("example dot org") | domains inside an email (judged by the email rule); "Thanks.Is that right?" |
| `diagnosis` | "sounds like (you have) an abscess", "you probably have a cavity", "it's most likely gum disease", "that could be pulpitis", "you've got an abscess" | "I've noted a cavity check as the reason", "I can't give a diagnosis" |
| `treatment_advice` | "you'll need a root canal", "I'd recommend a crown", "you should get an extraction", "that tooth should be pulled" | "Do you need a filling looked at?", listing the clinic's services |
| `medication_advice` | dosages (`400 mg`), "take/try/use/apply" + a drug or home remedy, "<drug> should help" | "Are you currently taking any medication?" |
| `price_quote` | currency symbols with amounts, "95 dollars", "eighty dollars", "costs about 60", "20% off", promo codes | "The clinic can tell you about costs", times such as 10:00 |
| `markup` | Markdown (bold, emphasis, headings, list items, links, backticks, code fences), HTML or SSML tags, HTML entities | `3 < 5`, a hyphen, a lone `*` |
| `control_characters` | control, format (zero-width, bidi override), private-use and line/paragraph separator characters, including newlines | ordinary punctuation |
| `too_long` | more than 400 characters | |

Before matching, text is NFKC-normalised, curly apostrophes become `'`, zero-width characters are
removed and other invisible characters become spaces, so look-alikes cannot hide a pattern. The
control and length rules judge the original text.

**Length bound.** The schema allows 600 characters. Two short spoken sentences are 100–250. The
longest legitimate model reply is the read-back in `INFORMATION_REVIEW`; the deterministic read-back
for the demo scenarios is at most 220 characters. 400 characters is about 65 words, or 25 seconds of
speech: longer is a monologue on a phone line and is the usual shape of a prompt dump.

**Conditional sentences.** A commitment pattern does not count when its sentence starts with a
subordinating word before the match (once, when, after, until, if, before, as soon as, whether…).
Negations ("isn't booked", "can't book", "has not been confirmed") never match the patterns.

## Limits

- The rules are clear patterns, not understanding. Paraphrases such as "consider it done, you're in
  for Tuesday" pass. The decision layer still controls state, and a false negative only affects
  wording, never data.
- False positives are cheap by design: the caller hears the deterministic reply instead.
  "I can only collect a request, which the clinic confirms later" is close to the prompt's own
  wording, so a reply that quotes 8 words of it is replaced.
- Spoken numbers are recognised digit by digit ("five five five"), not as "five hundred and
  fifty-five".
