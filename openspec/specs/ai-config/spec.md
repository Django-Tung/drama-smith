## Purpose

Defines the BYOK (bring-your-own-key) model configuration capability for Drama Smith: how each authenticated user self-provides and manages provider/model credentials and parameters for the three fixed generation purposes (`text`, `image`, `video`), how those credentials are protected (encrypted at rest, masked in transit), how exactly one active model per purpose is selected, how the mandatory text-model requirement gates entry to main functionality, and how connectivity and provider failures (auth, rate-limit, timeout) are handled at the configuration seam.

## Requirements

### Requirement: BYOK Model Configuration Slots

The system SHALL allow each user to self-provide model credentials (BYOK) for three fixed purposes — `text`, `image`, and `video` — without relying on any platform-wide key. Each model configuration SHALL record its purpose, a whitelisted `provider`, a `model` identifier, the API key (stored encrypted per the API Key Encryption requirement), an optional `base_url`/gateway, optional default call `params` (text: `temperature`/`max_tokens`; image: `size`/`quality`/`n`; video: `duration`/`resolution`/`aspect`), and an open `provider_options` object for vendor-specific extras (e.g. Azure `endpoint`/`api_version`/`deployment`). Every configuration SHALL be associated with the owning user via `user_id` and isolated accordingly.

#### Scenario: A configuration is created for any of the three purposes

- **WHEN** an authenticated client posts a valid configuration (purpose, provider, model, api_key) to `POST /api/me/models`
- **THEN** the system stores it encrypted under the user's id and responds with the created configuration (with the key masked)

#### Scenario: Provider outside the whitelist is rejected

- **WHEN** a configuration references a provider not in the supported whitelist for its purpose
- **THEN** the system responds with a validation error and stores nothing

### Requirement: API Key Encryption

The system SHALL store every API key ONLY as an AES-256-GCM envelope ciphertext: a per-configuration random data encryption key (DEK) encrypts the plaintext key, and the DEK itself is encrypted by a master encryption key (MEK) sourced from the `DS_MEK` environment variable. The MEK SHALL NEVER be persisted, logged, or exposed via the API or OpenAPI schema. The plaintext key SHALL NEVER be persisted, returned, or logged.

#### Scenario: Plaintext key is never persisted or returned

- **WHEN** a configuration is created or updated with a new API key
- **THEN** only the envelope (ciphertext, IV, encrypted DEK) is stored, and no API response, error, or log line contains the plaintext key

#### Scenario: Key round-trips through the envelope for actual use

- **WHEN** the LLM seam needs the key to call a provider
- **THEN** the system decrypts the envelope in memory only (MEK → DEK → plaintext) and never persists or logs the plaintext

### Requirement: Masked Key Display

The system SHALL mask API keys whenever they are surfaced — in listings, detail responses, and logs — showing only a prefix and the last 4 characters (e.g. `sk-…ab12`). The full plaintext SHALL NOT be retrievable through any endpoint.

#### Scenario: List and detail responses mask the key

- **WHEN** an authenticated client lists or fetches its model configurations
- **THEN** every key is shown masked and the full plaintext is absent from the response

### Requirement: Active Model Per Purpose

For each purpose, a user MAY hold zero to many configurations; whenever at least one configuration exists for a purpose, the system SHALL keep exactly one of them marked `is_active` as the "current" model for that purpose (zero configurations means the purpose is unavailable). The system SHALL enforce this invariant for each `(user_id, purpose)` pair via a database uniqueness constraint on active rows. Switching the active model SHALL flip only the `is_active` marker and SHALL NOT alter the key or params.

#### Scenario: First configuration of a purpose becomes active automatically

- **WHEN** a user creates the first configuration for a purpose that previously had none
- **THEN** that configuration is marked active for that purpose

#### Scenario: Activating one config deactivates the others of the same purpose

- **WHEN** a client posts to `POST /api/me/models/:id/activate` for a configuration
- **THEN** that configuration becomes the active one for its purpose and any previously active configuration of the same purpose is deactivated, in a single transaction

#### Scenario: Only one active configuration per purpose is permitted

- **WHEN** the database already holds an active configuration for a `(user_id, purpose)` and an operation would introduce a second
- **THEN** the uniqueness constraint prevents it and the invariant is preserved

### Requirement: Model Configuration Management

The system SHALL provide CRUD over model configurations scoped to the authenticated user: list (`GET /api/me/models`), create (`POST /api/me/models`), update (`PUT /api/me/models/:id`, which SHALL NOT touch the key unless a new key is supplied), delete (`DELETE /api/me/models/:id`), and activate (`POST /api/me/models/:id/activate`). All access SHALL be scoped by `user_id`; a request touching another user's configuration SHALL respond 404 without revealing existence.

