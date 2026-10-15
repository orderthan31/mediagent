# AI Provider Settings

Open Settings from the workspace sidebar (`#/settings`). Select or enter primary
and fallback model IDs separately for transcription and translation. Transcription
supports Gemini, OpenAI, xAI and OpenRouter timestamp-capable models.
Translation supports Gemini, OpenAI, xAI, OpenRouter and Anthropic,
with independently selected primary and fallback providers. Model-list
refresh calls the selected provider's official Models API using its saved/environment key;
it does not generate content. Availability in that list does not guarantee a
model supports this application's audio or structured-output requests.
OpenRouter suggestions are limited to models advertising text output and structured
outputs. Model IDs can also be entered manually (including `vendor/model:variant`).
An API key must be saved before refreshing that provider's model list.

Fallback on request errors and on provider content blocks are independent,
opt-in settings. A fallback can incur additional API charges. A segment switches
to its configured fallback once; later automatic retries stay on that model.
The queue keeps its three-attempt budget (at most four model calls including the
initial switch), and authentication/storage failures do not trigger fallback.
If the fallback also blocks, the existing placeholder and pre-encoding review
policy applies. No prompt rewriting is performed.

Settings apply at the start of the next job/retry, not to an in-flight job.
Completed transcription receipts and completed queue results are preserved.
Translation caches are scoped to primary provider/model and input prompts: changing
the primary provider/model currently selects a separate translation cache, while
changing only the fallback reuses successes under the same primary. A completed
transcription is not rerun just because the translation provider changed.
Changing a fallback does not automatically reprocess completed placeholder cues;
those are still review artifacts, not pending requests.

## Credentials And Access

- A newly entered API key is write-only. Responses report only whether a key
  exists and whether it came from registration or the environment.
- Registered keys take precedence over the corresponding `GEMINI_API_KEY`,
  `OPENAI_API_KEY`, `XAI_API_KEY`, `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`. Removing registration
  returns to the environment key, if one exists. Empty input leaves the key alone.
- Settings are account-scoped when authentication is enabled. Without auth they
  are shared local-instance settings; only expose that mode to trusted users.
- Keys are Fernet-encrypted in `.llm-settings/<account>.json` in the persistent
  jobs volume. The encryption key is `.llm-settings/master.key`; Linux modes are
  0700 for the directory and 0600 for settings/key files. Preserve both on backup.
- This protects plaintext storage/accidental disclosure, not a compromised host
  or an attacker who can read the entire volume, including the encryption key.
  Restrict host/backup ACLs and use HTTPS (e.g. Tailscale Serve) for key entry.
- Credentials are never included in job snapshots, frontend storage or provider
  diagnostics. Invalid API payloads return sanitized errors without echoed input.
- Model-list and generation requests use fixed allowlisted endpoints and never send
  keys in URLs. Arbitrary base URLs and automatic HTTP redirects are not supported.
- Existing single-Gemini encrypted credentials migrate on the next settings save.
  Upgrade API and worker together before using the new settings format.

No key is required just to start Docker and open Settings. A paid job still needs
a key and `PAID_LLM_ENABLED=true`; the settings page cannot disable the paid-call
safety lock. Model IDs and environment keys remain deployment defaults.

## Translation Protocol

The existing three-slot, 40-target queue, cue IDs, context, validation, progress,
stop-and-drain behavior, placeholder policy and timestamp preservation are reused.
Gemini retains the official SDK. Other providers use bounded-time HTTP requests:
OpenAI/xAI/OpenRouter Chat Completions and Anthropic Messages. Strict JSON schemas
wrap the existing result array in a `translations` object; the adapter unwraps it
before existing ID validation. Unsupported model/schema combinations fail explicitly,
never silently degrade to unconstrained text. OpenRouter gateway fallback is disabled;
the application owns fallback selection and requests required schema parameters.

Each external request has a 120-second HTTP timeout and 125-second total deadline,
no transport-level retry, and participates in queue cancellation. 429/5xx responses
are retryable (429 respects shared cooldown); authentication failures do not fallback.
Explicit refusals/content-filter codes use the existing blocked-cue workflow. Incomplete
output is an error, not automatically a content block. Request/response traces include
provider, model and raw usage; payload-free diagnostics include numeric token counts.
Provider usage units and cache/thinking accounting differ, so no common price is assumed.

## Verification Scope

Contract tests use mocked responses, including refusal, rate limit, malformed JSON,
encrypted credentials, key isolation, cancellation, and checkpoint reuse. No paid
cross-provider quality/speed evaluation has been run. Real-model compatibility and
account entitlements still require an explicitly authorized paid smoke test.

See [STT provider research](stt-providers.md) for the separate audio roadmap.

## Transcription Protocol

The STT primary and fallback each select their own provider and model, independently
of translation. Credentials are shared with translation for the same provider.
Existing settings default to Gemini without overwriting registered keys.
`GET /api/settings/llm/stt-models` supplies the supported model catalog to the UI
without making any paid or upstream request. Non-Gemini STT is restricted to known
timestamp-capable contracts, not arbitrary chat or text-only transcription models:

- OpenAI: `whisper-1` (verbose JSON segments), `gpt-4o-transcribe-diarize`
  (diarized JSON with automatic chunking).
- xAI: `grok-voice-transcribe-2.0`, `grok-voice-transcribe-1.0` (word times grouped
  into utterances at punctuation, pauses and five-second boundaries).
- OpenRouter: `microsoft/mai-transcribe-2`, `openai/whisper-large-v3` (verbose JSON).
- Gemini: existing manually entered model IDs and official SDK remain supported.
- Anthropic: not offered for STT until a supported audio/timestamp contract exists.

Dedicated STT uses multipart WAV uploads to fixed endpoints, a language hint (omitted
for auto detection), and a conservative 25 MB per-clip limit. xAI options precede
the file field. No translation prompt or Gemini generation options are sent.
These engines do not implement Gemini's semantic exclusion prompt: singing, cries,
or background voices can still be transcribed. Compare quality on an authorized
sample before replacing Gemini as a production default. OpenRouter's STT gateway
routing is managed by OpenRouter, unlike the chat routing flags used for translation.

All engines retain the 60-second packed-audio clock, three concurrent requests,
queue retry/drain/cancel behavior and original-video timeline restoration. Missing,
reversed or out-of-range timestamps are errors; no timestamps are fabricated.
External response traces retain the full response and usage; request traces retain
clip clock, model, language, byte size and audio hash. The preserved preprocessed
audio can reconstruct the exact clip; no additional audio copies are generated.
Partial queue caches include the primary provider/model. Completed transcription
receipts remain reusable even if settings change; selecting another model does
not force a completed transcription to run again.

Deploy API, worker and web together for the new STT fields and catalog endpoint.
Contract tests do not establish actual account access or real-audio accuracy.
