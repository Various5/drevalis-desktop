# Content Quality — Phase 1 Audit

Read-only verification of the 5 unconfirmed items before Phase 2 implementation.

---

## 1. `LLMService.generate_script` — signature + interpolation

**File**: `src/drevalis/services/llm/_monolith.py:541-653`.

### Signature

```python
async def generate_script(
    self,
    config: LLMConfig,
    prompt_template: PromptTemplate,
    topic: str,
    character_description: str,
    target_duration: int,
    language_code: str | None = None,
) -> EpisodeScript:
```

### How the user prompt is rendered

Manual `str.replace()` (NOT `.format()`) — chosen so JSON curly braces in the template don't trigger `KeyError`:

```python
# 1. {character} substitution — special-cased
if character_description:
    rendered_template = prompt_template.user_prompt_template.replace(
        "{character}", character_description
    )
else:
    # When character is empty, lines mentioning {character} are STRIPPED entirely
    rendered_template = "\n".join(
        line for line in prompt_template.user_prompt_template.split("\n")
        if "{character}" not in line
    )

# 2. {topic} and {duration} substitution
user_prompt = rendered_template.replace("{topic}", topic).replace(
    "{duration}", str(target_duration)
)
```

### Variables interpolated into the template

| Placeholder | Source |
|---|---|
| `{topic}` | `topic` arg (from `episode.topic or episode.title`) |
| `{character}` | `character_description` arg (from `series.character_description`); empty → entire line dropped |
| `{duration}` | `str(target_duration)` (from `series.target_duration_seconds`) |

There is **no** `{language}` placeholder. Language steering is done by **appending** a hard-coded English-language paragraph to the rendered prompt at line 596 when `language_code` is set and not `en*`. Same pattern for the no-character hint (line 581) and the appended `thumbnail_prompt` instruction in the **system** prompt (line 615).

### Implications for Phase 2.2

The new placeholders (`{tone_profile_block}`, `{visual_style}`, `{negative_prompt}`) need to follow the same `str.replace()` pattern, and the function signature must grow `tone_profile: dict | None`, `visual_style: str`, `negative_prompt: str` parameters. The `{character}` line-stripping behaviour should be preserved unchanged.

---

## 2. `_auto_select_prompt_template("script")` fallback

**File**: `src/drevalis/services/pipeline/_monolith.py:2257-2270`.

```python
async def _auto_select_prompt_template(self, template_type: str) -> Any:
    repo = PromptTemplateRepository(self.db)
    templates = await repo.get_by_type(template_type)
    if templates:
        return templates[0]
    return None
```

`PromptTemplateRepository.get_by_type` (`src/drevalis/repositories/prompt_template.py:19`) executes:

```python
select(PromptTemplate)
    .where(PromptTemplate.template_type == template_type)
    .order_by(PromptTemplate.name)
```

Order is **alphabetical by `name` ascending**. With the two existing script-type rows (`Default Script` and `YouTube Shorts Script Generator`), the fallback resolves to **`Default Script`** (D < Y). After Phase 2.3 deletes the `Default Script` row, the fallback will resolve to `YouTube Shorts Script Generator` — the new prompt.

---

## 3. Shorts script JSON — `description` / `hashtags` populated?

### Schema state

`src/drevalis/schemas/script.py:126-131` — `EpisodeScript` already declares the three fields:

```python
description: str = Field(default="", ...)
hashtags: list[str] = Field(default_factory=list, ...)
thumbnail_prompt: str = Field(default="", ...)
```

All three default to empty when the LLM doesn't return them. `EpisodeScript.model_validate()` does NOT reject missing values — it silently accepts the defaults.

### Shorts path — `_step_script` else-branch (`pipeline/_monolith.py:577-620`)

The shorts path calls `LLMService.generate_script` once and persists the result via `script.model_dump()`. Whether `description` / `hashtags` are populated depends entirely on whether the prompt template's JSON schema requests them.

