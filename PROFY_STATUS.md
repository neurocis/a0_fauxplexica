# Profy Status — A0_Fauxplexica Chat Profile

Status: **implemented coordinator-led** because the original Profy worker reported `NO_TOOLS` and the replacement worker did not remain visible in the active roster.

## Files created/updated

Project-scoped profile files:

- `/a0/usr/projects/a0-fauxplexica/.a0proj/instructions/fauxplexica.md`
- `/a0/usr/projects/a0-fauxplexica/.a0proj/agents.json`
- `/a0/usr/projects/a0-fauxplexica/.a0proj/plugins/_model_config/presets.yaml`

Plugin-distributed profile scaffold:

- `/a0/usr/plugins/a0_fauxplexica/agents/fauxplexica/agent.yaml`
- `/a0/usr/plugins/a0_fauxplexica/agents/fauxplexica/prompts/agent.system.main.specifics.md`
- `/a0/usr/plugins/a0_fauxplexica/agents/fauxplexica/plugins/_model_config/config.json`

Plugin prompt:

- `/a0/plugins/a0_fauxplexica/prompts/system_fauxplexica.md`

## Exact profile / preset contract

- Profile key: `fauxplexica`
- Profile display name: `A0_Fauxplexica`
- Agent profile: `developer`
- Primary instructions: `prompts/agent.system.main.specifics.md`
- Project model preset: `Fauxplexica Research`
- Plugin-distributed model config: `_model_config/config.json`
- Connection policy: single connection definition per chat context
- SearxNG provisioning: BYO only
- Default mode: `balanced`
- Citation style: inline bracket citations (`[1]`)
- Citation UI: rich sidebar citations expected by WebUI

## Model contract

- Chat model: `other/max` via `http://198.18.88.38/v1`
- Utility/classifier model: `other/max-utility` via `http://198.18.88.38/v1`
- Embedding model: `huggingface/sentence-transformers/all-MiniLM-L6-v2` via `http://198.18.88.35/api/v1`

## Behavior summary

A0_Fauxplexica should:

- answer directly first
- use search/file/widget context when useful
- cite factual sourced claims inline with `[n]`
- avoid fabricated citations or sources
- avoid separate references unless requested
- use Speed/Balanced/Quality modes
- keep widget output distinct from citeable web sources

## Manual/runtime note

If the running A0 UI requires explicit profile import/activation, select/create an agent named `A0_Fauxplexica` with profile key `fauxplexica`, point it at the distributed or project instructions above, and choose the `Fauxplexica Research` preset.
