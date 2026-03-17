# Attuned — Current Status

**Last updated:** Mar 17, 2026
**Current phase:** Pre-build. All specification gaps resolved. Documents updated with audit findings. Ready for Day 1.
**Next action:** Register WHOOP + Spotify developer apps, then begin Day 1.

---

## What Exists

- Project structure created (all directories)
- docs/PRD.md — v2.1, rephased for extended streaming history (arrived Mar 16: 33,427 records, 5,701 unique tracks, 679 with 5+ meaningful listens)
- docs/RESEARCH.md — full research analysis with audit updates: sigmoid scoring (parasympathetic/sympathetic), SWC-based HRV thresholds, evidence-informed characterization, Karageorghis reference, acousticness/danceability caveats, Weightless annotation
- docs/SYSTEM_LOGIC.md — comprehensive system design with audit updates: sigmoid formulas, SWC thresholds, property match score formula, engagement score formula, iso starting profiles, terminal fallback, confidence multiplier, evidence-informed note, softened causal language
- docs/PRD.md — v2.2 with audit updates: schema fixes (date columns, ln_rmssd, FKs, indexes), engagement/property match formulas, starting profiles, classification pool boundary, terminal fallback, confidence multiplier, cycle-to-date mapping, SWC thresholds, multi-user note
- CLAUDE.md — engineering guidelines, updated for 6 states + engagement scoring
- tasks/todo.md + tasks/lessons.md — tracking
- .env.example, .gitignore, requirements.txt — initial versions
- Spotify extended streaming history JSON files (arrived Mar 16)

## Blockers

- WHOOP developer app: needs to be registered at developer.whoop.com
- Spotify developer app: needs to be registered at developer.spotify.com

## API Keys Status

- WHOOP: not yet (need to register app)
- Spotify: not yet (need to register app)
- OpenAI: has $5 credits (for song classification, Day 4 — 679 songs ~$0.68)
