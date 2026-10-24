# Security policy

Proctor is a security-relevant tool: teams use it to decide whether to trust a change. If you find a way for a change to **pass proctor in CI while hiding test tampering**, and it's realistic enough to be abused, please report it privately through GitHub's [private vulnerability reporting](https://github.com/nbn07/proctor/security/advisories/new) instead of a public issue.

Ordinary detection gaps (an agent cheat that proctor doesn't recognize yet) are not vulnerabilities. Please open a normal PR with the diff in `tests/fixtures/cheats/`.
