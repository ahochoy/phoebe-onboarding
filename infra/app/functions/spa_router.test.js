// Loads spa_router.js the way CloudFront Functions see it: a bare script that
// defines handler(event), no module system. Run with `node --test`.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "spa_router.js"), "utf8");
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
assert.equal(typeof sandbox.handler, "function", "spa_router.js must define handler(event)");

function route(uri, extra = {}) {
  const request = { method: "GET", uri, headers: {}, ...extra };
  return sandbox.handler({ version: "1.0", request });
}

const cases = [
  // SPA fallback
  ["/", "/index.html"],
  ["/employee", "/index.html"],
  ["/admin/tasks", "/index.html"],
  ["/admin/tasks/", "/index.html"],
  // static files pass through
  ["/assets/app.js", "/assets/app.js"],
  ["/favicon.svg", "/favicon.svg"],
  ["/index.html", "/index.html"],
  // hosted seed sources pass through untouched
  ["/seed-sources/benefits.html", "/seed-sources/benefits.html"],
  // previews
  ["/pr-12/", "/previews/pr-12/index.html"],
  ["/pr-12", "/previews/pr-12/index.html"],
  ["/pr-12/admin/tasks", "/previews/pr-12/index.html"],
  ["/pr-12/assets/x.js", "/previews/pr-12/assets/x.js"],
  ["/pr-123/employee", "/previews/pr-123/index.html"],
  // not previews: look-alikes fall back to the SPA
  ["/pr-x/assets/x.js", "/pr-x/assets/x.js"],
  ["/pr-12abc", "/index.html"],
  ["/previews/pr-12/index.html", "/previews/pr-12/index.html"],
];

for (const [input, expected] of cases) {
  test(`${input} -> ${expected}`, () => {
    assert.equal(route(input).uri, expected);
  });
}

test("returns the request object, preserving other fields", () => {
  const out = route("/employee", { headers: { host: { value: "x" } } });
  assert.equal(out.method, "GET");
  assert.deepEqual(out.headers, { host: { value: "x" } });
});

test("source has no module syntax or dependencies", () => {
  assert.doesNotMatch(source, /\brequire\(|\bimport\b|\bexport\b|module\.exports/);
});
