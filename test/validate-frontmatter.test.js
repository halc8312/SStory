const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const validator = require('../scripts/validate-frontmatter');

function withTempDir(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'frontmatter-test-'));
  try {
    return fn(dir);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test('checkFrontmatter reports missing frontmatter', () => {
  validator.resetStats();

  const result = validator.checkFrontmatter('/tmp/example.md', '# No frontmatter');

  assert.equal(result, undefined);
  assert.deepEqual(validator.getStats(), { errors: 1, warnings: 0, checked: 1 });
});

test('checkFrontmatter returns parsed data and records warnings', () => {
  validator.resetStats();

  const result = validator.checkFrontmatter(
    '/tmp/unexpected-name.md',
    `---
title: Mystic Archive
version: 1
created: 2026-01-01
last_updated: 2026-01-02
author: Tester
category: invalid
status: unstable
---
Body
`
  );

  assert.equal(result.title, 'Mystic Archive');
  assert.deepEqual(validator.getStats(), { errors: 0, warnings: 3, checked: 1 });
});

test('checkLinks resolves relative markdown links and ignores external links', () => {
  withTempDir((dir) => {
    const page = path.join(dir, 'page.md');
    fs.writeFileSync(path.join(dir, 'target.md'), '# target');

    const brokenLinks = validator.checkLinks(
      [
        '[ok](./target)',
        '[missing](./missing)',
        '[web](https://example.com)',
        '[mail](mailto:test@example.com)'
      ].join('\n'),
      page
    );

    assert.deepEqual(brokenLinks, [
      {
        link: './missing',
        target: path.join(dir, 'missing.md'),
        file: page
      }
    ]);
  });
});

test('walkDir recurses through markdown files and skips ignored directories', () => {
  withTempDir((dir) => {
    fs.mkdirSync(path.join(dir, 'notes'), { recursive: true });
    fs.mkdirSync(path.join(dir, 'node_modules'), { recursive: true });
    fs.mkdirSync(path.join(dir, 'evaluation'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'notes', 'kept.md'), '# kept');
    fs.writeFileSync(path.join(dir, 'node_modules', 'ignored.md'), '# ignored');
    fs.writeFileSync(path.join(dir, 'evaluation', 'ignored.md'), '# ignored');
    fs.writeFileSync(path.join(dir, 'notes', 'skip.txt'), 'skip');

    const found = [];
    validator.walkDir(dir, (filePath) => found.push(path.relative(dir, filePath)));

    assert.deepEqual(found, ['notes/kept.md']);
  });
});
