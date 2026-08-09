# Installation

This guide covers installing metaScreener from PyPI or from source on
Windows, macOS, and Linux, with troubleshooting, verification, and
upgrade instructions. The short version of these steps lives in the
[project README](../README.md#installation); this page is the full
reference for anyone who hits a problem with the README quickstart or
needs the optional configuration knobs.

## Prerequisites

### Python 3.10 or later

metaScreener uses standard-library features introduced in Python 3.10
(structural pattern matching, parameterised generics syntax). On
earlier versions the application will fail to import.

Verify your Python version:

```bash
python --version    # Windows / macOS
python3 --version   # Linux / macOS with multiple Pythons
```

If your system Python is older than 3.10, install a newer interpreter
through the official installer
([python.org/downloads](https://www.python.org/downloads/)) or your
platform's package manager. Do not rename or replace the system Python;
use a fresh installation alongside it.

### Tkinter

metaScreener's GUI is built on Tkinter, which is bundled with the
official Python installers on Windows and macOS. On Linux, Tkinter is
distributed as a separate system package and must be installed
explicitly:

```bash
sudo apt-get install python3-tk       # Debian, Ubuntu, Mint
sudo dnf install python3-tkinter      # Fedora, RHEL
sudo pacman -S tk                     # Arch
```

To check whether Tkinter is available:

```bash
python -c "import tkinter; tkinter._test()"
```

If that command opens a small dialog window, Tkinter is correctly
installed. If it raises `ModuleNotFoundError: No module named
'tkinter'`, install the system package above and retry.

### Git

Only required for the install-from-source path. Verify with
`git --version`. Available from
[git-scm.com/downloads](https://git-scm.com/downloads).

### An OpenAI API key

Required for the LLM-using plugins (01 Reference Markers, 03 Criteria
Parser with LLM refinement, 06 EL, 07 IL). Not required for the
deterministic plugins (02 References-of-X, 04 EH, 05 IH) or for
running the test suite. Get a key from
[platform.openai.com/api-keys](https://platform.openai.com/api-keys);
the application reads it from a local `.env` file (see
[Configuration](#configuration) below).

## Option A — Install from PyPI

The simplest path for users who only need the application, not the
source tree:

```bash
pip install metascreener-lars-ulaval
```

After install, launch with:

```bash
python -m metascreener
```

Or, if PyPI scripts are on your PATH:

```bash
metascreener
```

The PyPI distribution bundles everything needed to run, but does not
include the sample inputs under `samples/`, the test suite, the golden
fixtures, or the tooling under `tools/`. The samples exist only in the
repository — clone or download the source to get them. Choose Option B
(install from source) if you intend to follow the documented
walkthroughs, contribute, run the tests, or inspect the audit scripts.

## Option B — Install from source

Use this path if you intend to develop, run tests, or modify
metaScreener.

### Windows

```powershell
# Clone the repository
git clone https://github.com/lars-ulaval/metaScreener.git
cd metaScreener

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure your API key (see Configuration section below)
copy .env.example .env
notepad .env

# Run
python run.py
```

If PowerShell rejects `Activate.ps1` with an execution-policy error,
enable script execution for the current user once with:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### macOS

```bash
# Clone the repository
git clone https://github.com/lars-ulaval/metaScreener.git
cd metaScreener

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure your API key (see Configuration section below)
cp .env.example .env
open -e .env

# Run
python run.py
```

On Apple Silicon, the python3 from python.org installers is universal
(arm64 + x86_64) and works without further configuration. If you
encounter wheel-build errors on `pymupdf` or `pillow`, ensure Xcode
Command Line Tools are installed (`xcode-select --install`).

### Linux (Ubuntu/Debian)

```bash
# Ensure Tkinter is available
sudo apt-get install python3-tk

# Clone the repository
git clone https://github.com/lars-ulaval/metaScreener.git
cd metaScreener

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure your API key (see Configuration section below)
cp .env.example .env
nano .env

# Run
python run.py
```

Other distributions (Fedora, Arch, etc.) follow the same flow with
their respective package managers; the only platform-specific step
is installing Tkinter (see [Prerequisites](#tkinter) above).

## Configuration

metaScreener reads configuration from a `.env` file in the project
root. Copy `.env.example` to `.env` and edit it:

```text
OPENAI_API_KEY=sk-...your-key-here...
```

### Optional environment variables

| Variable           | Default                       | Purpose                                                                                  |
|--------------------|-------------------------------|------------------------------------------------------------------------------------------|
| `OPENAI_API_KEY`   | (required for LLM plugins)    | Authentication for the OpenAI-compatible endpoint.                                       |
| `OPENAI_BASE_URL`  | `https://api.openai.com/v1`   | Override to use an alternative OpenAI-compatible endpoint (Azure OpenAI, local proxy).   |
| `OPENAI_MODEL`     | `gpt-4o-mini` (per plugin)    | Default model identifier. Per-plugin overrides are configurable through the GUI.         |
| `METASCREENER_CACHE_DIR` | `.cache/`               | Location of the per-stage LLM response cache. Use this to share cache across runs.       |

The `.env` file is loaded at application start; changes require a
restart.

### Per-plugin model selection

Each LLM-using plugin (01, 03, 06, 07) has its own model dropdown in
the GUI. Defaults can be overridden per run; the selected model is
recorded in each bundle's `manifest.json` so subsequent runs are
auditable.

## Verifying the installation

### Run the test suite

```bash
python -m pytest tests/ -q
```

Expected: every test passes, with a small number skipped. A few tests skip
themselves when an optional dependency or a display server is unavailable;
that is normal and is not an installation problem.

The count is deliberately not quoted here. It changes with every release,
and a stale number is worse than none — it tells you your install is broken
when it is not. What matters is that nothing **fails** and nothing
**errors**.

If tests fail, the most common causes are (a) a Python version older
than 3.10, (b) a partial install where `pip install -r
requirements.txt` errored on a wheel (re-run with `-v` to see), or
(c) Tkinter not available on Linux. The test failures' tracebacks
usually identify the cause; if not, file an issue with the test
output attached.

### Launch the GUI

```bash
python run.py
```

The main window should open within a few seconds, showing the plugin
list on the left and the empty bundle slot on the right. If the
window does not open, check the terminal for tracebacks; Tkinter
failures are the typical cause on Linux.

### Run a smoke test with the sample corpus

Sample inputs ship with the repository at `samples/` — present in a
source clone or download, but not in a PyPI install. If you installed
via pip (Option A), download the samples from the repository first.
To verify an end-to-end LLM-free pipeline:

1. Launch the GUI.
2. In Plugin 03 (Criteria Parser), load `samples/ic_ec_12.txt`.
   Click Run; review the inferred criteria.
3. In Plugin 02 (References-of-X AI), load
   `samples/ex_ref_2.txt`. Click Run.
4. Pipe the Plugin 02 output through Plugins 04 (EH) and 05 (IH) —
   these are deterministic and require no API key.

If you have an OpenAI key configured, extend the smoke test through
Plugins 06 (EL) and 07 (IL).

## Troubleshooting

### `ModuleNotFoundError: No module named 'tkinter'` (Linux)

Install the Tkinter system package. See [Tkinter](#tkinter) under
Prerequisites.

### `Activate.ps1 cannot be loaded because running scripts is disabled` (Windows)

Run once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

This affects only the current user, not the entire system.

### `pip install` fails on `pymupdf` or `pillow` (macOS)

Install Xcode Command Line Tools:

```bash
xcode-select --install
```

Then retry the install. If it still fails on Apple Silicon, ensure
you are using the python.org universal Python installer (not a
Homebrew-only build).

### `.env` not loaded / API key not recognised

- Confirm the file is named exactly `.env` (with the leading dot)
  and lives in the project root, not in a subdirectory.
- Confirm there is no `OPENAI_API_KEY` in your shell environment
  shadowing the file value.
- Verify the file's first line has no UTF-8 BOM (a stray invisible
  byte from some editors). Save as plain UTF-8.

### `AuthenticationError: Incorrect API key`

The key in `.env` is not accepted by the endpoint. Verify the key on
[platform.openai.com/api-keys](https://platform.openai.com/api-keys);
if the key was generated for a different organisation, switch to the
correct one before regenerating.

### Tests pass but the GUI does not open

Check whether `python -c "import tkinter; tkinter._test()"` opens a
window. If it does but `python run.py` does not, the issue is likely
a Python virtualenv mismatch — confirm the venv is activated and
`which python` (or `where python` on Windows) points inside `.venv/`.

### Cache directory grows unbounded

The LLM-response cache is keyed by content hash and grows over time
as new records are processed. To prune, delete `.cache/` between
runs; the next run will repopulate it.

## Upgrading

### From PyPI

```bash
pip install -U metascreener-lars-ulaval
```

### From source

```bash
cd metaScreener
git pull
pip install -r requirements.txt --upgrade
```

If `requirements.txt` has changed, you may also need to delete and
recreate the virtual environment. Bundle files produced under an
earlier version remain readable as long as the bundle-format major
version is unchanged.

## Uninstalling

### From PyPI

```bash
pip uninstall metascreener-lars-ulaval
```

### From source

Remove the cloned directory:

```bash
cd ..
rm -rf metaScreener
```

The `.env` file lives inside the project directory and is removed
with it; if you used `.env` outside the project tree, delete that
copy too. Cached LLM responses under `.cache/` are also removed
along with the project directory.
