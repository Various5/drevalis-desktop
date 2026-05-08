# ADR-0001: Async Job Queue --- arq over Celery

**Status:** Accepted
**Date:** 2026-03-23
**Deciders:** Project Lead

## Context

The generation pipeline contains multiple long-running operations that cannot execute within an HTTP request/response cycle. A single episode generation involves: LLM script generation (5--30 seconds depending on model), TTS synthesis per scene (2--10 seconds each), ComfyUI image generation per scene (10--60 seconds each), and FFmpeg video assembly (5--20 seconds). The total wall-clock time for one episode can reach several minutes.

The system needs a background job queue that supports:
- Enqueueing multi-step generation jobs from API endpoints.
- Reporting granular progress back to the frontend in real time.
- Retry logic for transient failures (ComfyUI connection drops, OOM during inference).
- Compatibility with the async Python ecosystem already in use.

### Options Considered

**Option A: Celery**

- Pros:
  - Industry standard for Python background task processing with over a decade of production use.
  - Rich ecosystem: Flower dashboard for monitoring, celery-beat for scheduling, extensive documentation.
  - Supports multiple broker backends (Redis, RabbitMQ, Amazon SQS).
  - Large community; most Python task-processing questions have existing answers.
- Cons:
  - Fundamentally synchronous. Workers use prefork (multiprocessing) or eventlet/gevent for concurrency, none of which are native asyncio.
  - Running async code inside Celery tasks requires `asyncio.run()` wrappers or the experimental `celery[asyncio]` support, which is not production-stable.
  - Heavy dependency footprint: pulls in kombu, billiard, vine, amqp, and their transitive dependencies.
  - Broker configuration is non-trivial. RabbitMQ adds an extra service to Docker Compose; Redis-as-broker works but is a second-class citizen in Celery's design.
  - Distributed features (multi-node routing, rate limiting per queue, chord/chain primitives) are unnecessary for a single-machine local-first application.

**Option B: arq**

- Pros:
  - Built from the ground up on asyncio. Worker functions are native `async def` coroutines.
  - Redis-based with minimal configuration: point it at a Redis URL and define worker functions.
  - Lightweight: single dependency (redis/aioredis). No broker abstraction layer.
  - Built-in job result storage and job progress reporting via `ctx['job'].update(progress=...)`.
  - Natural fit with FastAPI, asyncpg, and httpx (ComfyUI client), since all share the same event loop model.
  - Simple API: `await queue.enqueue_job('generate_episode', episode_id)` on the FastAPI side, `async def generate_episode(ctx, episode_id)` on the worker side.
- Cons:
  - Smaller community and fewer tutorials compared to Celery.
  - No built-in monitoring dashboard (no equivalent of Flower).
  - Redis is the only supported broker; no RabbitMQ or SQS option.
  - Fewer battle-tested patterns for complex workflows (chaining, fan-out/fan-in).

**Option C: Dramatiq**

- Pros:
  - Simpler than Celery with a cleaner API.
  - Supports Redis and RabbitMQ brokers.
  - Middleware architecture for cross-cutting concerns.
- Cons:
  - Also synchronous at its core; same asyncio compatibility issues as Celery.
  - Smaller ecosystem than Celery without the async advantages of arq.
  - Adds a third option without meaningfully improving on either A or B.

## Decision

**arq** is the chosen job queue.

The deciding factor is async-native compatibility. The entire backend --- FastAPI route handlers, SQLAlchemy async sessions, asyncpg connection pools, httpx calls to ComfyUI --- operates on asyncio. Introducing a synchronous task queue would create an impedance mismatch: every worker function would need `asyncio.run()` bridges, database sessions would need separate synchronous engines, and the httpx ComfyUI client would need a sync equivalent or wrapper.

arq eliminates this friction entirely. Worker functions share the same async patterns as the rest of the codebase. A single `aioredis` connection pool serves both the arq worker and any other Redis needs (caching, pub/sub for WebSocket progress).

The local-first deployment model (single Docker Compose stack on one machine) means Celery's distributed features provide no value. arq's simplicity is an asset, not a limitation, in this context.

## Consequences

**Positive:**
- Zero impedance mismatch between API code and worker code. Shared async database sessions, HTTP clients, and utilities.
- Minimal configuration. The worker is defined in a single Python module with a `WorkerSettings` class.
- Built-in progress reporting feeds directly into the WebSocket layer for real-time frontend updates.
- Smaller Docker image and faster startup due to fewer dependencies.

**Negative:**
- No off-the-shelf monitoring dashboard. Mitigated by building a custom `/api/jobs` endpoint that queries arq's Redis keys and by pushing progress events over WebSocket to the React frontend.
- Fewer community resources for troubleshooting. Mitigated by arq's small codebase (readable in an afternoon) and good official documentation.
- If the project ever needs multi-node distributed processing, arq would need to be replaced. Accepted risk: the local-first premise makes this unlikely, and the worker interface is thin enough that migration would be bounded.

**Risks:**
- arq is maintained primarily by Samuel Colvin (pydantic author). Bus-factor risk exists. Mitigated by the project's permissive MIT license and small codebase that could be forked if necessary.
