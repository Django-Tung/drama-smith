## ADDED Requirements

### Requirement: User Registration

The system SHALL allow a user to register with a unique username and a password, without invite codes and without email verification. The username SHALL be 3–32 characters of letters, digits, or underscores and SHALL be unique across the system. On success the system SHALL create the user and issue an access token and a refresh token (same shape as login).

#### Scenario: Successful registration

- **WHEN** a client posts a valid username and password to `POST /api/auth/register`
- **THEN** the system creates the user (password stored as argon2id hash) and responds 201 with an access token and a refresh token

#### Scenario: Duplicate username is rejected

- **WHEN** a client registers a username that already exists
- **THEN** the system responds with a conflict error and creates no user

#### Scenario: Invalid username or weak password is rejected

- **WHEN** a client posts a username violating the format rules, or a password shorter than 8 characters or lacking both letters and digits
- **THEN** the system responds with a validation error and creates no user

### Requirement: Password Hashing

The system SHALL store user passwords ONLY as an argon2id hash with salt. Plaintext passwords SHALL NEVER be persisted, returned, or logged.

#### Scenario: Password stored as argon2id hash only

- **WHEN** a user registers or otherwise sets a password
- **THEN** only the argon2id hash is stored; the plaintext is absent from the database, responses, and logs

### Requirement: User Login and Token Issuance

The system SHALL authenticate a user by username and password and, on success, issue a short-lived JWT access token (HS256, 15 minutes, stateless) and an opaque refresh token (7 days). On failure the system SHALL respond 401 and increment the account's failed-login counter.

#### Scenario: Successful login

- **WHEN** a client posts valid credentials to `POST /api/auth/login`
- **THEN** the system responds with an access token and a refresh token and resets that account's failed-login counter

#### Scenario: Wrong password

- **WHEN** a client posts an incorrect password for an existing username
- **THEN** the system responds 401 and increments the failed-login counter for that account

### Requirement: Brute-Force Lockout

The system SHALL lock an account after 5 consecutive failed login attempts for 15 minutes, scoped to the account only (not by IP). The lock SHALL auto-expire; a successful login SHALL reset the counter.

#### Scenario: Account locked after repeated failures

- **WHEN** 5 consecutive failed logins occur for an account
- **THEN** further login attempts for that account within 15 minutes are rejected as locked, even with the correct password

#### Scenario: Lock auto-expires

- **WHEN** the 15-minute lock window elapses
- **THEN** the account is usable again and the failed-login counter is reset

#### Scenario: Successful login resets counter

- **WHEN** a login succeeds before the lock threshold is reached
- **THEN** the failed-login counter is reset to zero

### Requirement: Access Token Authentication

All non-auth endpoints SHALL require a valid `Authorization: Bearer <access_token>` header. The access token SHALL be a HS256 JWT carrying `sub` (user id), `username`, `iat`, `exp`, and SHALL be stateless (no server-side session).

#### Scenario: Valid token authorizes request

- **WHEN** a request carries a valid, unexpired access token
- **THEN** the system authenticates the request as the token's user

#### Scenario: Missing, invalid, or expired token rejected

- **WHEN** a request carries no token, a malformed token, or an expired token
- **THEN** the system responds 401

### Requirement: Refresh Token and Rotation

The system SHALL issue an opaque refresh token whose hash is stored server-side (never the plaintext), associated with the user and an expiry. A refresh token SHALL be revocable. A valid, non-expired, non-revoked refresh token SHALL obtain a new access token via `POST /api/auth/refresh`.

#### Scenario: Valid refresh obtains new access token

- **WHEN** a client posts a valid refresh token to `POST /api/auth/refresh`
- **THEN** the system responds with a new access token

#### Scenario: Revoked or expired refresh rejected

- **WHEN** a client posts a revoked or expired refresh token
- **THEN** the system responds 401 and issues no access token

### Requirement: Logout and Revocation

The system SHALL revoke the refresh token on `POST /api/auth/logout`; the client SHALL discard its tokens.

#### Scenario: Logout revokes refresh token

- **WHEN** an authenticated client posts to `POST /api/auth/logout`
- **THEN** the associated refresh token is marked revoked and can no longer be used to refresh

### Requirement: Current User Endpoint

The system SHALL expose `GET /api/me` returning the authenticated user's identity and a configuration-completeness flag indicating whether a text model is configured. In this milestone the flag SHALL always be `false`, since model configuration is out of scope.

#### Scenario: Retrieve current user

- **WHEN** an authenticated client calls `GET /api/me`
- **THEN** the system responds with the user's id and username and `text_model_configured: false`

### Requirement: Multi-Tenant Data Isolation

The system SHALL associate every user-owned record with a `user_id` and SHALL scope all data access by the authenticated user's id. Accessing a record that does not belong to the authenticated user SHALL respond 404, without exposing the record's existence.

#### Scenario: Own record is accessible

- **WHEN** an authenticated user requests a resource they own
- **THEN** the system returns the resource

#### Scenario: Other user's record is not exposed

- **WHEN** an authenticated user requests a resource owned by another user
- **THEN** the system responds 404 regardless of whether the resource exists

#### Scenario: Listings are scoped to the authenticated user

- **WHEN** an authenticated user lists resources
- **THEN** only resources owned by that user are returned
