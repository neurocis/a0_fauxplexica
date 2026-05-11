# A0_Fauxplexica

<!-- badges: TODO -->
![status](https://img.shields.io/badge/status-scaffold-orange)
![license](https://img.shields.io/badge/license-MIT-blue)
![version](https://img.shields.io/badge/version-0.1.0-lightgrey)

A **Perplexity / Vane-style AI answering engine** delivered as a native [Agent Zero](https://github.com/agent0ai) plugin. Spawns a dedicated `fauxplexica` chat profile, orchestrates a *classify → research → compose → cite* pipeline against a BYO SearxNG meta-search backend, and renders rich citation sidebar cards in the A0 WebUI.

> **Status:** Phase 1 scaffold only. No business logic implemented yet — see `PLAN_PHASE1.md` and the per-component `TODO(<OwnerName>)` markers throughout the source tree.

## License

MIT — see [`LICENSE`](./LICENSE).

## ⚠️ BYO SearxNG Requirement

A0_Fauxplexica does **not** bundle or auto-provision a SearxNG instance. You must run your own SearxNG service and point the plugin at it via the `searxng_url` setting (per-project or per-agent).

Recommended: deploy SearxNG via the upstream Docker image (`searxng/searxng`) on your own infrastructure. No `docker-compose` template is shipped with this plugin in Phase 1.

## Features

- TODO
- Three search modes: **Speed** (1-shot), **Balanced** (parallel-3, <15s target), **Quality** (multi-hop subordinate)
- Source pickers: web / discussions / academic
- Widgets: **weather**, **calculator**, **stock**
- Rich citation sidebar cards with inline `[n]` markers
- File RAG via existing `_memory` plugin
- Public endpoints: `POST /api/fauxplexica/search`, `GET /api/fauxplexica/providers`

## Install

TODO — copy/clone into `/a0/plugins/a0_fauxplexica/`, then enable via the A0 plugins panel.

## Config

TODO — describe `searxng_url`, `default_mode`, `sources`, `widgets_enabled`, `max_sources_per_query`, `citation_style`, `model_overrides.*`.

## API

TODO — document `POST /api/fauxplexica/search`, `GET /api/fauxplexica/providers`.

## Architecture

TODO — see `PLAN_PHASE1.md` §2 (Vane → A0 mapping) and §3 (plugin layout).

## Contributing

TODO — issues and PRs welcome. Commits should include a `Co-authored-by:` footer per the A0 convention.
