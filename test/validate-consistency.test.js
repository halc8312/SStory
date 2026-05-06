const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const validator = require('../scripts/validate-consistency');

function withTempDir(fn) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'consistency-test-'));
  try {
    return fn(dir);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test('getAllMarkdown collects nested markdown files only', () => {
  withTempDir((dir) => {
    fs.mkdirSync(path.join(dir, 'nested'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'root.md'), '# root');
    fs.writeFileSync(path.join(dir, 'nested', 'child.md'), '# child');
    fs.writeFileSync(path.join(dir, 'nested', 'child.txt'), 'skip');

    const files = validator.getAllMarkdown(dir).map((file) => path.relative(dir, file)).sort();

    assert.deepEqual(files, ['nested/child.md', 'root.md']);
  });
});

test('checkTerms reports all supported term inconsistencies', () => {
  withTempDir((dir) => {
    fs.writeFileSync(path.join(dir, 'issues.md'), 'ドリト\nAD 1200\n500 kmkm²\n');

    const issues = validator.checkTerms(dir);

    assert.equal(issues.length, 3);
    assert.match(issues[0], /ドリト/);
    assert.match(issues[1], /AD/);
    assert.match(issues[2], /kmkm²/);
  });
});

test('checkLinks flags missing markdown targets', () => {
  withTempDir((dir) => {
    fs.mkdirSync(path.join(dir, 'sub'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'target.md'), '# target');
    fs.writeFileSync(
      path.join(dir, 'sub', 'page.md'),
      '[good](../target.md)\n[bad](../missing.md)\n[web](http://example.com)\n'
    );

    const issues = validator.checkLinks(dir);

    assert.deepEqual(issues, [path.join(dir, 'sub', 'page.md') + ': broken link -> ../missing.md']);
  });
});
