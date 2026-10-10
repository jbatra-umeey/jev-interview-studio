# Jev Interview Studio — SaaS architecture

**Status: proposed production design, not deployed infrastructure.** The first diagram describes the checked-in prototype. All subsequent diagrams describe a target architecture and require implementation, security review, infrastructure provisioning, and operational validation.

This reference uses a cloud-neutral, single-region, multiple-availability-zone deployment. Start with a modular FastAPI service plus separate workers; split services only when scaling or isolation requires it. No cloud account, region, capacity, availability SLA, or recovery target has been selected.

## 1. Current implementation

```mermaid
flowchart LR
    browser["React web client"]
    mobile["Expo mobile client"]
    edge["Caddy HTTPS gateway — optional production Compose profile"]
    web["Nginx — static web and local API proxy"]
    api["FastAPI — authentication, interviews, billing, LangGraph"]
    db[("SQLite — persistent Docker volume")]
    ai["AI provider — scoring, follow-up, transcription"]
    stripe["Stripe Checkout and signed webhooks"]
    traces["Langfuse — optional follow-up traces"]
    browser -->|"Local HTTP"| web
    browser -->|"HTTPS profile"| edge
    mobile -->|"Configured API URL"| edge
    edge -->|"Static assets"| web
    edge -->|"API requests"| api
    web -->|"Local API requests"| api
    api -->|"User-scoped queries"| db
    api -->|"Server-side API key"| ai
    api <-->|"Checkout and events"| stripe
    api -.->|"Metadata only"| traces
```

Source: [Compose](../../docker-compose.yml), [HTTPS profile](../../compose.production.yml), [Caddy routes](../../Caddyfile), [API](../../backend/app/main.py), and [integrations](../../backend/app/advanced.py). Mobile development can also connect directly to a separately launched API using its LAN address.

The prototype has user-level isolation, turn-based audio transcription, a browser JavaScript sandbox, and synchronous AI calls. It does **not** implement organization tenants, managed PostgreSQL, durable interview jobs, streaming voice, a remote code judge, or production quota enforcement.

## 2. Proposed production deployment

```mermaid
flowchart TB
    clients["Web and mobile clients"]
    identity["Managed identity provider — OIDC and MFA"]
    edge["DNS, CDN, WAF and TLS"]
    assets["Versioned web assets"]
    ingress["Regional load balancer — API and WebSocket routes"]
    subgraph privateNetwork ["Private application network — multiple availability zones"]
        api["Stateless FastAPI replicas — authorization and quotas"]
        workers["Interview workers — LangGraph execution"]
        outbox["Outbox dispatcher — durable job delivery"]
        queue["Managed job queue and dead-letter queue"]
        pg[("Managed PostgreSQL — multi-zone failover")]
        redis[("Redis — rate limits and short-lived state")]
        storage[("Encrypted object storage — consented media")]
        secrets["Secrets manager — workload identity"]
        telemetry["Telemetry collector — redaction and sampling"]
    end
    providers["AI and speech providers"]
    observe["Metrics, logs, alerts and Langfuse"]
    backups[("Isolated encrypted backups")]
    clients -->|"Sign in"| identity
    clients -->|"HTTPS"| edge
    edge -->|"Cache static content"| assets
    edge -->|"Dynamic traffic"| ingress
    ingress --> api
    api -->|"Verify issuer, audience and signature"| identity
    api -->|"Tenant transactions and job outbox"| pg
    pg -->|"Pending outbox records"| outbox
    outbox -->|"At-least-once delivery"| queue
    queue -->|"Jobs"| workers
    workers -->|"Checkpoints and results"| pg
    api --> redis
    api --> storage
    workers -->|"Allowlisted egress"| providers
    secrets -.->|"Scoped secrets"| api
    secrets -.->|"Scoped secrets"| workers
    api -.-> telemetry
    workers -.-> telemetry
    telemetry -.-> observe
    pg -->|"Point-in-time recovery"| backups
    storage -->|"Versioning and retention"| backups
```

Only the edge and ingress expose public application endpoints. Database, cache, and queue access use private connectivity and distinct workload roles. API authorization remains mandatory even behind the WAF. Redis is not the system of record for billing or durable usage accounting. Multi-zone replicas improve resilience but do not establish cross-region disaster recovery.

