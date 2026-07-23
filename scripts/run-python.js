#!/usr/bin/env node

/**
 * Run the repository's Python tooling on Windows, macOS, and Linux.
 *
 * Prefer the active environment's executable aliases before the Windows
 * launcher. setup-python and virtual environments update `python` on PATH,
 * while `py -3` can select a different system installation with no packages.
 */

const { spawnSync } = require('node:child_process');

function pythonCandidates(platform = process.platform) {
  const configured = process.env.SSTORY_PYTHON;
  const candidates = configured ? [{ command: configured, prefix: [] }] : [];

  if (platform === 'win32') {
    candidates.push(
      { command: 'python', prefix: [] },
      { command: 'python3', prefix: [] },
      { command: 'py', prefix: ['-3'] }
    );
  } else {
    candidates.push(
      { command: 'python3', prefix: [] },
      { command: 'python', prefix: [] }
    );
  }

  return candidates;
}

function isUsablePythonCandidate(candidate, options = {}) {
  const probe = spawnSync(
    candidate.command,
    [...candidate.prefix, '-c', 'print("SSTORY_PYTHON_OK")'],
    {
      cwd: options.cwd || process.cwd(),
      env: options.env || process.env,
      encoding: 'utf8',
      shell: false
    }
  );

  return !probe.error && probe.status === 0 && probe.stdout.includes('SSTORY_PYTHON_OK');
}

function runPython(args, options = {}) {
  for (const candidate of pythonCandidates(options.platform)) {
    if (!isUsablePythonCandidate(candidate, options)) {
      continue;
    }

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

module.exports = { isUsablePythonCandidate, pythonCandidates, runPython };
