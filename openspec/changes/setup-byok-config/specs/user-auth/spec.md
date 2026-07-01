## MODIFIED Requirements

### Requirement: Current User Endpoint

The system SHALL expose `GET /api/me` returning the authenticated user's identity and a configuration-completeness flag `text_model_configured` that reflects whether the authenticated user currently has an active text model configuration. The flag SHALL drive the first-configuration gate (text model mandatory before main functionality; image/video optional). The flag SHALL be `true` if and only if the user has at least one active configuration for the `text` purpose, and `false` otherwise.

#### Scenario: Retrieve current user with a configured text model

- **WHEN** an authenticated client who has an active text model configuration calls `GET /api/me`
- **THEN** the system responds with the user's id and username and `text_model_configured: true`

#### Scenario: Retrieve current user without a configured text model

- **WHEN** an authenticated client who has no active text model configuration calls `GET /api/me`
- **THEN** the system responds with the user's id and username and `text_model_configured: false`

#### Scenario: Flag tracks configuration lifecycle

- **WHEN** a user's active text configuration is created or its last remaining text configuration is deleted
- **THEN** a subsequent `GET /api/me` reflects the updated `text_model_configured` value