#### Scenario: Update without a new key preserves the existing key

- **WHEN** a client updates provider/model/params without supplying a new api key
- **THEN** the stored key is re-encrypted-and-kept unchanged and no plaintext is re-exposed

#### Scenario: Cross-user access is denied as not-found

- **WHEN** an authenticated user requests, updates, deletes, activates, or tests a configuration owned by another user
- **THEN** the system responds 404 and performs no action

#### Scenario: Deleting the active configuration with siblings remaining

- **WHEN** a user deletes the active configuration for a purpose while other configurations of that purpose remain
- **THEN** the system requires a new active to be designated (or rejects the deletion), so that exactly-one-active is maintained

### Requirement: Mandatory Text Model Configuration

The system SHALL require a newly registered user to configure an active text model before entering main functionality; image and video models are optional. When no image model is configured, image-dependent features SHALL be gated off (disabled) without blocking entry; likewise for video. `GET /api/me` SHALL expose a `text_model_configured` flag reflecting whether the user has an active text configuration, to drive the first-configuration gate on the client.

#### Scenario: First login forces text configuration

- **WHEN** a user logs in and has no active text model configuration
- **THEN** the client routes them to the configuration wizard, and main functionality is gated until a text model is configured

#### Scenario: Optional image/video do not block entry

- **WHEN** a user has configured a text model but no image or video model
- **THEN** the user may enter main functionality, and image-/video-dependent features are disabled but entry is not blocked

#### Scenario: Deleting the last text configuration re-triggers the requirement

- **WHEN** a user deletes their last remaining text configuration (so zero text configs exist)
- **THEN** the system marks the purpose as unconfigured and `GET /api/me` reports `text_model_configured: false`, re-triggering the mandatory-configuration gate

#### Scenario: Deleting the last image or video configuration only disables that feature

- **WHEN** a user deletes their last image (or video) configuration
- **THEN** only the corresponding feature is disabled; the user is not forced back into the wizard and entry is not blocked

### Requirement: Zero-Cost Connectivity Self-Test

The system SHALL provide `POST /api/me/models/:id/test` to verify authentication and connectivity for a single configuration WITHOUT performing any real generation (no text completion, no image, no video) and thus without incurring generation cost. On completion the system SHALL record `last_tested_at`. For providers that do not offer a zero-cost probe, the system SHALL degrade gracefully (best-effort probe or skip with an explicit, non-blocking outcome) rather than silently failing.

#### Scenario: Successful connectivity test incurs no generation cost

- **WHEN** a client tests a valid configuration
- **THEN** the system performs only a zero-cost authentication/connectivity probe, records `last_tested_at`, and reports success without generating any content

#### Scenario: Failed or degraded test is surfaced clearly

- **WHEN** a tested configuration fails the probe, or its provider has no zero-cost probe
- **THEN** the system reports the explicit outcome (failure reason or degradation) without raising an unhandled error

### Requirement: Credential Invalidation on Provider Auth Failure

At runtime, when a provider call returns 401/403 or an authentication failure, the system SHALL mark the corresponding `model_configs.status` as `invalid` and surface a reconfiguration prompt, consistent with the per-purpose active/inactive and mandatory-configuration rules. The invalid status SHALL be visible in the configuration's detail/list representation.

#### Scenario: Provider auth failure marks the configuration invalid

- **WHEN** a provider call for a configuration returns 401/403 or an authentication failure
- **THEN** the system sets that configuration's `status` to `invalid` and the detail response reflects the invalid status, prompting the user to reconfigure

### Requirement: Provider Timeout, Retry, and Rate-Limit Handling

The system SHALL apply, per purpose, a default timeout and bounded retry, mapping provider 429/timeout outcomes to a defined client error (retry or degrade per purpose) without indefinite blocking. The relevant parameters SHALL be sourced from system defaults and/or the configuration's `provider_options`. Failures SHALL map to the unified error codes `rate_limited` (provider 429/timeout → 502) and `quota_exceeded` (user concurrency/quota → 429) as defined by the backend error contract.

#### Scenario: Provider rate-limit is mapped to a defined error

- **WHEN** a provider returns 429 or times out within bounded retry
- **THEN** the system surfaces a `rate_limited` error (HTTP 502) rather than hanging or retrying indefinitely

#### Scenario: Self-test does not bypass rate-limit handling

- **WHEN** a connectivity self-test encounters a provider 429/timeout
- **THEN** the system surfaces the same bounded outcome rather than silently swallowing it
