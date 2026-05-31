# Tanellorn Mini App Plan

## Direction

`Танелорн` is the gradual Mini App interface for Aventura. The Telegram bot remains the entry point, while the city map becomes the place where players inspect available activity.

The shared center of the game remains unchanged:

- `players`, `characters`, and `change_log` continue to own character state;
- manual PvE missions remain the live game mode;
- the existing `turn.yaml -> export.json -> result.json` flow remains authoritative;
- Telegram commands remain the operational fallback.

## Implemented Stages

Stage 1 added the guarded map skeleton:

- feature flags in env/config;
- an admin-only development gate by default;
- `legacy`, `both`, and `miniapp` mission UI modes;
- a separate FastAPI web entrypoint;
- a Tanellorn map page with mission markers;
- `GET /api/tanellorn/state`, which maps currently open missions to temporary fixed map positions;
- mission detail cards.

No map coordinates are stored in the database yet. The API assigns stable placeholder positions at read time, so this phase is reversible and does not change the mission schema.

Stage 2 exposes existing bot functionality through the admin-preview map:

- choose or change a mission, submit or replace the action text;
- inspect the hero sheet, latest mission result, and guild roster;
- inspect NPC windows on the map with the current hero's personal reputation toward that NPC;
- use the shop, sell allowed assets, buy back a listed asset, and pay for tavern rest;
- create the existing once-per-turn craft request in the Alchemists' workshop;
- use an Auction landmark as a view of existing `player_sale` shop listings.

All operations call the same game-service functions as the Telegram UI. No new reward rules, mission resolution rules, turn import/export format, auction bidding, or portrait-storage schema has been added.

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

`both` preserves the old mission cards while exposing the map button only to admins. In admin-only mode, the API validates Telegram Mini App `initData` when the client provides it. For Telegram clients that open a persistent keyboard Web App without usable `initData`, the bot adds a signed admin access token to the button URL; the API validates its signature against the bot token and still rejects users outside `ADMIN_TELEGRAM_IDS`. Because the map now supports gameplay writes, that fallback link expires after 24 hours and must not be shared.

## Runtime

Locally, the bot and the web preview may be launched independently:

```bash
python -m aventura_bot.bot
python -m aventura_bot.web
```

On Railway, the current preview uses one existing service with its one SQLite volume:

```bash
python -m aventura_bot.runtime
```

The combined runtime keeps long polling active and exposes the web page from the same container. This is necessary while game state is stored in a volume-backed SQLite file; a separate Railway service would not own the live bot volume. The Mini App now performs guarded gameplay writes through existing service functions, while Telegram commands remain fully supported.

## Future Stages, Not Implemented

Later stages may add:

- incident markers;
- Gemini API resolution of simple incidents;
- assigning a hero, companion, or familiar from the map;
- NPC presence on the map;
- Power as a coefficient for used assets.
- optional hero portrait storage/upload;
- richer market behavior such as bids, only if deliberately designed later.

Those ideas are intentionally outside the current preview. The implemented stages introduce no incident processing, NPC rewards, reputation-driven Mini App actions, Power, companion locks, AI resolver, browser quest worker, or new sale permissions.
