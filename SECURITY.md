# Security Policy

## Supported Versions

Currently, only the latest version of the main branch is supported for security updates.

| Version | Supported          |
|---------|-------------------|
| main    | ✅ Yes            |
| < main  | ❌ No             |

## Reporting a Vulnerability

We take the security of the SStory project seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### **Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via private reporting channels.

## How to Report

### For Security Researchers

Please email your security report to: **<halc8312@github.com>** (or the maintainer's preferred contact if updated)

Include the following information in your report:

1. **Type of issue** (e.g., SQL injection, cross-site scripting, etc.)
2. **Full paths** of source file(s) related to the issue
3. **Step-by-step instructions** to reproduce the issue
4. **Proof-of-concept** code (if applicable)
5. **Impact assessment** – how could an attacker exploit this issue?
6. **Suggested fix** (if you have one)

### Response Timeline

- **Initial response**: within 48 hours
- **Status update**: within 7 days
- **Resolution timeline**: depends on severity and complexity

## Supported File Types

Security reports are accepted for:

- Code in `scripts/`, `.github/workflows/`, and any JavaScript/Node.js files
- Markdown processing vulnerabilities (XSS, injection, etc.)
- Dependency vulnerabilities (via Dependabot also)
- CI/CD pipeline security issues
- Repository configuration issues (CODEOWNERS, actions, etc.)
- Content injection or malicious content issues

## Out of Scope

The following are generally **out of scope** for security reports:

- Content disputes (worldbuilding, lore, etc.) – use GitHub Issues
- License compliance questions – use GitHub Issues
- Style guide violations – use GitHub Issues
- General bug reports – use GitHub Issues
- Feature requests – use GitHub Discussions

## Disclosure Policy

- **Private report**: Vulnerability details will be kept private until a fix is ready
- **Coordinated disclosure**: We will coordinate with the reporter on the public disclosure timeline
- **Credit**: We are happy to credit security researchers who report issues (with permission)

## Security Best Practices for Contributors

1. **Never commit secrets**: Use environment variables or GitHub Secrets for CI
2. **Validate user input**: Any scripts that process markdown or user-provided data must sanitize
3. **Keep dependencies updated**: Run `npm audit` regularly
4. **Review CI actions**: Only use trusted GitHub Actions with pinned versions
5. **Minimal permissions**: Workflows should have minimal access (see `.github/workflows/`)

## Security Updates

Security fixes will be released as patch versions (x.y.Z) and will be noted in the changelog.

## Contact

For security issues only: **<halc8312@github.com>** (replace with actual email if available)

For general questions: Use [GitHub Issues](https://github.com/halc8312/SStory/issues)

---

**Last updated**: 2026-05-02  
**Policy version**: 1.0.0
