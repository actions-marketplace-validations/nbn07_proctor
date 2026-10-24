# Contributing

Thanks for helping keep coding agents honest.

## The most valuable contribution: a new cheat

If you caught an agent gaming its tests in a way proctor missed:

1. Save the diff as `tests/fixtures/cheats/NN_short_name.diff`.
2. Add a first line `# expect: P0xx` naming the rule that *should* fire. Use a new ID if none fits.
3. Optionally add a `#` comment line saying which agent and task produced it.
4. Open a PR. A failing fixture with no fix is still welcome. It becomes a good-first-issue for someone else.

Please strip proprietary code down to the minimal shape of the trick.

## Adding or changing a rule

- Rules live in `src/proctor/rules.py`. Each one is a function decorated with `@rule(id, slug, severity, title, why)`.
- A rule must be **deterministic** and must point at a specific file and line.
- Every rule must keep `tests/fixtures/honest/` clean. If your rule is noisy on honest changes, add an honest fixture that demonstrates the noise and tune the rule until it passes.
- Run the noise-floor benchmark before and after:
  ```bash
  git clone --filter=blob:none https://github.com/pallets/flask /tmp/flask
  python bench/false_positives.py /tmp/flask --commits 150
  ```
  New **high** findings on human commits need a good reason.
- Regenerate the docs: `python scripts/gen_rules_doc.py > docs/RULES.md`.

Severity guide: **high** means it almost never happens by accident in an agent's diff and always deserves a human look. **medium** means it's often legitimate but worth flagging. **low** is informational.

## Dev setup

```bash
pip install -e . pytest
pytest -q
bash examples/demo.sh
```

Proctor uses only the standard library on Python 3.11+ (plus `tomli` on 3.9–3.10). Please keep it that way.
