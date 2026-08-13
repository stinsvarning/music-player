import assert from "node:assert/strict";
import { test } from "node:test";
import { fail, ok, parseRequest } from "../src/protocol.js";

test("parses seek as absolute value", () => {
  const parsed = parseRequest('{"cmd":"seek","value":90}');
  assert.equal(parsed.ok, true);
  assert.equal(parsed.request.cmd, "seek");
  assert.equal(parsed.request.value, 90);
});

test("rejects missing cmd", () => {
  const parsed = parseRequest('{"value":1}');
  assert.equal(parsed.ok, false);
});

test("ok and fail envelopes", () => {
  assert.deepEqual(ok({ state: "playing" }), { ok: true, state: "playing" });
  assert.deepEqual(fail("nope"), { ok: false, error: "nope" });
});
