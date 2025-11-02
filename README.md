# xiv

[![Tests](https://github.com/james-akl/xiv/actions/workflows/test.yml/badge.svg)](https://github.com/james-akl/xiv/actions/workflows/test.yml)
[![Deploy](https://github.com/james-akl/xiv/actions/workflows/deploy.yml/badge.svg)](https://github.com/james-akl/xiv/actions/workflows/deploy.yml)
[![codecov](https://codecov.io/gh/james-akl/xiv/branch/main/graph/badge.svg)](https://codecov.io/gh/james-akl/xiv)
[![Python](https://img.shields.io/badge/python-2.7%20%7C%203.3--3.14-blue.svg)](https://github.com/james-akl/xiv)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Minimal arXiv search and download tool. Zero external dependencies (Python stdlib only). Requires only a Python interpreter. Written for portability and minimalism, tested on Python 2.7, 3.3–3.14.

## Installation

**Debian/Ubuntu:**
```bash
curl -fsSL https://github.com/james-akl/xiv/releases/latest/download/xiv.deb -o xiv.deb
sudo dpkg -i xiv.deb
```
Uninstall: `sudo dpkg -r xiv` or `sudo apt remove xiv`

**Linux/macOS/WSL:**
```bash
curl -fsSL https://github.com/james-akl/xiv/releases/latest/download/xiv -o xiv
chmod +x xiv
sudo mv xiv /usr/local/bin/
```
Uninstall: `sudo rm /usr/local/bin/xiv`

**Windows (PowerShell):**
```powershell
curl -fsSL https://github.com/james-akl/xiv/releases/latest/download/xiv -o xiv.py

# Create wrapper batch file
@'
@echo off
python "%~dp0xiv.py" %*
'@ | Out-File -FilePath xiv.bat -Encoding ASCII

# Add directory to PATH or move to a directory already in PATH
# Then use: xiv <query>
```
Uninstall: Delete `xiv.py` and `xiv.bat`

## Usage

```bash
xiv                          # Search 10 latest papers in category (default `cs.RO`)
xiv "neural networks" -n 20  # Search 20 latest matches in category (default `cs.RO`)
xiv -h                       # Show help and configuration options
```

## Options

```
query              search query
-n N               max results (default: 10, env: XIV_MAX_RESULTS)
-c CAT [CAT...]    categories (default: cs.RO, env: XIV_CATEGORY)
-t T               papers from last T days (max results 1000, use -n to limit)
-s SORT            sort: date, updated, relevance (default: date, env: XIV_SORT)
-d [ARG...]        download PDFs; accepts: -d (default dir 'papers', env: XIV_PDF_DIR),
                   -d DIR, -d 1,3-5, -d DIR 1,3-5
-j                 output as JSON
-l                 compact list output
-f                 formatted output with color (default: plain, env: XIV_FORMAT)
-e, --env          show environment configuration and exit
-v, --version      show version
-h                 show help
```

## Examples

```bash
# Find recent papers on transformers in AI/ML
xiv "transformer attention" -c cs.AI cs.LG -n 10
# Last week's robotics papers, sorted by relevance
xiv "manipulation grasping" -c cs.RO -t 7 -s relevance
# Computer vision papers from last 30 days, limit to 5
xiv "object detection" -c cs.CV -t 30 -n 5
# Download latest 3 papers on neural ODEs
xiv "neural ode" -n 3 -d papers/
# Download specific papers by index (1st, 3rd, 5th from results)
xiv "transformer attention" -n 20 -d 1,3,5
# Download range of papers (papers 1-5 and 8)
xiv "graph neural networks" -n 20 -d 1-5,8
# Download selective papers to custom directory
xiv "reinforcement learning" -n 20 -d rl_papers/ 2,4-7,10
# Get compact list of recent quantum computing papers
xiv "quantum computing" -c quant-ph -n 20 -l
# Enable formatted/colored output
xiv "machine learning" -f
# Plain output (default, useful for piping)
xiv "deep learning" > papers.txt
# JSON output piped to `jq` for processing
xiv "graph neural networks" -n 10 -j | jq '.[].title'
xiv "reinforcement learning" -n 5 -j | jq -r '.[] | "\(.published) - \(.title)"'
xiv "diffusion models" -n 5 -j | jq -r '.[] | .link' | xargs -I {} firefox {}
# Combine with other tools
xiv "large language models" -n 50 -l | grep -i "reasoning"
xiv "computer vision" -t 7 -l | wc -l  # Count recent CV papers
```

## Environment Variables

Configure defaults via environment variables. All values are validated on startup with clear error messages.

**Linux/macOS:**
```bash
export XIV_MAX_RESULTS=20                # Default number of results (range: 1-2000)
export XIV_CATEGORY='cs.AI cs.CV'        # Default categories
export XIV_SORT=relevance                # Default sort order (date, updated, relevance)
export XIV_FORMAT=1                      # Formatted output: 0=plain, 1=color (default: 0)
export XIV_PDF_DIR=papers                # Download directory
export XIV_DOWNLOAD_DELAY=3.0            # Seconds between downloads (range: 0.0-60.0)
export XIV_RETRY_ATTEMPTS=3              # Retry attempts for failed requests (range: 1-10)
export XIV_MAX_AUTHORS=3                 # Number of authors before "et al." (range: 1-20)
```

For persistence, add to `~/.bashrc`, `~/.zshrc`, or otherwise.

**Windows (PowerShell):**
```powershell
$env:XIV_MAX_RESULTS=20
$env:XIV_CATEGORY="cs.AI cs.CV"
$env:XIV_SORT="relevance"
$env:XIV_FORMAT=1
$env:XIV_PDF_DIR="papers"
$env:XIV_DOWNLOAD_DELAY=3.0
$env:XIV_RETRY_ATTEMPTS=3
$env:XIV_MAX_AUTHORS=3
```

For persistence, use System Properties → Environment Variables.

**View Current Configuration:**
```bash
xiv -e  # Display all settings with validation ranges
```

**Notes:**
- Invalid values trigger warnings and fall back to defaults
- `XIV_DOWNLOAD_DELAY < 3.0` violates API limits and risks blocking
- Category validation is case-insensitive (e.g., `cs.AI`, `cs.ai`, `CS.AI` all valid)
- Unknown categories trigger warnings but don't block execution
- All environment variables are optional

## Testing

Comprehensive test suite with 155 pytest tests covering all functionality:

```bash
# Local testing
pytest                          # Unit tests (mocked, fast)
pytest --integration            # Integration tests (real arXiv API)
pytest -v                       # Verbose with test names
# Multi-version testing
./run_tests.sh                  # Test Python 2.7, 3.3–3.14 (Docker)
./run_tests.sh -v               # Verbose output
./run_tests.sh --integration    # Integration mode across all versions
```

**Test Coverage:**
- **Search function**: API parameters, data validation, filtering, sorting
- **Download function**: PDF retrieval, directory creation, file naming, selective downloads
- **Helper functions**: Error classification, CAPTCHA detection, retry logic, index parsing
- **CLI arguments**: All flags (`-n`, `-c`, `-t`, `-s`, `-d`, `-j`, `-l`, `-f`, `-v`) with selective download combinations
- **Configuration**: Environment variables, constants, defaults, validation with warnings
- **Input validation**: Category format validation, range checks, policy warnings
- **Output formats**: JSON, compact list, standard output, formatted (colored) output
- **Format functionality**: ANSI code application, semantic coloring, et al. handling
- **Edge cases**: Empty results, error handling, exit codes, pipe handling, invalid index specifications

Unit tests use real arXiv response data for accurate mocking and require no network. Integration tests make live API calls. All tests must pass on Python 2.7 and 3.3–3.14.