The current `Default Script` / `YouTube Shorts Script Generator` template (per the user's pre-supplied finding) does NOT include `description` or `hashtags` in the `OUTPUT JSON` schema it shows the LLM. Only `thumbnail_prompt` gets a nudge — and only via the runtime system-prompt augmentation at line 615:

```python
effective_system = prompt_template.system_prompt
if "thumbnail_prompt" not in effective_system:
    effective_system += (
        '\n\nAlso include a top-level "thumbnail_prompt" field in your JSON: ...'
    )
```

**Net effect**: shorts ship `description=""`, `hashtags=[]` in `episode.script` JSONB by default. `thumbnail_prompt` is sometimes populated (depending on whether the model honours the appended instruction). I could not query the dev DB directly to count actuals because Docker is not currently running on this host — but the prompt template + schema together guarantee the empty defaults.

### Long-form path — populated

`services/longform_script.py:166-176` builds the script dict from the outline, which the outline phase explicitly asks the LLM to produce (`_generate_outline` system prompt at line 202-216 includes `"description"` and `"hashtags"`). So long-form scripts DO carry these fields. The longform service does NOT pass `thumbnail_prompt` (line 167-176 omits it — the outline prompt also omits it) — so longform thumbnails miss it.

### prompt_templates table state

I could not run `SELECT name, template_type FROM prompt_templates` directly (Docker not running). I confirmed:
- The `001_initial_schema.py` migration creates the table empty — no inline seed data.
- No seed code lives in the codebase (`PromptTemplate(...)` constructor is referenced only in tests/models — not in any startup hook or onboarding bootstrap).
- No code path in `src/drevalis/services/series.py`, `services/pipeline/_monolith.py`, `services/llm/_monolith.py`, or `core/license/gate.py` writes default rows.

The 3 rows must therefore have been seeded manually via `POST /api/v1/prompt-templates/`. **The user's pre-supplied finding (3 rows, `Default Script` ≡ `YouTube Shorts Script Generator`, plus `Scene Visual Enhancer`) is taken as authoritative.** The Phase 2.3 down-migration must be defensive: a `DELETE WHERE name = 'Default Script'` and `UPDATE WHERE name = 'YouTube Shorts Script Generator'` won't break installs that have been customised, but the migration must store the previous content of the row as a constant so down-migration restores prior state.

### Implications for Phase 2.3

- The new shorts prompt explicitly lists `description`, `hashtags`, `thumbnail_prompt` in the OUTPUT JSON. The runtime system-prompt augmentation at line 615 will become a no-op for the new template (the `"thumbnail_prompt"` substring will already match) — leave it in place anyway as a safety net for users who keep custom templates.
- Shorts will start populating `description`/`hashtags` via the same code path that currently produces empty values — no schema change needed.

---

## 4. YouTube upload description — source chain

**File**: `src/drevalis/api/routes/youtube/_monolith.py:418-449` (resolution) → `services/youtube_admin.py:342-405` (SEO generation) → `workers/jobs/seo.py:69-97` (background SEO).

### Resolution order (first non-empty wins)

```python
upload_title       = payload.title       or seo_data.get("title", episode.title)
upload_description = payload.description or seo_data.get("description", "")
upload_tags        = payload.tags        if payload.tags else seo_data.get("tags", [])
```

Then:

1. **Hashtag append**: if `seo_data["hashtags"]` exists, the joined `#tag1 #tag2 …` string is appended to `upload_description` (with a blank line separator) — but only if not already present.
2. **Script fallback** (lines 428-449) — runs ONLY when `upload_description == ""` after step 1:
   - `parts = [script.title, script.description, "#tag #tag" from script.hashtags]`
   - joined with `\n\n`
3. **Tags fallback** (lines 446-449) — runs only when `upload_tags` is empty:
   - `[h.lstrip("#") for h in script.hashtags]`

### `seo_data` source

`YouTubeAdminService.get_or_generate_seo()`:

1. If `episode.metadata_["seo"]` is a dict → return it (cache hit).
2. Otherwise generate inline via a hard-coded SEO prompt against the **first available** `LLMConfig` (no series-level config respected here):
   ```text
   You are a YouTube SEO expert. Generate optimized metadata. Output ONLY valid JSON: {"title": ..., "description": ..., "hashtags": [...], "tags": [...]}
   ```
   Result cached back into `episode.metadata_["seo"]`.

There is also a **separate** background arq job `generate_seo_async` (`workers/jobs/seo.py`) that does roughly the same thing offline — same prompt, slightly different schema (adds `hook`, `virality_score`). Both write to `episode.metadata_["seo"]`. Either can populate the cache before the upload runs.

### What this means for shorts today

Shorts get a non-empty upload description via the **SEO subsystem** (separate LLM call, separate prompt — not the script step). The script's empty `description` is masked. Once Phase 2.3 lands, the script will produce its own `description`. Resolution still favours `payload.description` → SEO → script — so the new script field will only surface when SEO has not been pre-generated AND the user did not pass a description in the upload request. That is acceptable as a fallback layer, but not as a primary "the script controls the description" claim — the SEO prompt would need to be retired or rewired for that to be true.

**Note for follow-up (out of Phase 2 scope, flag for later):** the SEO prompt in `youtube_admin.py:380` and `workers/jobs/seo.py:69` is also subject to the same banned-vocabulary issue and could overwrite a clean script description with cargo-cult prose. Worth a post-2.9 ticket.

### Implications for Phase 2.3

The new shorts prompt's `description` field rules ("First 125 chars = the hook again as a written cold-open. Total ≤300 chars. No 'In this video...'.") will only flow through to YouTube when SEO data is absent. To make the script-side rules actually win, Phase 2 should consider either (a) re-ordering the resolution chain, or (b) updating the SEO prompts to mirror the script rules. **Out of scope for this audit; flagging for the implementation plan.**

---

## 5. Series fields used in script generation — confirmed

`_step_script` (`pipeline/_monolith.py:469-620`) reads:

| Field | Used in | Notes |
|---|---|---|
| `series.llm_config` | shorts + longform | FK; falls back to `_auto_select_llm_config()` |
| `series.script_prompt_template` | shorts + longform (refinement) | FK; falls back to `_auto_select_prompt_template("script")` |
| `series.visual_prompt_template` | shorts + longform | FK; gates `_refine_visual_prompts` call |
| `series.character_description` | shorts + longform | passed to LLM + visual refiner |
| `series.content_format` | dispatch | shorts / longform / music_video |
| `series.description` | longform only | passed as `series_description` to `LongFormScriptService.generate()` |
| `series.visual_style` | shorts (refiner) + longform | |
| `series.negative_prompt` | longform only | passed to `LongFormScriptService.generate()` |
| `series.target_duration_seconds` | shorts only | |
| `series.target_duration_minutes` | longform only | via `getattr(..., None) or 30` |
| `series.scenes_per_chapter` | longform only | via `getattr(..., 8)` |
| `series.visual_consistency_prompt` | longform only | passed to `LongFormScriptService.__init__` |
| `series.default_language` | shorts only | passed as `language_code`; longform hard-codes `"en-US"` |

### Fields the audit task list missed (worth knowing about)

- `target_duration_minutes`, `scenes_per_chapter`, `visual_consistency_prompt` — longform-only, used during script gen.
- **`series.default_language` is silently ignored on the longform path** (`longform_script.py:173` hard-codes `"language": "en-US"`). Phase 2.6 can fix that by threading the series' language through.

### Implications for Phase 2.1 / 2.2

- Adding `series.tone_profile` (JSONB) only requires touching `_step_script` to pass it into both the shorts call (`generate_script`) and the longform call (`LongFormScriptService(...)`).
- The longform path needs `tone_profile` plumbed into the constructor (mirrors `visual_consistency_prompt` / `character_description`).
- The shorts path needs the `LLMService.generate_script` signature change called out in §1.

---

## Confirmation of the visual-prompt placeholder bug (Phase 2.4)

`pipeline/_monolith.py:663-671` — confirmed exactly as the task description stated:

```python
async def _refine_one(scene_data: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    raw_vp: str = scene_data.get("visual_prompt", "")
    if not raw_vp:
        return scene_data, None
    refine_user = user_template.replace("{prompt}", raw_vp)   # ← bug: template uses {scene_prompt}
    if visual_style:
        refine_user += f"\nVisual style: {visual_style}"
    if character_description:
        refine_user += f"\nCharacter: {character_description}"
```

The user-supplied finding (DB template uses `{scene_prompt}` while the code substitutes `{prompt}`) means **the placeholder is sent to the LLM verbatim**, with the actual prompt body appended via the two `+=` lines. The fallback default at line 660 (`"Refine this prompt: {prompt}"`) does match the substituted name — so series with no template attached behave correctly; series WITH the seeded `Scene Visual Enhancer` template do not.

Hardcoded fallback system prompt at lines 651-657 confirmed to be 2 sentences (matches the task description for Phase 2.5).

---

## Other gotchas surfaced during the audit (not blockers, but worth flagging)

1. **`LongFormScriptService` is documented as 3-phase but is actually 2-phase.** `services/longform_script.py:1-13` docstring promises outline + chapters + quality. The `generate()` method runs phases 1 and 2 only — there is no quality phase. Phase 2.6 is the right place to actually add it. CLAUDE.md `Long-Form Video` section makes the same false claim and needs updating in Phase 2 docs.
2. **`series.default_language` ignored in longform** — see §5. `longform_script.py:173` hard-codes `"en-US"`. Phase 2.6 should thread the series language through both `_generate_outline` (so its description text honours it) and the final `script["language"]` field.
3. **`get_or_generate_seo` uses `LLMConfigRepository(self._db).get_all(limit=1)`** — i.e. ignores the series-level LLM config. Quietly out of scope for content-quality work, but worth a note: when Phase 2.3's prompts start producing good descriptions, the SEO subsystem will still mint replacement copy on a different model. Either re-order the resolution chain in the upload route or wire SEO to use the same provider.
4. **The runtime system-prompt augmentation at `llm/_monolith.py:615`** appends a thumbnail_prompt instruction whenever the substring `thumbnail_prompt` is missing. New Phase 2.3 prompts include the field by name in the OUTPUT JSON — so the augmentation becomes a no-op for the new templates. Safe to leave for compatibility with custom templates.

---

## Status

Phase 1 audit complete. Stopping for sign-off before:

- Phase 2.1 — `tone_profile` field shape confirmation
- Phase 2.6 / 2.7 — regex set + specificity thresholds for `check_script_content`

Per the brief, both of those are explicit "ask me first" hard stops.
