# Crash Course 2 leaderboard server on Cloudflare Workers (free plan)

Stores the course times the game uploads and serves them back in place of Xbox Live, so everyone
pointed at the same Worker sees each other's times. It's the Trials HD port's Worker adapted for
Crash Course 2 (same API, same setup). Nothing runs at home; the free plan (100,000 requests a day)
is far more than a group of players uses.

**Use a new Worker and database, not your Trials HD one.** Both games number their leaderboards
from 0, so sharing a database would mix them.

Everything below is done in the Cloudflare dashboard; no tools to install.

## 1. Create the database

**Storage & Databases → D1 SQL Database → Create** → name it `cc2` → Create.

## 2. Create the Worker

1. **Compute (Workers) → Workers & Pages → Create → Start with Hello World** → name it `cc2` →
   **Deploy**.
2. **Edit code**, delete everything in `worker.js`, paste in the contents of [worker.js](worker.js),
   then **Deploy**.
3. In the Worker: **Settings → Bindings → + Add binding → D1 database → Add Binding**, pick the
   `cc2` database and save. The variable name doesn't matter; the Worker uses whichever D1
   database is bound.
4. Optional, under **Settings → Variables and Secrets**:
   - `ADMIN_KEY` (type **Secret**): a long random password for the admin endpoints.
   - `EVERYONE_FRIENDS` = `0` if you want hand-picked friends instead of everyone being friends.
5. Open `https://cc2.<your-account>.workers.dev/health`. It should say
   `{"ok":true,"database":true}` (`"database":false` means the binding is missing).
   Tables are created automatically on first use.

Optional: **Domains → Add → Custom domain** to use your own address (e.g. `cc2.yourdomain`).

## 3. In the game

Press **F1** → *Player & Online*: type a name and a password (8+ characters, made up), tick
**Play online**, put the Worker's address in **Server**, press **Test connection** ("Connected as
…"), then **Save** and restart the game. Or in `crashcourse2.toml`:

```toml
cc2_player_name = "Trev"
cc2_server_url = "https://cc2.<your-account>.workers.dev"
cc2_player_key = "a-password-only-you-know"
```

The first time a name connects, the server remembers its password; after that only that password
can post times for it. An admin can free a name with `POST /api/v1/admin/reset_key
{"name": "..."}` (header `X-Admin-Key`).

## How Crash Course 2's leaderboards map

From the XLAST inside the game (`5841124F.original.gameconfig`), 171 views, each ranked by
property `0x20000008` (`LB_RATING`), aggregation Max, so **higher is better**:

| Views | Leaderboard |
|---|---|
| 0-5 / 6-11 | Jungle courses 1-6, all-time / weekly |
| 12-17 / 18-23 | Desert |
| 24-29 / 30-35 | Island |
| 36-41 / 42-47 | Arctic |
| 48-53 / 54-59 | Hong Kong |
| 60 | Gold medals (all-time) |
| 61-70 | Bonus courses (all-time, weekly per world) |
| 71-170 | reserved, unused |

Weekly views (`resetType="Weekly"`) start fresh every Monday 00:00 UTC. `VIEWS_JSON` can override
a view's ranking (`{"60":{"order":"asc"}}`), but shouldn't be needed.

## API (for reference)

All requests carry `X-Player-Name` and `X-Player-Key` (plus `CF-Access-Client-Id` /
`CF-Access-Client-Secret` when set in the game, for Cloudflare Access).

- `GET /api/v1/hello` → `{"xuid": "..."}` (registers the name on first use)
- `POST /api/v1/stats` `{"views":[{"view":0,"props":[{"id":536870920,"type":2,"value":-61234}]}]}`
- `GET /api/v1/leaderboard?view=N&start=1&count=10` or `&around=<xuid>`; `&fmt=text` for the game
- `POST /api/v1/read` `{"view":N,"xuids":["..."]}`
- `GET|POST /api/v1/friends`
- Errors: `{"error": "..."}` with a 4xx status (shown in the F1 menu)

## Command line instead of the dashboard

With [wrangler](https://developers.cloudflare.com/workers/wrangler/): `npx wrangler d1 create cc2`,
put its id in `wrangler.toml`, then `npx wrangler deploy`.
