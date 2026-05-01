#!/usr/bin/env node

/**
 * SStory Frontmatter Validator
 *
 * Checks all markdown files for:
 * - Presence of YAML frontmatter
 * - Required fields (title, version, created, last_updated, author, category, status)
 * - Valid category values
 * - File naming conventions
 * - Cross-reference validation
 */

const fs = require('fs');
const path = require('path');

const WORLD_DIR = path.join(__dirname, '..', 'world');
const ROOT = __dirname.replace('/scripts', '');

const REQUIRED_FIELDS = ['title', 'version', 'created', 'last_updated', 'author', 'category', 'status'];
const VALID_CATEGORIES = [
  'lore', 'geography', 'races', 'magic', 'politics',
  'creatures', 'culture', 'economy', 'religion', 'maps',
  'rules', 'npcs', 'glossary', 'index', 'readme'
];
const VALID_STATUS = ['draft', 'review', 'stable'];

let errors = 0;
let warnings = 0;
let checked = 0;

function log(message, type = 'INFO') {
  const colors = {
    INFO: '\x1b[36m',
    WARN: '\x1b[33m',
    ERROR: '\x1b[31m',
    SUCCESS: '\x1b[32m',
    RESET: '\x1b[0m'
  };
  console.log(`${colors[type] || ''}[${type}]${colors.RESET} ${message}`);
}

function checkFrontmatter(filePath, content) {
  checked++;

  // Check if file starts with ---
  if (!content.startsWith('---')) {
    log(`Missing frontmatter: ${filePath}`, 'ERROR');
    errors++;
    return;
  }

  // Extract frontmatter
  const frontmatterEnd = content.indexOf('---', 3);
  if (frontmatterEnd === -1) {
    log(`Invalid frontmatter (no closing ---): ${filePath}`, 'ERROR');
    errors++;
    return;
  }

  const frontmatterStr = content.substring(3, frontmatterEnd);
  let frontmatter;
  try {
    frontmatter = require('yaml').parse(frontmatterStr);
  } catch (e) {
    log(`YAML parse error in ${filePath}: ${e.message}`, 'ERROR');
    errors++;
    return;
  }

  // Check required fields
  REQUIRED_FIELDS.forEach(field => {
    if (!frontmatter[field]) {
      log(`Missing required field '${field}' in ${filePath}`, 'ERROR');
      errors++;
    }
  });

  // Validate category
  if (frontmatter.category && !VALID_CATEGORIES.includes(frontmatter.category)) {
    log(`Invalid category '${frontmatter.category}' in ${filePath}. Valid: ${VALID_CATEGORIES.join(', ')}`, 'WARN');
    warnings++;
  }

  // Validate status
  if (frontmatter.status && !VALID_STATUS.includes(frontmatter.status)) {
    log(`Invalid status '${frontmatter.status}' in ${filePath}. Valid: ${VALID_STATUS.join(', ')}`, 'WARN');
    warnings++;
  }

  // Check file name matches title (rough check)
  const fileName = path.basename(filePath, '.md');
  const expectedSlug = frontmatter.title
    ?.toLowerCase()
    .replace(/[^\w\sー\-ぁ-んア-ン一-龥]/g, '')
    .replace(/\s+/g, '-')
    .substring(0, 50);

  if (expectedSlug && !fileName.includes(expectedSlug.substring(0, 10))) {
    log(`Title may not match filename: ${filePath} (title: ${frontmatter.title})`, 'WARN');
    warnings++;
  }

  return frontmatter;
}

function checkLinks(content, filePath) {
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
  let match;
  const brokenLinks = [];

  while ((match = linkRegex.exec(content)) !== null) {
    const [full, text, link] = match;

    // Skip external links
    if (link.startsWith('http://') || link.startsWith('https://') || link.startsWith('mailto:')) {
      continue;
    }

    // Resolve relative path
    const dir = path.dirname(filePath);
    const targetPath = path.resolve(dir, link);

    // Remove .md extension if exists
    const finalPath = targetPath.endsWith('.md') ? targetPath : targetPath + '.md';

    if (!fs.existsSync(finalPath)) {
      brokenLinks.push({ link, target: finalPath, file: filePath });
    }
  }

  return brokenLinks;
}

function walkDir(dir, callback) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      // Skip node_modules, .git, evaluation, etc.
      if (['node_modules', '.git', 'evaluation', 'dist', 'build'].includes(entry.name)) {
        continue;
      }
      walkDir(fullPath, callback);
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      callback(fullPath, entry.name);
    }
  }
}

function main() {
  log('SStory Frontmatter Validator starting...', 'INFO');
  console.log('');

  // Check all markdown files
  const allFiles = [];
  walkDir(ROOT, (filePath, fileName) => {
    allFiles.push({ filePath, fileName });
  });

  log(`Found ${allFiles.length} markdown files to check`, 'INFO');
  console.log('');

  const brokenLinks = [];

  allFiles.forEach(({ filePath, fileName }) => {
    try {
      const content = fs.readFileSync(filePath, 'utf-8');

      // Check frontmatter
      checkFrontmatter(filePath, content);

      // Check links (only in world/ directory)
      if (filePath.includes('/world/')) {
        const fileBrokenLinks = checkLinks(content, filePath);
        brokenLinks.push(...fileBrokenLinks);
      }
    } catch (err) {
      log(`Error reading ${filePath}: ${err.message}`, 'ERROR');
      errors++;
    }
  });

  console.log('');
  log('=== Validation Summary ===', 'INFO');
  log(`Files checked: ${checked}`, 'INFO');
  log(`Errors: ${errors}`, errors > 0 ? 'ERROR' : 'SUCCESS');
  log(`Warnings: ${warnings}`, warnings > 0 ? 'WARN' : 'SUCCESS');

  if (brokenLinks.length > 0) {
    log(`Broken links found: ${brokenLinks.length}`, 'ERROR');
    brokenLinks.forEach(({ link, target, file }) => {
      log(`  ${file}: ${link} -> ${target} (not found)`, 'ERROR');
    });
    errors += brokenLinks.length;
  } else {
    log('Broken links: 0', 'SUCCESS');
  }

  console.log('');

  if (errors > 0) {
    log('Validation FAILED', 'ERROR');
    process.exit(1);
  } else {
    log('Validation PASSED', 'SUCCESS');
    process.exit(0);
  }
}

// Check if yaml package is available, if not use simple regex parsing
try {
  require('yaml');
} catch (e) {
  // Fallback: simple regex parsing
  console.log('Note: Install "yaml" package for full YAML validation');
}

main();
