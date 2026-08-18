import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

test("index.js named imports exist on the modules they name", async () => {
  const src = fs.readFileSync(new URL("../src/index.js", import.meta.url), "utf8");
  const blocks = [...src.matchAll(/import\s+\{([^}]+)\}\s+from\s+"(\.[^"]+)"/g)];
  assert.ok(blocks.length > 0);
  for (const [, names, spec] of blocks) {
    const mod = await import(new URL(spec, new URL("../src/", import.meta.url)));
    for (const raw of names.split(",")) {
      const name = raw.replace(/\s+as\s+\w+/g, "").trim();
      if (!name) {
        continue;
      }
      assert.notEqual(mod[name], undefined, `${spec} is missing ${name}`);
    }
  }
});
