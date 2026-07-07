## ADDED Requirements

### Requirement: Drama and Episode Containers

The system SHALL provide two levels of organization containers — Drama (`dramas`) and Episode (`episodes`) — both owned by and isolated to the authenticated user. A user SHALL be able to create a drama (with a name), create episodes under a drama (with a title, an `aspect_ratio` from `16:9`/`9:16`/`1:1`/`4:3`, and an optional `style_preset`), list their dramas and the episodes under a drama, rename/update (including `sort_order`, aspect ratio, style preset), and soft-delete them. Every drama and episode SHALL be associated with the owning user via the ownership chain (`dramas.user_id` directly; `episodes` via `drama_id → dramas.user_id`). A request referencing another user's drama or episode SHALL respond 404 without revealing existence. Deleting a drama or episode SHALL be a soft delete (`deleted_at`); soft-deleted resources SHALL be excluded from lists and detail lookups. This corresponds to FR-A1.

#### Scenario: A user creates a drama and an episode under it

- **WHEN** an authenticated client posts a drama to `POST /api/dramas`, then posts an episode (with aspect ratio and optional style preset) to `POST /api/dramas/:dramaId/episodes`
- **THEN** the system creates both owned by the user and returns the created resources, with the episode attached to the specified drama

#### Scenario: Episodes carry episode-wide aspect ratio and style preset

- **WHEN** an episode is created or updated
- **THEN** its `aspect_ratio` (one of `16:9`, `9:16`, `1:1`, `4:3`) and optional `style_preset` are persisted and returned on subsequent reads

#### Scenario: Cross-user access to a drama or episode is denied as not-found

- **WHEN** an authenticated user requests, updates, deletes, or creates a child resource under a drama or episode owned by another user
- **THEN** the system responds 404 and performs no action

#### Scenario: Deletion is soft and removes the resource from listings

- **WHEN** a user deletes a drama or episode via `DELETE`
- **THEN** the resource is marked with a `deleted_at` timestamp, excluded from list and detail responses, and its children are no longer reachable through it

### Requirement: Script Input and Versioning

Each episode SHALL hold at most one script (1:1 via `scripts.episode_id`). The system SHALL accept script input via `PUT /api/episodes/:id/script` as plain text, Markdown, or Fountain (`format` ∈ `plain`/`markdown`/`fountain`; binary formats such as `.docx`/`.pdf` are out of scope for this milestone). Writing or materially rewriting a script SHALL create a new immutable `script_versions` row (`source = 'input'`), and `scripts.current_version_id` SHALL point at the currently effective version so the script can be reverted to any prior version. The current script content and format SHALL be readable via the episode. This corresponds to FR-A2 and the versioning intent of FR-A3.

#### Scenario: A script is written and retained as a version

- **WHEN** an authenticated client writes a script (content + format) to an episode it owns via `PUT /api/episodes/:id/script`
- **THEN** the system stores it as a new script version with `source='input'`, sets it as the current version, and subsequent reads return that content and format

#### Scenario: The current script can be reverted to a prior version

- **WHEN** a user reverts the current script to a previous version
- **THEN** `scripts.current_version_id` is moved to that version without deleting later versions, and reads reflect the reverted content

#### Scenario: A script cannot be written to another user's episode

- **WHEN** a client attempts to write a script to an episode owned by another user
- **THEN** the system responds 404 and stores nothing

### Requirement: Script AI Optimization

The system SHALL provide `POST /api/episodes/:id/script/optimize` to perform AI-assisted copy-edit optimization (format normalization, typo/punctuation fixes, dialogue polishing) on the current script as an asynchronous task (`type='optimize'`) dispatched through the task executor. Optimization SHALL perform copy-edit only and SHALL NOT restructure the script (e.g. reorder scenes, rewrite structure, or re-segment acts); structural and pacing insights belong to the breakdown's pacing dimension (`analyses.result.pacing`), not to script optimization. Optimization SHALL require an active text model configuration for the user; if none exists the request SHALL fail with `model_not_configured` (409). A successful optimization SHALL produce a new script version with `source='optimize'` and SHALL return a paragraph-level diff against the current version computed server-side (via the standard-library difflib, with paragraphs split by format-appropriate delimiters), enabling the user to preview the change as a read-only comparison. The client SHALL render this diff read-only; the user SHALL be able to accept the optimized version (which moves `current_version_id` to it) or reject it (which leaves `current_version_id` unchanged while still retaining the optimized version for later review/revert), and adoption is whole-version (no per-paragraph partial adoption). This corresponds to FR-A3 (copy-edit scope) and relies on the Task Record Prototype requirement.