Use bounded queues, per-tenant concurrency and token budgets, provider timeouts, circuit breakers, and backpressure. Alert on queue age, API error rate, latency, provider failures, and cost. Select measurable SLOs and recovery objectives before launch, then prove them with load tests and restore drills. Raw answers, audio, credentials, and payment data must not enter routine logs or traces.

## 3. Proposed authenticated interview flow

```mermaid
sequenceDiagram
    actor candidate as Candidate
    participant client as Web or mobile
    participant api as FastAPI
    participant db as PostgreSQL
    participant dispatch as Outbox dispatcher
    participant queue as Job queue
    participant worker as LangGraph worker
    participant ai as AI provider
    candidate->>client: Submit answer with request ID
    client->>api: Token, session ID, answer, idempotency key
    api->>api: Validate identity, tenant membership and input
    api->>db: Verify ownership and entitlement and reserve quota
    alt Unauthorized or quota exhausted
        db-->>api: Deny
        api-->>client: Access or quota error
    else Authorized
        api->>db: Atomically store job, quota reservation and outbox record
        api-->>client: Accepted with job ID
        dispatch->>db: Read pending outbox record
        dispatch->>queue: Publish job ID
        dispatch->>db: Mark outbox record delivered
        queue->>worker: Deliver job, possibly more than once
        worker->>db: Claim job and load tenant-scoped state and checkpoint
        worker->>ai: Evaluate answer and generate follow-up with bounded retries
        ai-->>worker: Structured evaluation
        worker->>worker: Validate output schema and enforce limits
        worker->>db: Persist result and actual usage and settle reservation
        worker->>queue: Acknowledge completed job
        client->>api: Poll job status or subscribe to authenticated updates
        api->>db: Read result after ownership check
        api-->>client: Evaluation and follow-up
    end
```

Outbox delivery and queue processing are at least once. Deduplicate by stable job/request ID, use leased job claims, and make database state transitions idempotent. A crash after a provider call can still repeat a billable request; use provider idempotency where supported and enforce retry budgets. Retry transient failures only; send exhausted jobs to a dead-letter queue and release or reconcile abandoned quota reservations. Worker checkpoints and results must share the same tenant boundary.

For a future full-duplex voice mode, add an authenticated WebSocket/WebRTC media session with short-lived credentials, concurrent-session limits, interruption handling, and transcript consent. The current record-and-transcribe endpoint is not that streaming system.

## 4. Proposed tenant and data model

```mermaid
erDiagram
    USER ||--o{ MEMBERSHIP : joins
    TENANT ||--o{ MEMBERSHIP : grants
    TENANT ||--o{ INTERVIEW_SESSION : owns
    USER ||--o{ INTERVIEW_SESSION : starts
    INTERVIEW_SESSION ||--o{ ANSWER : contains
    INTERVIEW_SESSION ||--o{ INTERVIEW_JOB : schedules
    INTERVIEW_JOB ||--o{ CHECKPOINT : persists
    TENANT ||--o{ USAGE_EVENT : meters
    TENANT ||--o| SUBSCRIPTION : subscribes
    SUBSCRIPTION ||--o{ BILLING_EVENT : reconciles
    USER {
        uuid id PK
        string identity_subject UK
    }
    TENANT {
        uuid id PK
        string name
    }
    MEMBERSHIP {
        uuid tenant_id PK,FK
        uuid user_id PK,FK
        string role
    }
    INTERVIEW_SESSION {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string track
    }
    ANSWER {
        uuid id PK
        uuid tenant_id FK
        uuid session_id FK
        string encrypted_content
    }
    INTERVIEW_JOB {
        uuid id PK
        uuid tenant_id FK
        uuid session_id FK
        string idempotency_key
        string state
    }
    CHECKPOINT {
        uuid id PK
        uuid tenant_id FK
        uuid job_id FK
        string encrypted_state
    }
    USAGE_EVENT {
        uuid id PK
        uuid tenant_id FK
        uuid job_id FK
        int billable_units
    }
    SUBSCRIPTION {
        uuid id PK
        uuid tenant_id FK
        string provider_subscription_id UK
        string entitlement_state
    }
    BILLING_EVENT {
        string provider_event_id PK
        uuid subscription_id FK
        string processing_state
    }
```

