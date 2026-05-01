#!/usr/bin/env node

/**
 * SStory Consistency Validator
 * Checks for common data inconsistencies across Markdown files.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', 'world');

// Patterns to check
const CHECKS = [
  {
    name: 'Inconsistent earth spirit name',
    pattern: /ドリト/,
    message: 'Found "ドリト" (should be "グラン")',
    files: ['races/races-overview.md']
  },
  {
    name: 'Duplicate unit kmkm²',
    pattern: /kmkm²/,
    message: 'Found "kmkm²" (should be "km²")',
    files: ['politics/kingdoms.md']
  },
  {
    name: 'AD vs アールディー inconsistency',
    pattern: /\bAD\b/,
    message: 'Found "AD", use "アールディー" instead',
    exclude: []
  },
  {
    name: 'Trailing whitespace',
    pattern: /[ \t]+$/m,
    message: 'Trailing whitespace detected',
    files: []
  }
];

// Check for broken internal links
function checkLinks() {
  const mdFiles = getAllMarkdown(ROOT);
  const linkRegex = /\[.*?\]\((?!http)(.*?\.md)\)/g;
  let errors = [];

  mdFiles.forEach(file => {
    const content = fs.readFileSync(file, 'utf8');
    const dir = path.dirname(file);
    let match;
    while ((match = linkRegex.exec(content)) !== null) {
      const target = match[1];
      const targetPath = path.resolve(dir, target);
      if (!fs.existsSync(targetPath)) {
        errors.push(`${file}: broken link -> ${target}`);
      }
    }
  });
  return errors;
}

// Check naming consistency for key terms
function checkTerms() {
  const files = getAllMarkdown(ROOT);
  const issues = [];

  // Earth spirit must be "グラン" only, not "ドリト"
  files.forEach(file => {
    const content = fs.readFileSync(file, 'utf8');
    if (content.includes('ドリト')) {
      issues.push(`${file}: contains "ドリト" (should be "グラン")`);
    }
  });

  // Year notation: must use アールディー not AD
  files.forEach(file => {
    const content = fs.readFileSync(file, 'utf8');
    if (/\bAD\b/.test(content)) {
      issues.push(`${file}: contains "AD" (use "アールディー")`);
    }
  });

  // Unit typo kmkm²
  files.forEach(file => {
    const content = fs.readFileSync(file, 'utf8');
    if (/kmkm²/.test(content)) {
      issues.push(`${file}: contains "kmkm²" (should be "km²")`);
    }
  });

  return issues;
}

// Get all .md files recursively
function getAllMarkdown(dir) {
  let results = [];
  const list = fs.readdirSync(dir);
  list.forEach(file => {
    const full = path.join(dir, file);
    const stat = fs.statSync(full);
    if (stat.isDirectory()) {
      results = results.concat(getAllMarkdown(full));
    } else if (file.endsWith('.md')) {
      results.push(full);
    }
  });
  return results;
}

// Main
function main() {
  console.log('🔍 SStory Consistency Validator\n');
  console.log(`Checking files under: ${ROOT}\n`);

  let hasErrors = false;

  // Check terms
  console.log('--- Term Consistency ---');
  const termIssues = checkTerms();
  if (termIssues.length > 0) {
    hasErrors = true;
    termIssues.forEach(i => console.log(`❌ ${i}`));
  } else {
    console.log('✅ No term inconsistencies found.');
  }

  // Check links
  console.log('\n--- Link Integrity ---');
  const brokenLinks = checkLinks();
  if (brokenLinks.length > 0) {
    hasErrors = true;
    brokenLinks.forEach(l => console.log(`❌ ${l}`));
  } else {
    console.log('✅ No broken links found.');
  }

  console.log('\n--- Summary ---');
  if (hasErrors) {
    console.log('❌ Validation FAILED. Please fix the above issues.');
    process.exit(1);
  } else {
    console.log('✅ All checks passed.');
    process.exit(0);
  }
}

main();