#### Scenario: Optimization requires a configured text model

- **WHEN** a user without an active text model configuration requests script optimization
- **THEN** the system responds 409 `model_not_configured` and starts no task

#### Scenario: Optimization runs asynchronously and returns a version with a server-computed diff

- **WHEN** a user with an active text model requests optimization of a script they own
- **THEN** the system creates an `optimize` task, returns its task id (so the client can poll progress), and on completion produces a new `source='optimize'` script version plus a paragraph-level diff against the current version computed server-side via difflib

#### Scenario: Optimization is copy-edit only and does not restructure the script

- **WHEN** a script is optimized
- **THEN** the optimization fixes formatting, typos/punctuation, and polishes dialogue but does not reorder scenes or rewrite structure; structural and pacing insights are instead produced by the breakdown's pacing dimension

#### Scenario: The diff is read-only and adoption is whole-version

- **WHEN** the optimized version is presented to the user
- **THEN** the client renders the server-computed paragraph diff as a read-only comparison, and the user may accept the whole optimized version or reject it (no per-paragraph partial adoption)

#### Scenario: The user accepts or rejects the optimized version

- **WHEN** the user accepts the optimized version
- **THEN** `current_version_id` moves to the optimized version; and **WHEN** the user rejects it, `current_version_id` is unchanged and the optimized version is still retained for later review or revert

### Requirement: Episode Characters

The system SHALL provide CRUD over episode characters (`GET/POST/PUT/DELETE /api/episodes/:id/characters`, `GET/PUT/DELETE /api/episodes/:id/characters/:cid`) scoped to the authenticated user, where each character carries `name`, optional `role_type`/`persona`/`motivation`/`traits`/`appearance_desc`, a `source` of `preset` or `analysis`, and `sort_order`. Characters that a user pre-configures SHALL be stored with `source='preset'`. Characters produced by text breakdown SHALL be materialized into `episode_characters` with `source='analysis'`. Both sources SHALL be surfaced together in the episode's character list, distinguishable by `source`, and the system SHALL NOT automatically merge or delete characters; deduplication of plausibly-duplicate characters across sources is performed manually by the user via the character CRUD. This corresponds to FR-A4 (automated merge-suggestion by name similarity, and character library import/`source='library'` with promote/clone flows, are out of scope for this milestone).

#### Scenario: A user pre-configures characters on an episode

- **WHEN** an authenticated client creates a character on an episode it owns via `POST /api/episodes/:id/characters`
- **THEN** the system stores it with `source='preset'` scoped to that episode and user, and subsequent reads return it

#### Scenario: Breakdown-produced characters are materialized and traced

- **WHEN** a text breakdown completes successfully
- **THEN** the characters extracted by the breakdown are written to `episode_characters` with `source='analysis'`, available alongside pre-configured characters

#### Scenario: Both preset and analysis characters coexist; dedup is manual

- **WHEN** a breakdown produces a character that plausibly duplicates a pre-configured one (e.g. same name)
- **THEN** the system stores both (distinguished by `source`) and performs no automatic merge; the user deduplicates manually via the character CRUD

#### Scenario: Cross-user access to an episode character is denied as not-found

- **WHEN** an authenticated user requests, updates, or deletes a character under an episode owned by another user
- **THEN** the system responds 404 and performs no action

### Requirement: Structured Text Breakdown

