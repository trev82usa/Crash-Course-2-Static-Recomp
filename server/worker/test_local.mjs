// Local test: node test_local.mjs (Node 22+, uses node:sqlite as a stand-in for D1).
// D1 stand-in on node:sqlite, then exercise the Worker's API.
import { DatabaseSync } from "node:sqlite";
import worker from "./worker.js";
const sql = new DatabaseSync(":memory:");
class Stmt {
  constructor(q) { this.q = q; this.args = []; }
  bind(...a) { this.args = a; return this; }
  async first() { return sql.prepare(this.q).get(...this.args) ?? null; }
  async all() { return { results: sql.prepare(this.q).all(...this.args) }; }
  async run() { sql.prepare(this.q).run(...this.args); return {}; }
}
const DB = { prepare: (q) => new Stmt(q), batch: async (ss) => { for (const s of ss) await s.run(); } };
const env = { DB };
const call = async (method, path, name, key, body) => {
  const r = await worker.fetch(new Request("https://x" + path, { method,
    headers: { "X-Player-Name": name, "X-Player-Key": key }, body: body ? JSON.stringify(body) : undefined }), env);
  return [r.status, await r.text()];
};
const stats = (view, rating) => ({ views: [{ view, props: [{ id: 0x20000008, type: 2, value: rating }] }] });
console.log("hello", await call("GET", "/api/v1/hello", "Trev", "password1"));
console.log("wrong key", await call("GET", "/api/v1/hello", "Trev", "password2"));
console.log("Trev post", await call("POST", "/api/v1/stats", "Trev", "password1", stats(0, -61234)));
console.log("Amy post", await call("POST", "/api/v1/stats", "Amy", "password9", stats(0, -59000)));
console.log("Trev worse", await call("POST", "/api/v1/stats", "Trev", "password1", stats(0, -70000)));
console.log("board 0", (await call("GET", "/api/v1/leaderboard?fmt=text&view=0&start=1&count=10", "Trev", "password1"))[1]);
// weekly: Trev's old week entry should be ignored
await call("POST", "/api/v1/stats", "Trev", "password1", stats(6, -50000));
sql.prepare("UPDATE entries SET updated = updated - 8*86400 WHERE view=6").run();
console.log("weekly after a week", (await call("GET", "/api/v1/leaderboard?fmt=text&view=6", "Trev", "password1"))[1]);
await call("POST", "/api/v1/stats", "Trev", "password1", stats(6, -90000));
console.log("weekly new post (worse than last week, still counts)", (await call("GET", "/api/v1/leaderboard?fmt=text&view=6", "Trev", "password1"))[1]);
console.log("read", (await call("POST", "/api/v1/read?fmt=text", "Amy", "password9", { view: 0, xuids: [] }))[1]);
