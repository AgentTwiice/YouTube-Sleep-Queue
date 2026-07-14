const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const updater = require("./bump-uv-lock.js");

const SAMPLE = `version = 1
revision = 3
requires-python = ">=3.11"

[[package]]
name = "flask"
version = "3.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "youtube-sleep-queue"
version = "4.1.0"
source = { editable = "." }

[package.metadata]
requires-dist = []
`;

// readVersion finds the project version, not flask's
assert.equal(
  updater.readVersion(SAMPLE),
  "4.1.0",
  "readVersion returns the project version, not flask's"
);

// writeVersion updates only the youtube-sleep-queue [[package]] block
const bumped = updater.writeVersion(SAMPLE, "4.2.0");
assert.match(
  bumped,
  /name = "youtube-sleep-queue"\s*\nversion = "4\.2\.0"/,
  "writeVersion bumps youtube-sleep-queue version"
);
assert.match(
  bumped,
  /name = "flask"\s*\nversion = "3\.0\.0"/,
  "writeVersion leaves flask version alone"
);

// readVersion throws when the project package is missing
assert.throws(
  () => updater.readVersion(`[[package]]\nname = "flask"\nversion = "3.0.0"\n`),
  /youtube-sleep-queue package not found/,
  "readVersion throws when the project package is missing"
);

assert.throws(
  () => updater.writeVersion(`[[package]]\nname = "flask"\nversion = "3.0.0"\n`, "5.0.0"),
  /youtube-sleep-queue package not found/,
  "writeVersion throws when the project package is missing"
);

// Exercise the updater against the actual repository lockfile so a package
// rename cannot silently break the release process again.
const repositoryRoot = path.resolve(__dirname, "..");
const actualLockfile = fs.readFileSync(path.join(repositoryRoot, "uv.lock"), "utf8");
const packageVersion = require(path.join(repositoryRoot, "package.json")).version;
assert.equal(updater.readVersion(actualLockfile), packageVersion);
assert.match(
  updater.writeVersion(actualLockfile, "9.9.9"),
  /name = "youtube-sleep-queue"\s*\nversion = "9\.9\.9"/
);

console.log("ok - bump-uv-lock updater");
