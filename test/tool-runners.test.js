const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { pythonCandidates } = require('../scripts/run-python');
const { collectMarkdownFiles } = require('../scripts/run-markdown-link-check');

test('pythonCandidates uses the Windows launcher before executable aliases', () => {
  const previous = process.env.SSTORY_PYTHON;
  delete process.env.SSTORY_PYTHON;
  try {
    assert.deepEqual(pythonCandidates('win32'), [
      { command: 'py', prefix: ['-3'] },
      { command: 'python3', prefix: [] },
      { command: 'python', prefix: [] }
    ]);
  } finally {
    if (previous === undefined) {
      delete process.env.SSTORY_PYTHON;
    } else {
      process.env.SSTORY_PYTHON = previous;
    }
  }
});

test('collectMarkdownFiles is recursive and excludes dependency directories', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'markdown-files-test-'));
  try {
    fs.mkdirSync(path.join(dir, 'nested'));
    fs.mkdirSync(path.join(dir, 'evaluation'));
    fs.mkdirSync(path.join(dir, 'node_modules'));
    fs.writeFileSync(path.join(dir, 'root.md'), '# root');
    fs.writeFileSync(path.join(dir, 'nested', 'child.md'), '# child');
    fs.writeFileSync(path.join(dir, 'node_modules', 'ignored.md'), '# ignored');
    fs.writeFileSync(path.join(dir, 'evaluation', 'ignored.md'), '# ignored');
    fs.writeFileSync(path.join(dir, 'nested', 'ignored.txt'), 'ignored');

    const files = collectMarkdownFiles(dir).map(file => path.relative(dir, file));
    assert.deepEqual(files, [path.join('nested', 'child.md'), 'root.md']);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
