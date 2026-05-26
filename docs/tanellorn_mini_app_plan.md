# Tanellorn Mini App Plan

## Direction

`Танелорн` is the gradual Mini App interface for Aventura. The Telegram bot remains the entry point, while the city map becomes the place where players inspect available activity.

The shared center of the game remains unchanged:

- `players`, `characters`, and `change_log` continue to own character state;
- manual PvE missions remain the live game mode;
- the existing `turn.yaml -> export.json -> result.json` flow remains authoritative;
- Telegram commands remain the operational fallback.

## Stage 1: Current Scope

This stage adds only an alternative, read-only view of current manual PvE missions:

- feature flags in env/config;
- an admin-only development gate by default;
- `legacy`, `both`, and `miniapp` mission UI modes;
- a separate FastAPI web entrypoint;
- a Tanellorn map page with mission markers;
- `GET /api/tanellorn/state`, which maps currently open missions to temporary fixed map positions;
- mission detail cards that direct the player back to `/join <id>` in the bot.

No map coordinates are stored in the database yet. The API assigns stable placeholder positions at read time, so this phase is reversible and does not change the mission schema.

## Safe Rollout

Default flags keep the current bot behavior:

```text
TANELLORN_MINI_APP_ENABLED=false
TANELLORN_MINI_APP_ADMIN_ONLY=true
TANELLORN_MINI_APP_URL=
MISSION_UI_MODE=legacy
```

For an admin preview:

```text
TANELLORN_MINI_APP_ENABLED=true
TANELLORN_MINI_APP_ADMIN_ONLY=true
TANELLORN_MINI_APP_URL=https://<railway-public-domain>/tanellorn
MISSION_UI_MODE=both
```

`both` preserves the old mission cards while exposing the map button only to admins. In admin-only mode, the API validates Telegram Mini App `initData` when the client provides it. For Telegram clients that open a persistent keyboard Web App without usable `initData`, the bot adds a signed read-only admin access token to the button URL; the API validates its signature against the bot token and still rejects users outside `ADMIN_TELEGRAM_IDS`. This admin button URL is a development access token and must not be shared.

## Runtime

Locally, the bot and the web preview may be launched independently:

```bash
python -m aventura_bot.bot
python -m aventura_bot.web
```

On Railway, stage 1 uses one existing service with its one SQLite volume:

```bash
python -m aventura_bot.runtime
```

The combined runtime keeps long polling active and exposes the web page from the same container. This is necessary while game state is stored in a volume-backed SQLite file; a separate Railway service would not own the live bot volume. The web route reads the database for display only; schema initialization and all gameplay writes remain owned by the bot worker. Joining a mission and sending an action still happens through Telegram commands.

## Future Stages, Not Implemented

Later stages may add:

- incident markers;
- Gemini API resolution of simple incidents;
- assigning a hero, companion, or familiar from the map;
- NPC presence on the map;
- reputation tags and titles;
- Power as a coefficient for used assets.

Those ideas are intentionally outside stage 1. This stage introduces no incident processing, NPC rewards, reputation, Power, companion locks, AI resolver, or browser quest worker.
