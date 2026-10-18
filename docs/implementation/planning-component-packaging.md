# Planning component distribution

`packages/planning-view` is the canonical browser implementation. Assembly uses
Python's standard library and copies identical modules, CSS, frontend HTML,
metadata, documentation and the existing MIT license into:

- `app/presentation/assets/components/gantt/planning-view/`
- `packages/streamlit-planning-view/src/streamlit_planning_view/frontend/`
- An optional independent browser tar archive.

The prepared directories are ignored build products. Edit canonical source,
then prepare; never maintain copied trees separately. The content manifest
records package/contract versions and SHA-256 for every resource. Assembly has
no clocks, machine paths or external URLs. Browser archives use sorted paths and
fixed timestamps/ownership. Source and Python package versions must match;
contract compatibility is separate.

## Prepare and check

From the repository root using Python 3.14:

```bash
python -m scripts.build_planning_assets \
  --browser-archive .local/planning-distributions/planning-view-0.1.0.tar.gz
python -m scripts.build_planning_assets --check
```

`--target eppm` or `--target streamlit` selects one host. `--check` writes
nothing and fails on missing, extra, or stale resources. Preparation refuses
unmanaged files and symlink targets. The manifest owns obsolete generated paths
so source deletions remove only managed assets. No compilation or dependency
installation runs at application startup.

Root editable/wheel/source builds check embedded assets against canonical
source. Root source distributions retain that source and metadata so checks
work without the original checkout. Prepare before root installation. Docker
prepares in its build stage using Python, then copies the tree into its non-root
runtime. CI prepares before installation and checks drift after tests.

## Build Python artifacts

Use a Python 3.14 environment with `setuptools>=80` and `wheel`. These are build
tools, adding no application runtime dependency:

```bash
python -m pip install 'setuptools>=80' wheel
python -m scripts.build_planning_assets
cd packages/streamlit-planning-view
python -c "from setuptools.build_meta import build_sdist, build_wheel; build_sdist('dist'); build_wheel('dist')"
```

The wheel includes all nested frontend resources. The standalone source
distribution contains a prepared frontend and its `build_frontend.py` guard.
Rebuild a wheel from extracted sources without EPPM, source paths, a JavaScript
compiler, or a build-time browser download:

```bash
tar -xzf streamlit_planning_view-0.1.0.tar.gz
cd streamlit_planning_view-0.1.0
python -c "from setuptools.build_meta import build_wheel; build_wheel('dist')"
```

The guard checks required entries, inventory, safe paths, versions and every
checksum. Missing/modified resources fail wheel and source builds. Standalone
sources do not need the repository assembly script. Install either wheel:

```bash
python -m pip install /path/to/streamlit_planning_view-0.1.0-py3-none-any.whl
```

The wrapper README documents full-data/lazy hosts. Browser hosts unpack their
archive, serve it over HTTP, and import `src/index.js`; CSS loads relative to the
installed module. Streamlit consumers need no frontend build. Registry
publication and a separate repository remain outside this change.

## Verification

`tests/test_planning_distributions.py` builds direct/source-rebuilt wheels and
installs them plus the root wheel in temporary targets. It disables source-tree
import resolution and checks every resource against the source manifest. Tests
also check byte-identical repeated archives, failed build guards and browser
rendering from an extracted archive. They use the active Python 3.14 build
tools (included in `.[dev]`), falling back to `python3` on PATH when needed.
`EPPM_BUILD_PYTHON` selects another prepared Python 3.14 interpreter.
Runtime/browser checks retain the pytest interpreter and its Streamlit install.
Installed-consumer interaction tests supplement these packaging checks.