The system SHALL provide `POST /api/episodes/:id/analyze` to run a structured text breakdown of the current script as an asynchronous task (`type='analyze'`) dispatched through the task executor and orchestrated by a LangGraph analysis graph (`extract_characters → analyze_plot | analyze_conflict | analyze_pacing → split_shots`). The breakdown SHALL require (a) an active text model configuration for the user, else `model_not_configured` (409); and (b) a current script on the episode, else a validation error. A successful breakdown SHALL produce a result of `{characters, plotlines, conflicts, pacing}` persisted on an `analyses` record, plus a list of shots (`shots`) split by dramatic beats with each shot targeting 3–15 seconds (estimated by the text model), each shot carrying sequence, description, shot type, scene, plot point/emotion, appearing characters, dialogue (text), and target duration, with traceability to plotlines/conflicts. Breakdown-produced characters SHALL be materialized per the Episode Characters requirement, including merge suggestions against pre-configured characters. The analysis graph nodes SHALL consume the text model exclusively through the `core/llm` seam and SHALL NOT directly import any provider SDK. A successful breakdown SHALL record the script version it was based on (`analyses.script_version_id`) and SHALL become the episode's current analysis by moving `episodes.current_analysis_id` to it. The current shot list returned by `GET /api/episodes/:id/shots` SHALL be the shots of the episode's current analysis. Re-running a breakdown SHALL create a new analysis and new shots while preserving prior analyses (and their shots) as read-only history that the user can switch back to via `PATCH /api/episodes/:id/analysis/current`. When the current script version no longer matches the version the current analysis was based on, the system SHALL surface a stale flag/notice but SHALL NOT automatically discard the analysis. `GET /api/episodes/:id/analysis` SHALL return the current analysis, any in-flight breakdown task, and a stale flag. The breakdown result SHALL be readable via `GET /api/episodes/:id/analysis`. This corresponds to FR-A5 and relies on the Task Record Prototype requirement.

#### Scenario: Breakdown requires a configured text model and a script

- **WHEN** a user without an active text model requests a breakdown, or requests a breakdown on an episode with no current script
- **THEN** the system responds 409 `model_not_configured` (no model) or a validation error (no script) and starts no task

#### Scenario: Breakdown runs asynchronously through the analysis graph

- **WHEN** a user with an active text model and a current script requests a breakdown on an episode they own
- **THEN** the system creates an `analyze` task, returns its task id, runs the LangGraph analysis graph through the `core/llm` text seam, and on completion persists the four-dimension result plus the shot list

#### Scenario: Shots target 3–15 seconds and are traceable

- **WHEN** a breakdown completes
- **THEN** each produced shot has a `target_duration` within 3–15 seconds (or is flagged when the model could not satisfy it), and carries the fields needed for downstream editing including traceability to plotlines/conflicts

#### Scenario: Only one in-flight breakdown per episode

- **WHEN** a breakdown is already `pending` or `running` for an episode and another breakdown is requested for the same episode
- **THEN** the system responds 409 `invalid_state` rather than starting a concurrent breakdown

#### Scenario: Provider auth failure during breakdown invalidates the model and fails the task

- **WHEN** a provider call during breakdown returns 401/403 or an authentication failure
- **THEN** the corresponding model configuration is marked `status='invalid'` and the task transitions to `failed` with error code `provider_auth_failed`

#### Scenario: The current shot list belongs to the current analysis

- **WHEN** a breakdown completes (or the user switches the current analysis)
- **THEN** the episode's current-analysis pointer is set to it, and `GET /api/episodes/:id/shots` returns the shots of that current analysis

#### Scenario: Re-analyzing preserves the prior analysis as switchable history

- **WHEN** a user re-runs a breakdown while a current analysis already exists for the episode
- **THEN** the system creates a new analysis and a new shot list, moves the current-analysis pointer to it, and keeps the prior analysis and its shots as read-only history that the user can switch back to via `PATCH /api/episodes/:id/analysis/current`

#### Scenario: An analysis stale to the current script is flagged but not discarded

- **WHEN** the current script version no longer equals the version the current analysis was based on (e.g. after an accepted optimization or a revert)
- **THEN** `GET /api/episodes/:id/analysis` reports a stale flag, the system surfaces a stale notice, and it does not automatically discard or overwrite the analysis

#### Scenario: Shot appearing characters are resolved to character ids at persistence time

- **WHEN** a breakdown completes and its shots (with appearing characters referenced by name) are persisted
- **THEN** the system resolves each appearing character name to an episode_character_id via normalized name matching (preset characters taking priority on collision), inserts all extracted characters as `source='analysis'` regardless, and skips any name that does not match (without blocking persistence) rather than auto-merging characters

### Requirement: Shot Management and Editing

