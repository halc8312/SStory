#!/usr/bin/env node

/**
 * Run the repository's Python tooling on Windows, macOS, and Linux.
 *
 * Windows commonly exposes Python through the `py` launcher while CI images
 * expose `python3`. npm scripts should not need platform-specific variants.
 */

const { spawnSync } = require('node:child_process');

function pythonCandidates(platform = process.platform) {
  const configured = process.env.SSTORY_PYTHON;
  const candidates = configured ? [{ command: configured, prefix: [] }] : [];

  if (platform === 'win32') {
    candidates.push(
      { command: 'py', prefix: ['-3'] },
      { command: 'python3', prefix: [] },
      { command: 'python', prefix: [] }
    );
  } else {
    candidates.push(
      { command: 'python3', prefix: [] },
      { command: 'python', prefix: [] }
    );
  }

  return candidates;
}

function runPython(args, options = {}) {
  for (const candidate of pythonCandidates(options.platform)) {
    const result = spawnSync(candidate.command, [...candidate.prefix, ...args], {
      cwd: options.cwd || process.cwd(),
      env: options.env || process.env,
      stdio: options.stdio || 'inherit',
      shell: false
    });

    if (result.error?.code === 'ENOENT') {
      continue;
    }

    if (result.error) {
      throw result.error;
    }

    return result.status ?? 1;
  }

  throw new Error(
    'Python 3 was not found. Install Python 3 or set SSTORY_PYTHON to its executable path.'
  );
}

function main() {
  if (process.argv.length < 3) {
    console.error('Usage: node scripts/run-python.js <script-or-module> [args...]');
    process.exit(2);
  }

  try {
    process.exit(runPython(process.argv.slice(2)));
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = { pythonCandidates, runPython };
