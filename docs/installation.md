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
metascreener
```

That console script is installed on your PATH by pip. (There is no
`python -m metascreener` entry point; the package ships no `__main__`
module.)

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

metaScreener asks which model provider to use the first time it runs, and
remembers the answer. You do not have to edit any file to get started.

### Where settings are stored

| Platform | Location |
|---|---|
| Windows | `%APPDATA%\metaScreener\settings.json` |
| macOS / Linux | `$XDG_CONFIG_HOME/metaScreener/settings.json`, or `~/.config/metaScreener/settings.json` |

That directory is used rather than the project folder because it survives
reinstalling, and because the packaged Windows build unpacks itself into a
temporary directory that is deleted when the application exits — anything
written beside the executable is lost on close.

The file holds your provider choice, endpoint, model and API key, with an
optional per-stage override. It is written only by metaScreener; you may
edit it by hand, and a file that cannot be parsed is reported and left
alone rather than overwritten.

### Which models are offered for download

When a local server is running with no models installed, metaScreener
offers to pull one. What it offers is data, not code:

```text
plugins/_common/recommended_models.json
```

Edit that file to change the list. A copy placed in your settings
directory — `recommended_models.json` beside `settings.json` — takes
precedence and survives reinstalling. Each entry carries a name, an
approximate size and a note; the size is shown before any download
starts, and the download can be cancelled at any point.

metaScreener makes no claim about how well any listed model screens. That
requires a measurement that has not been made.

### `.env` and environment variables

A `.env` file in the project root is still **read** at start-up, and
environment variables still work, so an existing source-tree setup keeps
working. Neither is written to any more. A stored provider choice takes
precedence over `OPENAI_BASE_URL`, so that changing the endpoint in the
interface is not silently overridden by a leftover shell export.

| Variable           | Default                       | Purpose                                                                                  |
|--------------------|-------------------------------|------------------------------------------------------------------------------------------|
| `OPENAI_API_KEY`   | (required for hosted providers) | Authentication. A local server needs none, and metaScreener no longer asks you to invent a placeholder for one. |
| `OPENAI_BASE_URL`  | `https://api.openai.com/v1`   | Endpoint, when nothing is stored. |
| `OPENAI_MODEL`     | `gpt-4o` | Model identifier for **Plugin 01 only** (the experimental reference extractor). The EL and IL screening stages do not read it. |
| `SCREENA_EL_MODEL` | `gpt-4o-mini`                 | Default model for the EL stage. `SCREENA_IL_MODEL` does the same for IL.                 |

### Per-plugin model selection

Each LLM-using plugin (01, 03, 06, 07) has its own model field in the
GUI. For plugins 03, 06 and 07 it is an **editable combobox**: it is
filled with whatever your endpoint reports through `/v1/models`, and you
can still type a name that is not on the list. It is deliberately not a
read-only dropdown — llama.cpp ignores the model field entirely, and a
server that will not enumerate its models would otherwise leave you
unable to name one. Nothing validates the string.

If the list call fails, times out, or returns nothing, the field is
still usable and the run is still allowed to start; a line under the
field says which of the three happened. Discovery is an aid, never a
gate.

Stages 06 and 07 also carry their own **Endpoint** field, which
overrides the application-level endpoint for that stage alone, with a
line beneath naming which source the current value came from. A stage
whose endpoint points at a billing host always requires an API key,
whatever the provider is set to.

The model, the resolved endpoint, the temperature, the prompt version,
the truncation limit, the batch size and the context window the run was
budgeted against (the `context_window` setting — see the usage guide's
"The context window") **are** recorded in the bundle's `manifest.json`,
once per stage run, in the `provenance` block of the run-history entry.
Whether that run was permitted to exclude is recorded beside it, as
`exclusion_policy`. Two limits are worth knowing: the record is per run
rather than per decision, and a bundle whose stage ran more than once
carries one entry per run.

**What is *not* recorded, and it matters for a local run.** The block
does not carry the model's quantisation, and the recorded window is the
one metaScreener *checked against*, not necessarily the one the server
*served* — metaScreener never sets `num_ctx`, so a local run is served
whatever window the server was started with (F-154). A local model's
name in this block also does not fully identify what produced the
result: `llama3.2:latest` is a **mutable tag**, naming whatever weights
it pointed at on the day. For a run you intend to cite, record the
quantisation and the server's actual window yourself alongside the
bundle.

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
To verify an end-to-end pipeline **entirely offline** — no API key, no
network, using only files that ship with the repository:

1. Launch the GUI.
2. In **Plugin 03 (Criteria Parser)**:
   - **Load TXT/RTF…** → `samples/20260122_1654_sampleIcEc.txt`, and review the inferred
     criteria;
   - **Load A CSV…** → `samples/20260122_1654_aggregate.csv`. Both
     harmonise buttons need this corpus, and neither is enabled without
     it;
   - click **Harmonise (no-LLM)**. Take care to pick that one and not
     **Harmonise + LLM** beside it, which calls a model and, on an OpenAI
     key, spends money;
   - click **Export bundle…** and save the bundle ZIP.
3. In **Plugin 04 (EH)**, load the bundle you just exported and click
   **Run**. Then export its bundle.
4. In **Plugin 05 (IH)**, load Plugin 04's bundle and click **Run**.

Plugins 04 and 05 are deterministic: they need no API key and no model of
any kind.

Two notes on what this route deliberately avoids.

**Plugin 04's input is a bundle ZIP, and only Plugin 03 produces one.**
There is no path from Plugin 02's output directly into Plugin 04.

**Plugin 02 (References-of-X AI) is not part of this route, because it is
network-dependent.** It resolves metadata and fetches references from
external bibliographic services, so although it uses no LLM and costs
nothing, it is *un-billed* rather than *offline* and will not work without
an internet connection. Neither of its two actions is called "Run" —
they are **Resolve Metadata** and **Fetch References**.

If you have an LLM provider configured, extend the smoke test through
Plugins 06 (EL) and 07 (IL). A local model works for these; see
[Configuration](#configuration).

**Expect zero exclusions on a local model, and do not read that as a
failure.** metaScreener runs **flag-only** by default on a `local` or
`custom` provider: the model reads every record and may flag it, but may
not remove it. A smoke run will therefore show records marked
`EXCLUSION_SUPPRESSED` or flagged for review and **none** marked `OUT`.
That is the stage working. The run summary line reports the suppressed
count, the provider dialog can permit exclusion for presence-justified
removals (an absence-justified removal — `not_meet` on an inclusion
criterion — is never applied automatically, whatever the setting), and
the measurement behind the default is in [LLM
evaluation](llm-evaluation.md#local-models-on-this-corpus-a-direct-measurement).

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

### The LLM cache grows over time

The LLM-response cache is keyed by content hash and grows as new
records and new criterion wordings are processed. It is not a
directory on disk — it travels inside the bundle, as
`cache/EL_cache.jsonl` and `cache/IL_cache.jsonl` — so it grows the
bundle rather than your working tree, and nothing prunes it. To start
a stage fresh, untick **Use cache** before running it.

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
copy too. Cached LLM responses live inside your exported bundle ZIPs,
not in the project directory, so removing the project does not remove
them.