This is a logical model, not a migration file. Apply composite foreign keys such as `(tenant_id, session_id)` and unique `(tenant_id, idempotency_key)` constraints. Derive tenant context from verified identity and membership, never from an unverified client header. Enforce ownership in the API and PostgreSQL row-level security with transaction-local tenant context; pooled connections must not retain tenant state, and application roles must not bypass RLS. Extend tenant checks to object keys, job payloads, caches, and checkpoints.

Each user can initially receive a personal tenant. Organization membership is a future capability, not a property of the current SQLite schema. Define deletion and retention policies across active data, provider-side data, and backups before collecting production interview material.

## 5. Proposed billing and isolated code execution

```mermaid
flowchart LR
    user["Authenticated client"]
    api["FastAPI — tenant and entitlement checks"]
    stripe["Stripe"]
    webhook["Webhook handler — raw-body signature verification"]
    billing[("Billing inbox and subscription state")]
    reconcile["Billing reconciliation worker"]
    jobs["Code execution queue"]
    controller["Sandbox controller"]
    sandbox["Ephemeral isolated runtime — no credentials or outbound network"]
    results[("Tenant-scoped execution results")]
    user -->|"Checkout or code request"| api
    api -->|"Server-created checkout"| stripe
    stripe -->|"Signed event"| webhook
    webhook -->|"Deduplicate event ID and persist"| billing
    billing -->|"Pending events"| reconcile
    reconcile -->|"Fetch authoritative subscription"| stripe
    reconcile -->|"Update entitlements"| billing
    api -->|"Read entitlements"| billing
    api -->|"Validated job and budget"| jobs
    jobs --> controller
    controller -->|"CPU, memory and wall-clock limits"| sandbox
    sandbox -->|"Bounded output"| controller
    controller --> results
    api -->|"Authorized result retrieval"| results
```

A checkout redirect never grants paid access. Acknowledge webhooks only after durable acceptance; process retries idempotently and reconcile out-of-order events against authoritative provider state. Periodically reconcile subscriptions and handle cancellation, refunds, disputes, and grace periods. Select a platform-appropriate mobile billing design before a store release.

The remote judge is optional future work. Use a dedicated sandbox worker pool or managed execution service with syscall restrictions, read-only base images, per-job isolation, output limits, and cleanup on timeout. No user code runs inside API or interview-worker processes. The checked-in coding lab executes JavaScript in a browser iframe and does not provide this infrastructure.

## 6. Proposed release and recovery pipeline

```mermaid
flowchart LR
    change["Pull request"]
    checks["Tests, bundle builds, secret and dependency scans"]
    review["Review and merge protection"]
    build["Build immutable images and web assets"]
    registry["Registry — signed artifacts and SBOM"]
    staging["Staging — integration and tenant isolation checks"]
    gate["Release approval and migration preflight"]
    migrate["Backward-compatible database migrations"]
    canary["Canary deployment"]
    health{"SLO and health checks pass?"}
    production["Promote and monitor"]
    rollback["Roll back application artifact"]
    restore["Scheduled backup restore drills"]
    change --> checks --> review --> build --> registry --> staging --> gate
    gate --> migrate --> canary --> health
    health -->|"Yes"| production
    health -->|"No"| rollback
    production -.-> restore
```

Use short-lived CI workload identity, separate staging and production accounts or projects, least-privilege deployment roles, and infrastructure as code. Do not put long-lived cloud credentials in repository files. Expand-and-contract schema changes must remain compatible with the previous application version; application rollback does not automatically reverse a destructive database migration.

The existing [CI workflow](../../.github/workflows/ci.yml) runs backend tests, the web build, and mobile dependency/configuration/bundle checks. Registry signing, security release gates, staging, canary rollout, and restore drills are proposed. Known mobile dependency findings remain documented in [mobile security notes](../../mobile/SECURITY.md); these diagrams do not resolve them or certify production readiness.

## Implementation sequence

1. Establish identity, tenant migration, PostgreSQL isolation tests, rate limits, and secrets management.
2. Add transactional jobs/outbox, durable LangGraph checkpoints, quota accounting, and billing reconciliation.
3. Provision multi-zone infrastructure, redacted telemetry, backups, and tested deployment/rollback procedures.
4. Add streaming voice or remote code execution only after their separate security and cost controls are validated.

Mermaid sources are embedded here so GitHub renders them and changes can be reviewed alongside code. Keep the current-state diagram grounded in code; change target-state diagrams as architectural decisions are accepted.
