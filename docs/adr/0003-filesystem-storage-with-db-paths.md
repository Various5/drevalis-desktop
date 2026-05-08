# ADR-0003: Local Filesystem Storage with Database Path References over Cloud Storage and Database BLOBs

**Status:** Accepted
**Date:** 2026-03-23
**Deciders:** Project Lead

## Context

A single episode generation produces multiple binary artifacts:
- 1 voiceover WAV file (typically 1--5 MB).
- 5--15 scene PNG images (each 0.5--3 MB, depending on ComfyUI output resolution).
- 1 assembled MP4 video (typically 10--50 MB).
- 1 subtitle file (SRT or ASS, a few KB).

Over weeks of daily operation, storage accumulates significantly. A user generating 2 episodes per day with 10 scenes each produces roughly 1--2 GB per week of raw artifacts before any cleanup.

The storage system must:
- Organize files predictably so that cleanup, export, and debugging are straightforward.
- Allow the API to serve files efficiently (static file serving or sendfile).
- Store file references in the database for relational queries (find all scenes for episode X).
- Be configurable so users can point storage at a different drive or NAS mount.

### Options Considered

**Option A: Cloud object storage (S3 / MinIO)**

- Pros:
  - Scalable, durable, battle-tested.
  - Pre-signed URLs for direct client access without proxying through the backend.
  - MinIO provides S3-compatible API for self-hosted deployments.
- Cons:
  - Adds operational complexity: another service in Docker Compose, access key management, bucket policies.
  - Network latency for every file read/write, even on localhost with MinIO.
  - Overkill for a single-user local application. The durability and scalability guarantees of object storage solve problems this application does not have.
  - FFmpeg and Piper TTS operate on local file paths. Using S3 would require downloading files to a temp directory before processing and uploading results afterward, adding complexity and latency to every pipeline step.

**Option B: Database BLOBs (PostgreSQL large objects or BYTEA columns)**

- Pros:
  - Transactional consistency: file data and metadata are committed atomically.
  - No separate storage system to manage.
- Cons:
  - PostgreSQL performance degrades significantly with large BYTEA columns. A 50 MB video in a BYTEA column bloats WAL, makes `pg_dump` slow, and consumes shared buffers inefficiently.
  - Streaming large files from the database to an HTTP response is more complex than serving from the filesystem.
  - Database backups become enormous and slow.
  - FFmpeg and TTS tools cannot read from database BLOBs; files would need to be extracted to temp paths anyway.

**Option C: Local filesystem with configurable base path and database path references**

- Pros:
  - Simplest possible approach. Files are regular files on disk.
  - FFmpeg, Piper TTS, and ComfyUI all operate natively on filesystem paths. No download/upload ceremony.
  - FastAPI's `FileResponse` and static file mounts serve files efficiently, leveraging OS-level sendfile where available.
  - Users control storage location via a single `STORAGE_BASE_PATH` environment variable. Can point to an external drive, NAS mount, or fast NVMe.
  - Database stores only relative paths (e.g., `episodes/abc123/scenes/001.png`), keeping rows small and queries fast.
  - Cleanup is trivial: delete the episode directory.
- Cons:
  - No transactional atomicity between database writes and filesystem writes. A crash between creating the DB record and writing the file leaves an orphan reference.
  - No built-in redundancy or replication.
  - File serving must go through FastAPI or a reverse proxy; no pre-signed URL pattern.

## Decision

**Local filesystem with configurable base path.** The database stores relative paths; the application resolves them against a `STORAGE_BASE_PATH` setting managed by pydantic-settings (environment variable or `.env` file).

The directory structure follows a predictable convention:

```
$STORAGE_BASE_PATH/
  episodes/
    {episode_id}/
      voice/
        narration.wav
      scenes/
        001.png
        002.png
        ...
      captions/
        subtitles.ass
      output/
        final.mp4
  models/
    piper/
      {voice_name}.onnx
      {voice_name}.onnx.json
```

This was chosen because every tool in the pipeline (FFmpeg, Piper, ComfyUI) operates on filesystem paths. Introducing an abstraction layer (S3 API, DB BLOB extraction) would add complexity to every pipeline step without providing value to a single-user local application.

## Consequences

**Positive:**
- Zero additional infrastructure. No MinIO container, no bucket configuration, no access keys.
- Pipeline steps pass file paths directly. `ffmpeg -i /storage/episodes/abc/voice/narration.wav` works without any download step.
- Users can browse, back up, or move generated content with standard file management tools.
- The `STORAGE_BASE_PATH` setting makes it trivial to relocate storage (e.g., to a larger drive) by changing one environment variable and moving the directory.

**Negative:**
- No atomicity guarantee between database state and filesystem state. Mitigated by: (a) writing files before creating/updating DB records (file-first pattern), and (b) a periodic cleanup task that reconciles orphaned files against DB records.
- Single-machine storage has no built-in redundancy. Accepted risk for a local-first application. Users who need redundancy can point `STORAGE_BASE_PATH` at a RAID array or synced directory.

**Risks:**
- Disk space exhaustion if cleanup is neglected. Mitigated by a storage usage endpoint in the API and configurable retention policies (delete episodes older than N days).
- Path traversal vulnerabilities if episode IDs or filenames are not sanitized. Mitigated by using UUID-based episode IDs (no user-supplied path components) and validating all paths resolve within `STORAGE_BASE_PATH`.
