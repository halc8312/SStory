#!/usr/bin/env node

/**
 * Cross-platform entry point for markdown-link-check.
 *
 * Shell glob expansion differs between Windows and POSIX shells. Resolve the
 * Markdown file list in Node so the same npm command checks the same files on
 * every platform and never descends into generated/dependency directories.
 */

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const REPO_ROOT = path.join(__dirname, '..');
const IGNORED_DIRECTORIES = new Set([
  '.git',
  'build',
  'dist',
  'evaluation',
  'Evaluation',
  'node_modules',
  'site'
]);

function collectMarkdownFiles(rootDir = REPO_ROOT) {
  const files = [];

  function walk(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
      .sort((left, right) => left.name.localeCompare(right.name));

    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!IGNORED_DIRECTORIES.has(entry.name)) {
          walk(fullPath);
        }
      } else if (entry.isFile() && entry.name.toLowerCase().endsWith('.md')) {
        files.push(fullPath);
      }
    }
  }

  walk(rootDir);
  return files;
}

function markdownLinkCheckCli() {
  const packagePath = require.resolve('markdown-link-check/package.json');
  const packageData = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
  return path.join(path.dirname(packagePath), packageData.bin['markdown-link-check']);
}

function main() {
  const files = collectMarkdownFiles();
  if (files.length === 0) {
    console.error('No Markdown files found.');
    process.exit(1);
  }

  const result = spawnSync(
    process.execPath,
    [
      markdownLinkCheckCli(),
      '--quiet',
      '--config',
      path.join(REPO_ROOT, '.markdown-link-check.json'),
      ...files
    ],
    { cwd: REPO_ROOT, stdio: 'inherit', shell: false }
  );

  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  process.exit(result.status ?? 1);
}

if (require.main === module) {
  main();
}

module.exports = { IGNORED_DIRECTORIES, collectMarkdownFiles, markdownLinkCheckCli };