The system SHALL provide interactive editing of an episode's shot list: read the current analysis's shot list (`GET /api/episodes/:id/shots`, i.e. the shots of the episode's current analysis), edit a single shot's fields (`PATCH /api/shots/:id`: description, shot type, scene, plot point/emotion, appearing characters, dialogue, target duration, camera move), split a shot into multiple (`POST /api/shots/:id/split`), and merge with an adjacent shot (`POST /api/shots/:id/merge`). Split, merge, and reorder operations SHALL recompute and persist a gap-free ordering (`seq`) for the episode within a single transaction. After any edit, if a shot's `target_duration` falls outside 3–15 seconds, the system SHALL surface a soft out-of-range notice SHALL NOT block the save (deferring to human confirmation). All shot operations SHALL be scoped by `user_id`; a request touching another user's shot or episode SHALL respond 404. This corresponds to FR-A6.

#### Scenario: A single shot's fields are edited

- **WHEN** an authenticated client patches a shot it owns via `PATCH /api/shots/:id`
- **THEN** the specified fields are updated and the updated shot is returned

#### Scenario: Splitting a shot produces ordered shots

- **WHEN** a client splits a shot via `POST /api/shots/:id/split`
- **THEN** the shot is replaced by multiple shots in sequence and the episode's `seq` ordering is recomputed gap-free within a single transaction

#### Scenario: Merging adjacent shots combines them and reorders

- **WHEN** a client merges a shot with an adjacent shot via `POST /api/shots/:id/merge`
- **THEN** the two shots are combined (description/dialogue concatenated, duration summed, appearing characters unioned), one is removed, and the episode's `seq` ordering is recomputed gap-free within a single transaction

#### Scenario: Out-of-range duration is surfaced but does not block editing

- **WHEN** an edit, split, or merge results in a `target_duration` outside 3–15 seconds
- **THEN** the system persists the change and returns an out-of-range notice rather than rejecting the request

#### Scenario: Cross-user access to a shot is denied as not-found

- **WHEN** an authenticated user patches, splits, or merges a shot belonging to another user's episode
- **THEN** the system responds 404 and performs no action

### Requirement: Task Record Prototype

The system SHALL persist long-running pipeline steps (script optimization and text breakdown in this milestone) as task records (`tasks`) owned by and isolated to the authenticated user, each with `type`, `status` (`pending`/`running`/`succeeded`/`failed`/`canceled`/`interrupted`), `progress` (0–100), `stage`, `input_snapshot` (including a snapshot of the active model configuration used), `output_refs`, `error`, and a created/started/finished timeline. Tasks SHALL be executed by an in-process asyncio task executor with a per-user concurrency limit (default 3–5) and a global worker cap; tasks exceeding the limit SHALL remain `pending` (queued). The system SHALL provide `GET /api/tasks/:id` to poll a single task's status, progress, stage, error, and output refs as the REST baseline channel, so a user can close the page and return to observe progress and any landed outputs. On process startup, any task left in `running` SHALL be transitioned to `interrupted` (error code `restart_interrupted`) rather than auto-resumed. A task touching another user's data SHALL respond 404. The system SHALL provide `POST /api/tasks/:id/cancel` to cooperatively cancel a `running` task (already-landed outputs preserved; task transitions to `canceled`) so a stuck long-running step does not block re-initiation. The WebSocket `/ws/tasks` real-time channel, the cross-episode aggregation list `GET /api/tasks`, and the `retry` endpoint are out of scope for this milestone. This corresponds to the FR-A11 embryonic task-record slice.

#### Scenario: A long step is persisted as a queued or running task

- **WHEN** a user initiates a breakdown or optimization
- **THEN** the system creates a `tasks` record scoped to the user and episode; if the per-user concurrency limit is reached the task stays `pending`, otherwise it transitions to `running`

#### Scenario: A task can be polled across page reloads

- **WHEN** an authenticated client polls `GET /api/tasks/:id` for its own task, including after closing and reopening the page
- **THEN** the system returns the task's current status, progress, stage, error (if any), and output refs, reflecting the server record as the single source of truth

#### Scenario: A process restart interrupts in-flight tasks

- **WHEN** the process restarts with one or more tasks left in `running`
- **THEN** those tasks are transitioned to `interrupted` with error code `restart_interrupted` and are not auto-resumed

#### Scenario: The input snapshot captures the active model configuration

- **WHEN** a task is created
- **THEN** `input_snapshot` records the inputs and a snapshot of the active model configuration at submission time, so a later change to the user's configuration does not affect the in-flight call

#### Scenario: A running task can be canceled to unblock re-initiation

- **WHEN** an authenticated client cancels its own `running` task via `POST /api/tasks/:id/cancel`
- **THEN** the system cooperatively stops the task, preserves any already-landed outputs, transitions the task to `canceled`, and a new breakdown or optimization may then be initiated for the same episode

#### Scenario: Cross-user access to a task is denied as not-found

- **WHEN** an authenticated user polls or cancels a task owned by another user
- **THEN** the system responds 404 and reveals nothing
