#!/usr/bin/env node

/**
 * Validate YAML frontmatter and internal links in world/ Markdown documents.
 *
 * Common frontmatter rules are loaded from schemas/common.yaml. Keeping the
 * schema as the single source of truth prevents the validator from drifting
 * away from the documented metadata contract.
 */

const fs = require('node:fs');
const path = require('node:path');
const Ajv = require('ajv');
const addFormats = require('ajv-formats');
const YAML = require('yaml');

const REPO_ROOT = path.join(__dirname, '..');
const WORLD_DIR = path.join(REPO_ROOT, 'world');
const SCHEMA_DIR = path.join(REPO_ROOT, 'schemas');
const COMMON_SCHEMA_PATH = path.join(SCHEMA_DIR, 'common.yaml');
const SCHEMA_BASE_URI = 'https://sstory.local/schemas/';
const TYPE_SCHEMA_FILES = Object.freeze({
  'canon-document': 'canon-document.yaml',
  npc: 'npc.yaml',
  rule: 'rule.yaml',
  asset: 'asset.yaml',
  analysis: 'analysis.yaml',
  overview: 'overview.yaml'
});

const commonSchema = YAML.parse(fs.readFileSync(COMMON_SCHEMA_PATH, 'utf8'));
const REQUIRED_FIELDS = Object.freeze([...(commonSchema.required || [])]);
const VALID_TYPES = Object.freeze([...(commonSchema.properties?.type?.enum || [])]);
const VALID_CATEGORIES = Object.freeze([...(commonSchema.properties?.category?.enum || [])]);
const VALID_STATUS = Object.freeze([...(commonSchema.properties?.status?.enum || [])]);

function loadSchema(schemaFile) {
  const schemaPath = path.join(SCHEMA_DIR, schemaFile);
  const schema = YAML.parse(fs.readFileSync(schemaPath, 'utf8'));
  return { ...schema, $id: `${SCHEMA_BASE_URI}${schemaFile}` };
}

function createSchemaValidators() {
  const schemaAjv = new Ajv({ allErrors: true, strict: false });
  addFormats(schemaAjv);
  const schemas = new Map();

  for (const schemaFile of ['common.yaml', ...Object.values(TYPE_SCHEMA_FILES)]) {
    const schema = loadSchema(schemaFile);
    schemas.set(schemaFile, schema);
    schemaAjv.addSchema(schema, schema.$id);
  }

  const validators = new Map();
  for (const schemaFile of schemas.keys()) {
    validators.set(schemaFile, schemaAjv.getSchema(`${SCHEMA_BASE_URI}${schemaFile}`));
  }
  return validators;
}

const schemaValidators = createSchemaValidators();

let errors = 0;
let warnings = 0;
let checked = 0;

function resetStats() {
  errors = 0;
  warnings = 0;
  checked = 0;
}

function getStats() {
  return { errors, warnings, checked };
}

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

function extractFrontmatter(content) {
  const match = content.match(/^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/);
  return match?.[1];
}

function formatSchemaError(schemaError) {
  const location = schemaError.instancePath || '/';
  return `${location} ${schemaError.message}`;
}

function checkFrontmatter(filePath, content) {
  checked++;

  const frontmatterText = extractFrontmatter(content);
  if (frontmatterText === undefined) {
    log(`Missing or invalid frontmatter: ${filePath}`, 'ERROR');
    errors++;
    return undefined;
  }

  let frontmatter;
  try {
    frontmatter = YAML.parse(frontmatterText);
  } catch (error) {
    log(`YAML parse error in ${filePath}: ${error.message}`, 'ERROR');
    errors++;
    return undefined;
  }

  if (!frontmatter || typeof frontmatter !== 'object' || Array.isArray(frontmatter)) {
    log(`Frontmatter must be a YAML mapping: ${filePath}`, 'ERROR');
    errors++;
    return frontmatter;
  }

  const schemaFile = TYPE_SCHEMA_FILES[frontmatter.type] || 'common.yaml';
  const validateFrontmatter = schemaValidators.get(schemaFile);
  if (!validateFrontmatter(frontmatter)) {
    for (const schemaError of validateFrontmatter.errors || []) {
      log(`Schema violation in ${filePath}: ${formatSchemaError(schemaError)}`, 'ERROR');
      errors++;
    }
  }

  return frontmatter;
}

