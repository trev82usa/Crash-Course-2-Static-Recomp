// Crash Course 2 leaderboard server as a Cloudflare Worker with a D1 database.
//
// Adapted from the Trials HD port's Worker (same API). Point cc2_server_url (F1 menu or
// crashcourse2.toml) at this Worker. Use a separate Worker + database from Trials HD: both games
// number their leaderboards from 0.
//
// Crash Course 2's leaderboards (from the XLAST in the game's SPA): every view ranks by
// property 0x20000008 (LB_RATING), aggregation Max, so higher is better. Views 0-59 are the five
// worlds x 6 courses (all-time and weekly), 60 gold medals, 61-70 bonus courses; weekly views
// reset every Monday 00:00 UTC, like Xbox Live.
//
// Bindings / settings (Worker -> Settings -> Bindings / Variables and Secrets):
//   DB                       D1 database binding (required)
//   ADMIN_KEY                secret; enables /api/v1/admin/* with header X-Admin-Key (optional)
//   EVERYONE_FRIENDS         "1" (default) = every player is everyone's friend; "0" = hand-picked
//   VIEWS_JSON               optional ranking overrides, e.g. {"3":{"rating":536870920,"order":"asc"}}
//
// Tables are created automatically on first use.

const CC2_RATING = 0x20000008;  // LB_RATING
// Views with resetType="Weekly" in the game's XLAST.
const WEEKLY_VIEWS = new Set([6,7,8,9,10,11,18,19,20,21,22,23,30,31,32,33,34,35,42,43,44,45,46,47,54,55,56,57,58,59,62,64,66,68,70,72,74,76,78,80,82,84,86,88,90,92,94,96,98,100,102,104,106,108,110,112,114,116,118,120,122,124,126,128,130,132,134,136,138,140,142,144,146,148,150,152,154,156,158,160,162,164,166,168,170]);

// Start of the current Xbox Live week (Monday 00:00 UTC), in seconds.
function weekStart() {
  const d = new Date();
  const day = (d.getUTCDay() + 6) % 7;  // Monday = 0
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day) / 1000;
}
// SQL condition that hides last week's entries on weekly views.
const current = (view) =>
  WEEKLY_VIEWS.has(view) ? ` AND updated >= ${weekStart()}` : "";
