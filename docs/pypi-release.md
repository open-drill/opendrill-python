# PyPI release

The distribution and import package are both `opendrill`. The PyPI project already exists (0.0.1 was a placeholder), so releases go through a trusted publisher attached to that project. No API token is stored in the repository or in CI.

## One-time setup

1. On pypi.org, open the `opendrill` project, then **Settings > Publishing**, and add a GitHub Actions publisher:
   - Owner: `open-drill`
   - Repository name: `opendrill-python`
   - Workflow filename: `publish.yml`
   - Environment name: `pypi`
2. On GitHub, create an environment named `pypi` in `open-drill/opendrill-python` (**Settings > Environments**). Add yourself as a required reviewer if you want a manual approval before each upload.

## Cutting a release

1. Set `version` in `pyproject.toml` and the fallback in `src/opendrill/__init__.py`.
2. Merge to `main` with CI green.
3. Publish a GitHub Release with tag `v<version>`, for example `v0.1.0`.

`.github/workflows/publish.yml` then runs the tests, builds the sdist and wheel, checks that the tag matches `opendrill.__version__`, and uploads to PyPI. PyPI never accepts the same version twice, so a bad release is fixed with a new version, not a re-upload.

## Local build check

```bash
python -m pip install build twine
python -m build
twine check dist/*
python -m venv /tmp/opendrill-check
/tmp/opendrill-check/bin/pip install dist/opendrill-*.whl
/tmp/opendrill-check/bin/opendrill example pdf --out /tmp/synthetic.pdf
```

The wheel `METADATA` should contain `License-Expression: MIT` and `License-File: LICENSE`, and `LICENSE` should be inside both the wheel and the sdist. CI checks this.