function markdownDestination(rawDestination) {
  let destination = rawDestination.trim();
  if (destination.startsWith('<')) {
    const closingBracket = destination.indexOf('>');
    if (closingBracket !== -1) {
      return destination.slice(1, closingBracket);
    }
  }

  // Strip an optional Markdown link title while preserving URL-encoded spaces.
  const titleMatch = destination.match(/^(\S+)(?:\s+["'].*["'])?$/);
  return titleMatch ? titleMatch[1] : destination;
}

function resolveInternalLink(link, filePath) {
  if (
    !link ||
    link.startsWith('#') ||
    /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(link)
  ) {
    return null;
  }

  const pathOnly = link.split(/[?#]/, 1)[0];
  if (!pathOnly) {
    return null;
  }

  let decodedPath;
  try {
    decodedPath = decodeURIComponent(pathOnly);
  } catch {
    decodedPath = pathOnly;
  }

  const targetPath = decodedPath.startsWith('/')
    ? path.resolve(REPO_ROOT, decodedPath.replace(/^[/\\]+/, ''))
    : path.resolve(path.dirname(filePath), decodedPath);
  const candidates = [targetPath];

  if (!path.extname(targetPath)) {
    candidates.push(`${targetPath}.md`);
    candidates.push(path.join(targetPath, 'index.md'));
    candidates.push(path.join(targetPath, 'README.md'));
  }

  return {
    exists: candidates.some(candidate => fs.existsSync(candidate)),
    target: candidates[1] || candidates[0]
  };
}

function checkLinks(content, filePath) {
  const linkRegex = /!?\[([^\]]*)\]\(([^)]+)\)/g;
  const brokenLinks = [];
  let match;

  while ((match = linkRegex.exec(content)) !== null) {
    const link = markdownDestination(match[2]);
    const resolved = resolveInternalLink(link, filePath);
    if (resolved && !resolved.exists) {
      brokenLinks.push({ link, target: resolved.target, file: filePath });
    }
  }

  return brokenLinks;
}

function walkDir(dir, callback) {
  const entries = fs.readdirSync(dir, { withFileTypes: true })
    .sort((left, right) => left.name.localeCompare(right.name));

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      if (!['node_modules', '.git', 'evaluation', 'dist', 'build'].includes(entry.name)) {
        walkDir(fullPath, callback);
      }
    } else if (entry.isFile() && entry.name.toLowerCase().endsWith('.md')) {
      callback(fullPath, entry.name);
    }
  }
}

function main() {
  resetStats();
  log('SStory Frontmatter Validator starting...', 'INFO');

  const allFiles = [];
  walkDir(WORLD_DIR, (filePath, fileName) => allFiles.push({ filePath, fileName }));
  log(`Found ${allFiles.length} markdown files to check`, 'INFO');

  const brokenLinks = [];
  for (const { filePath } of allFiles) {
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      checkFrontmatter(filePath, content);
      brokenLinks.push(...checkLinks(content, filePath));
    } catch (error) {
      log(`Error reading ${filePath}: ${error.message}`, 'ERROR');
      errors++;
    }
  }

  log('=== Validation Summary ===', 'INFO');
  log(`Files checked: ${checked}`, 'INFO');
  log(`Frontmatter errors: ${errors}`, errors > 0 ? 'ERROR' : 'SUCCESS');
  log(`Warnings: ${warnings}`, warnings > 0 ? 'WARN' : 'SUCCESS');

  if (brokenLinks.length > 0) {
    log(`Broken links found: ${brokenLinks.length}`, 'ERROR');
    for (const { link, target, file } of brokenLinks) {
      log(`  ${file}: ${link} -> ${target} (not found)`, 'ERROR');
    }
    errors += brokenLinks.length;
  } else {
    log('Broken links: 0', 'SUCCESS');
  }

  if (errors > 0) {
    log('Validation FAILED', 'ERROR');
    process.exit(1);
  }

  log('Validation PASSED', 'SUCCESS');
}

if (require.main === module) {
  main();
}

module.exports = {
  REQUIRED_FIELDS,
  TYPE_SCHEMA_FILES,
  VALID_TYPES,
  VALID_CATEGORIES,
  VALID_STATUS,
  checkFrontmatter,
  checkLinks,
  createSchemaValidators,
  extractFrontmatter,
  formatSchemaError,
  log,
  main,
  markdownDestination,
  resetStats,
  resolveInternalLink,
  getStats,
  walkDir
};