const NAME_RE = /^[A-Za-z0-9 _\-]{1,15}$/;
const MAX_BODY = 64 * 1024;

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS players (
     xuid INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE NOT NULL,
     key_hash TEXT NOT NULL, created REAL NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS entries (
     view INTEGER NOT NULL, xuid INTEGER NOT NULL, rating INTEGER NOT NULL,
     props TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY (view, xuid))`,
  `CREATE TABLE IF NOT EXISTS submissions (
     id INTEGER PRIMARY KEY AUTOINCREMENT, view INTEGER NOT NULL, xuid INTEGER NOT NULL,
     props TEXT NOT NULL, received REAL NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS friends (
     xuid INTEGER NOT NULL, friend INTEGER NOT NULL, PRIMARY KEY (xuid, friend))`,
  `CREATE INDEX IF NOT EXISTS entries_rank ON entries (view, rating)`,
];

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

let schemaReady = false;
async function ensureSchema(db) {
  if (schemaReady) return;
  await db.batch(SCHEMA.map((s) => db.prepare(s)));
  schemaReady = true;
}

// Stable fake XUID for a player name (must match the game client). The result is below 2^52,
// so it is exact as a JavaScript number.
function xuidFor(name) {
  let h = 0xcbf29ce484222325n;
  for (const b of new TextEncoder().encode(name.toLowerCase())) {
    h ^= BigInt(b);
    h = (h * 0x100000001b3n) & 0xffffffffffffffffn;
  }
  return Number(0x0009000000000000n | (h & 0x0000ffffffffffffn));
}

const hex16 = (x) => x.toString(16).toUpperCase().padStart(16, "0");
const parseHex = (s) => {
  if (!/^[0-9a-fA-F]{1,16}$/.test(s)) throw new ApiError(400, "bad request: bad xuid");
  return Number(BigInt("0x" + s));
};

async function hashKey(key) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("cc2:" + key));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Stat values can be 64-bit integers, which JSON.parse would round. Quote every "value" number
// before parsing so values stay exact strings.
function parseLossless(text) {
  return JSON.parse(text.replace(/("value"\s*:\s*)(-?[0-9][0-9eE+.\-]*)/g, '$1"$2"'));
}

function viewsConfig(env) {
  try {
    return env.VIEWS_JSON ? JSON.parse(env.VIEWS_JSON) : {};
  } catch {
    return {};
  }
}

function everyoneFriends(env) {
  const v = String(env.EVERYONE_FRIENDS ?? "1").trim().toLowerCase();
  return !["0", "false", "no", "off"].includes(v);
}

async function readBody(req) {
  const text = await req.text();
  if (text.length > MAX_BODY) throw new ApiError(413, "request too large");
  try {
    return text ? parseLossless(text) : {};
  } catch {
    throw new ApiError(400, "invalid JSON");
  }
}

// -- players ---------------------------------------------------------------------------------
async function authenticate(db, req) {
  const name = req.headers.get("X-Player-Name") || "";
  const key = req.headers.get("X-Player-Key") || "";
  if (!NAME_RE.test(name))
    throw new ApiError(400, "player name must be 1-15 letters, digits, spaces, _ or -");
  if (key.length < 8) throw new ApiError(400, "player key must be at least 8 characters");
  const xuid = xuidFor(name);
  const h = await hashKey(key);
  const row = await db.prepare("SELECT key_hash FROM players WHERE xuid=?").bind(xuid).first();
  if (!row) {
    await db
      .prepare("INSERT OR IGNORE INTO players VALUES (?,?,?,?)")
      .bind(xuid, name, h, Date.now() / 1000)
      .run();
    console.log(`registered new player ${name} (xuid ${hex16(xuid)})`);
    return xuid;
  }
  if (row.key_hash !== h) throw new ApiError(403, "wrong key for this player name");
  return xuid;
}

async function names(db, xuids) {
  if (!xuids.length) return new Map();
  const q = xuids.map(() => "?").join(",");
  const { results } = await db
    .prepare(`SELECT xuid, name FROM players WHERE xuid IN (${q})`)
    .bind(...xuids)
    .all();
  return new Map(results.map((r) => [r.xuid, r.name]));
}

// -- writing ---------------------------------------------------------------------------------
async function submit(db, env, xuid, views) {
  const config = viewsConfig(env);
  const now = Date.now() / 1000;
  const writes = [];
  let written = 0;
  for (const v of views || []) {
    const view = parseInt(v.view, 10);
    if (!Number.isFinite(view)) continue;
    const props = new Map();
    for (const p of v.props || []) props.set(parseInt(p.id, 10), p);
    if (!props.size) continue;
    writes.push(
      db
        .prepare("INSERT INTO submissions (view,xuid,props,received) VALUES (?,?,?,?)")
        .bind(view, xuid, JSON.stringify(v), now),
    );
    const cfg = config[String(view)] || {};
    const defaultId = props.has(CC2_RATING) ? CC2_RATING : props.keys().next().value;
    const ratingId = parseInt(cfg.rating ?? defaultId, 10);
    const desc = (cfg.order ?? "desc") === "desc";
    if (!props.has(ratingId)) {
      console.log(`view ${view}: rating property ${ratingId} missing`);
      continue;
    }
    const rating = BigInt(String(props.get(ratingId).value).split(".")[0]);
    const old = await db
      .prepare("SELECT rating, props, updated FROM entries WHERE view=? AND xuid=?")
      .bind(view, xuid)
      .first();
    // A weekly view's entry from an earlier week doesn't count: this week starts fresh.
    const stale = old !== null && WEEKLY_VIEWS.has(view) && old.updated < weekStart();
    const oldRating = old && !stale ? BigInt(old.rating) : null;
    const better = oldRating === null || (desc ? rating > oldRating : rating < oldRating);
    if (better) {
      const merged = old && !stale ? parseLossless(old.props) : {};
      for (const [id, p] of props) merged[String(id)] = p;
      writes.push(
        db
          .prepare("INSERT OR REPLACE INTO entries VALUES (?,?,?,?,?)")
          .bind(view, xuid, Number(rating), JSON.stringify(merged), now),
      );
      written++;
    }
    if (!(String(view) in config))
      console.log(`view ${view}: rating ${rating} (${desc ? "desc" : "asc"}), ${props.size} props`);
  }
  if (writes.length) {
    // Keep only the newest 2000 raw submissions (a debugging log) so the database stays small.
    writes.push(
      db.prepare(
        "DELETE FROM submissions WHERE id <= (SELECT MAX(id) - 2000 FROM submissions)",
      ),
    );
    await db.batch(writes);
  }
  return written;
}

// -- reading ---------------------------------------------------------------------------------
function ranked(env, view) {
  const order = (viewsConfig(env)[String(view)] || {}).order ?? "desc";
  const o = order === "desc" ? "DESC" : "ASC";
  return (
    `SELECT xuid, rating, props, RANK() OVER (ORDER BY rating ${o}) AS rank ` +
    `FROM entries WHERE view=${parseInt(view, 10)}${current(parseInt(view, 10))}`
  );
}

async function rowsOut(db, rows) {
  const n = await names(db, rows.map((r) => r.xuid));
  return rows.map((r) => ({
    xuid: hex16(r.xuid),
    name: n.get(r.xuid) ?? "?",
    rank: r.rank,
    rating: r.rating,
    props: parseLossless(r.props),
  }));
}

async function total(db, view) {
  const r = await db
    .prepare(`SELECT COUNT(*) AS n FROM entries WHERE view=?${current(view)}`)
    .bind(view)
    .first();
  return r ? r.n : 0;
}

async function byRank(db, env, view, start, count) {
  const { results } = await db
    .prepare(`SELECT * FROM (${ranked(env, view)}) WHERE rank >= ? ORDER BY rank LIMIT ?`)
    .bind(Math.max(start, 1), count)
    .all();
  return rowsOut(db, results);
}

async function around(db, env, view, xuid, count) {
  const me = await db
    .prepare(`SELECT rank FROM (${ranked(env, view)}) WHERE xuid=?`)
    .bind(xuid)
    .first();
  if (!me) return byRank(db, env, view, 1, count);
  return byRank(db, env, view, Math.max(1, me.rank - Math.floor(count / 2)), count);
}

async function byXuids(db, env, view, xuids) {
  if (!xuids.length) return [];
  const q = xuids.map(() => "?").join(",");
  const { results } = await db
    .prepare(`SELECT * FROM (${ranked(env, view)}) WHERE xuid IN (${q}) ORDER BY rank`)
    .bind(...xuids)
    .all();
  return rowsOut(db, results);
}

// -- friends ---------------------------------------------------------------------------------
async function friends(db, env, xuid) {
  const stmt = everyoneFriends(env)
    ? db
        .prepare("SELECT xuid AS friend FROM players WHERE xuid<>? ORDER BY name COLLATE NOCASE")
        .bind(xuid)
    : db.prepare("SELECT friend FROM friends WHERE xuid=?").bind(xuid);
  const ids = (await stmt.all()).results.map((r) => r.friend);
  const n = await names(db, ids);
  return ids.map((i) => ({ xuid: hex16(i), name: n.get(i) ?? "?" }));
}

async function addFriend(db, xuid, name) {
  const other = xuidFor(name);
  if (!(await names(db, [other])).size) throw new ApiError(404, `no player called '${name}'`);
  await db.batch([
    db.prepare("INSERT OR IGNORE INTO friends VALUES (?,?)").bind(xuid, other),
    db.prepare("INSERT OR IGNORE INTO friends VALUES (?,?)").bind(other, xuid),
  ]);
}

// -- responses -------------------------------------------------------------------------------
const json = (status, obj) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const text = (body) =>
  new Response(body, { status: 200, headers: { "Content-Type": "text/plain" } });

// Compact format for the game client: a 'total' line, then one tab-separated line per row:
// xuid, rank, rating, name, id:type:value;id:type:value...
function boardText(board) {
  const out = [`total\t${board.total}`];
  for (const r of board.rows) {
    const props = Object.values(r.props)
      .map((p) => `${p.id}:${p.type}:${p.value}`)
      .join(";");
    out.push(`${r.xuid}\t${r.rank}\t${r.rating}\t${r.name}\t${props}`);
  }
  return out.join("\n") + "\n";
}

const board = (q, obj) => (q.get("fmt") === "text" ? text(boardText(obj)) : json(200, obj));

async function route(req, env) {
  const url = new URL(req.url);
  const path = url.pathname;
  const q = url.searchParams;
  const m = req.method;
  // Use the binding called DB, or else whatever D1 database is bound (any name).
  const db =
    env.DB ||
    Object.values(env).find(
      (v) => v && typeof v.prepare === "function" && typeof v.batch === "function",
    );

  if (m === "GET" && path === "/health") return json(200, { ok: true, database: !!db });
  if (!db) throw new ApiError(500, "no D1 database bound to this Worker");
  await ensureSchema(db);

  if (m === "GET" && path === "/api/v1/hello") {
    return json(200, { xuid: hex16(await authenticate(db, req)) });
  }
  if (m === "POST" && path === "/api/v1/stats") {
    const xuid = await authenticate(db, req);
    const body = await readBody(req);
    return json(200, { updated: await submit(db, env, xuid, body.views) });
  }
  if (m === "GET" && path === "/api/v1/leaderboard") {
    await authenticate(db, req);
    const view = parseInt(q.get("view"), 10);
    if (!Number.isFinite(view)) throw new ApiError(400, "bad request: view");
    const count = Math.min(parseInt(q.get("count") ?? "10", 10) || 10, 100);
    const rows = q.has("around")
      ? await around(db, env, view, parseHex(q.get("around")), count)
      : await byRank(db, env, view, parseInt(q.get("start") ?? "1", 10) || 1, count);
    return board(q, { view, total: await total(db, view), rows });
  }
  if (m === "POST" && path === "/api/v1/read") {
    await authenticate(db, req);
    const body = await readBody(req);
    const view = parseInt(body.view, 10);
    if (!Number.isFinite(view)) throw new ApiError(400, "bad request: view");
    const xuids = (body.xuids || []).slice(0, 100).map((x) => parseHex(String(x)));
    return board(q, { view, total: await total(db, view), rows: await byXuids(db, env, view, xuids) });
  }
  if (m === "GET" && path === "/api/v1/friends") {
    const list = await friends(db, env, await authenticate(db, req));
    if (q.get("fmt") === "text") return text(list.map((f) => `${f.xuid}\t${f.name}\n`).join(""));
    return json(200, { friends: list });
  }
  if (m === "POST" && path === "/api/v1/friends") {
    const xuid = await authenticate(db, req);
    const body = await readBody(req);
    await addFriend(db, xuid, String(body.name ?? ""));
    return json(200, { friends: await friends(db, env, xuid) });
  }
  if (path.startsWith("/api/v1/admin/")) {
    if (!env.ADMIN_KEY || req.headers.get("X-Admin-Key") !== env.ADMIN_KEY)
      throw new ApiError(403, "admin key required");
    if (m === "GET" && path === "/api/v1/admin/players") {
      const { results } = await db.prepare("SELECT xuid, name, created FROM players").all();
      return json(
        200,
        results.map((r) => ({ xuid: hex16(r.xuid), name: r.name, created: r.created })),
      );
    }
    if (m === "POST" && path === "/api/v1/admin/reset_key") {
      const name = String((await readBody(req)).name ?? "");
      await db.prepare("DELETE FROM players WHERE name=?").bind(name).run();
      return json(200, { reset: name });
    }
  }
  throw new ApiError(404, "not found");
}

export default {
  async fetch(req, env) {
    try {
      return await route(req, env);
    } catch (e) {
      if (e instanceof ApiError) return json(e.status, { error: e.message });
      console.error(e && e.stack ? e.stack : String(e));
      return json(500, { error: "internal error" });
    }
  },
};
