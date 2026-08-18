import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import {
  clearSavedHeader,
  clearSignedOut,
  defaultBrowserCandidates,
  hasYoutubeSession,
  isSignedOut,
  markSignedOut,
  resolveCookies,
  slimCookieHeader,
  writeSavedHeader,
} from "../src/cookies.js";

test("hasYoutubeSession requires LOGIN_INFO or SAPISID", () => {
  assert.equal(hasYoutubeSession(""), false);
  assert.equal(hasYoutubeSession("VISITOR_INFO1_LIVE=abc"), false);
  assert.equal(hasYoutubeSession("SAPISID=secret; VISITOR_INFO1_LIVE=abc"), true);
  assert.equal(hasYoutubeSession("LOGIN_INFO=xyz"), true);
});

test("slimCookieHeader keeps youtube session cookies only", () => {
  const slim = slimCookieHeader("foo=1; SAPISID=s; random=no; __Secure-1PSID=p; LOGIN_INFO=li");
  assert.match(slim, /SAPISID=s/);
  assert.match(slim, /LOGIN_INFO=li/);
  assert.match(slim, /__Secure-1PSID=p/);
  assert.doesNotMatch(slim, /foo=1/);
  assert.doesNotMatch(slim, /random=no/);
});

test("resolveCookies prefers a saved session over browsers", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-auth-"));
  const saved = path.join(dir, "cookies.header");
  writeSavedHeader(saved, "SAPISID=from-file");
  const resolved = resolveCookies({
    spec: "auto",
    home: dir,
    savedPath: saved,
  });
  assert.equal(resolved.source, "saved");
  assert.match(resolved.header, /SAPISID=from-file/);
});

test("resolveCookies skipSaved ignores the saved header", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-auth-skip-"));
  const saved = path.join(dir, "cookies.header");
  writeSavedHeader(saved, "SAPISID=from-file");
  const resolved = resolveCookies({
    spec: "auto",
    home: dir,
    savedPath: saved,
    skipSaved: true,
  });
  assert.equal(resolved.header, "");
  assert.equal(resolved.source, "");
});

test("signed-out flag survives until cleared", () => {
  const flag = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "music-out-")), "signed-out");
  assert.equal(isSignedOut(flag), false);
  markSignedOut(flag);
  assert.equal(isSignedOut(flag), true);
  clearSignedOut(flag);
  assert.equal(isSignedOut(flag), false);
});

test("clearSavedHeader removes the session file", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-auth-out-"));
  const saved = path.join(dir, "cookies.header");
  writeSavedHeader(saved, "SAPISID=from-file");
  assert.equal(fs.existsSync(saved), true);
  clearSavedHeader(saved);
  assert.equal(fs.existsSync(saved), false);
  clearSavedHeader(saved);
});

test("resolveCookies uses an explicit firefox profile sqlite", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "music-ff-"));
  const profile = path.join(dir, "profile");
  fs.mkdirSync(profile);
  const db = path.join(profile, "cookies.sqlite");
  execFileSync("sqlite3", [
    db,
    "CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT);",
    "INSERT INTO moz_cookies VALUES ('.youtube.com','SAPISID','from-zen');",
    "INSERT INTO moz_cookies VALUES ('.youtube.com','noise','ignore-me');",
  ]);
  const resolved = resolveCookies({
    spec: `firefox:${profile}`,
    home: dir,
    savedPath: path.join(dir, "missing.header"),
  });
  assert.equal(resolved.source, `firefox:${profile}`);
  assert.match(resolved.header, /SAPISID=from-zen/);
  assert.doesNotMatch(resolved.header, /noise=/);
});

test("resolveCookies scans known browsers when spec is auto", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "music-home-"));
  const zen = path.join(home, ".config", "zen", "abc.default");
  fs.mkdirSync(zen, { recursive: true });
  execFileSync("sqlite3", [
    path.join(zen, "cookies.sqlite"),
    "CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT);",
    "INSERT INTO moz_cookies VALUES ('.youtube.com','LOGIN_INFO','from-scan');",
  ]);
  const resolved = resolveCookies({
    spec: "auto",
    home,
    savedPath: path.join(home, "missing.header"),
  });
  assert.equal(resolved.source.startsWith("firefox:"), true);
  assert.match(resolved.header, /LOGIN_INFO=from-scan/);
});

test("resolveCookies returns empty when nothing is logged in", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "music-empty-"));
  const resolved = resolveCookies({
    spec: "auto",
    home,
    savedPath: path.join(home, "missing.header"),
  });
  assert.equal(resolved.header, "");
  assert.equal(resolved.source, "");
});

test("defaultBrowserCandidates covers zen firefox chrome and brave", () => {
  const list = defaultBrowserCandidates("/home/someone");
  const keys = list.map((c) => `${c.browser}:${c.profileDir}`);
  assert.ok(keys.some((k) => k.includes("firefox:") && k.includes(".config/zen")));
  assert.ok(keys.some((k) => k.includes(".mozilla/firefox")));
  assert.ok(keys.some((k) => k.includes("google-chrome")));
  assert.ok(keys.some((k) => k.includes("Brave-Browser")));
});
