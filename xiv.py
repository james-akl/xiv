#!/usr/bin/env python
"""xiv - Search and download papers from arXiv

This code is written for portability across Python 2.7-3.14+.
Style choices are deliberate for compatibility:
- No type hints (Python 2 incompatible)
- No f-strings (Python 2, 3.3-3.5 incompatible)
- Import compatibility blocks for urllib (Python 2/3 differences)
- Explicit exception handling for platform differences (SIGPIPE on Windows)
"""
import argparse, sys, os, json, re, time, signal
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

__version__ = "1.1.1"

# Python 2/3 compatibility for urllib
try:
    from urllib.request import urlopen, Request
    from urllib.parse import urlencode
except ImportError:
    from urllib2 import urlopen, Request
    from urllib import urlencode

NS = {
    'a': 'http://www.w3.org/2005/Atom',
    'opensearch': 'http://a9.com/-/spec/opensearch/1.1/'
}
SORTS = {'date': 'submittedDate', 'updated': 'lastUpdatedDate', 'relevance': 'relevance'}

# Constants
MIN_VALID_PDF_SIZE = 100000  # PDFs are typically >100KB; smaller files are likely CAPTCHA pages
CAPTCHA_CHECK_BYTES = 1024   # Read first 1KB to detect HTML CAPTCHA pages
DATE_PREFIX_LENGTH = 10      # YYYY-MM-DD format
MAX_TIME_RESULTS = 1000      # arXiv API limit for time-based queries
EXIT_SIGINT = 130            # POSIX exit code for SIGINT (128 + 2)

# Safe environment variable parsing with validation
def getenv_int(var, default, min_val=None, max_val=None):
    """Parse integer env var with optional range validation"""
    val_str = os.getenv(var)
    if not val_str:
        return default
    try:
        val = int(val_str)
        if min_val is not None and val < min_val:
            sys.stderr.write("Warning: %s=%d is below minimum %d, using %d\n" % (var, val, min_val, default))
            return default
        if max_val is not None and val > max_val:
            sys.stderr.write("Warning: %s=%d exceeds maximum %d, using %d\n" % (var, val, max_val, default))
            return default
        return val
    except ValueError:
        sys.stderr.write("Warning: %s='%s' is not a valid integer, using default %d\n" % (var, val_str, default))
        return default

def getenv_float(var, default, min_val=None, max_val=None):
    """Parse float env var with optional range validation"""
    val_str = os.getenv(var)
    if not val_str:
        return default
    try:
        val = float(val_str)
        if min_val is not None and val < min_val:
            sys.stderr.write("Warning: %s=%.1f is below minimum %.1f, using %.1f\n" % (var, val, min_val, default))
            return default
        if max_val is not None and val > max_val:
            sys.stderr.write("Warning: %s=%.1f exceeds maximum %.1f, using %.1f\n" % (var, val, max_val, default))
            return default
        return val
    except ValueError:
        sys.stderr.write("Warning: %s='%s' is not a valid number, using default %.1f\n" % (var, val_str, default))
        return default

def getenv_str(var, default, valid_values=None):
    """Parse string env var with optional validation"""
    val = os.getenv(var, default)
    if valid_values and val not in valid_values:
        sys.stderr.write("Warning: %s='%s' is not valid (use: %s), using default '%s'\n" %
                        (var, val, ', '.join(valid_values), default))
        return default
    return val

# Configuration with validation
DEFAULT_RESULTS = getenv_int('XIV_MAX_RESULTS', 10, min_val=1, max_val=2000)
DEFAULT_CATEGORY = os.getenv('XIV_CATEGORY', 'cs.RO')
DEFAULT_SORT = getenv_str('XIV_SORT', 'date', valid_values=['date', 'updated', 'relevance'])
DEFAULT_PDF_DIR = os.getenv('XIV_PDF_DIR', 'papers')
DEFAULT_DOWNLOAD_DELAY = getenv_float('XIV_DOWNLOAD_DELAY', 3.0, min_val=0.0, max_val=60.0)
DEFAULT_RETRY_ATTEMPTS = getenv_int('XIV_RETRY_ATTEMPTS', 3, min_val=1, max_val=10)
DEFAULT_MAX_AUTHORS = getenv_int('XIV_MAX_AUTHORS', 3, min_val=1, max_val=20)

# Known arXiv categories (updated 2025-10-26)
ARXIV_CATEGORIES = {
    'cs.AI', 'cs.AR', 'cs.CC', 'cs.CE', 'cs.CG', 'cs.CL', 'cs.CR', 'cs.CV', 'cs.CY', 'cs.DB',
    'cs.DC', 'cs.DL', 'cs.DM', 'cs.DS', 'cs.ET', 'cs.FL', 'cs.GL', 'cs.GR', 'cs.GT', 'cs.HC',
    'cs.IR', 'cs.IT', 'cs.LG', 'cs.LO', 'cs.MA', 'cs.MM', 'cs.MS', 'cs.NA', 'cs.NE', 'cs.NI',
    'cs.OH', 'cs.OS', 'cs.PF', 'cs.PL', 'cs.RO', 'cs.SC', 'cs.SD', 'cs.SE', 'cs.SI', 'cs.SY',
    'econ.EM', 'econ.GN', 'econ.TH', 'eess.AS', 'eess.IV', 'eess.SP', 'eess.SY',
    'math.AC', 'math.AG', 'math.AP', 'math.AT', 'math.CA', 'math.CO', 'math.CT', 'math.CV',
    'math.DG', 'math.DS', 'math.FA', 'math.GM', 'math.GN', 'math.GR', 'math.GT', 'math.HO',
    'math.IT', 'math.KT', 'math.LO', 'math.MG', 'math.MP', 'math.NA', 'math.NT', 'math.OA',
    'math.OC', 'math.PR', 'math.QA', 'math.RA', 'math.RT', 'math.SG', 'math.SP', 'math.ST',
    'astro-ph', 'astro-ph.CO', 'astro-ph.EP', 'astro-ph.GA', 'astro-ph.HE', 'astro-ph.IM', 'astro-ph.SR',
    'cond-mat.dis-nn', 'cond-mat.mes-hall', 'cond-mat.mtrl-sci', 'cond-mat.other',
    'cond-mat.quant-gas', 'cond-mat.soft', 'cond-mat.stat-mech', 'cond-mat.str-el', 'cond-mat.supr-con',
    'gr-qc', 'hep-ex', 'hep-lat', 'hep-ph', 'hep-th', 'math-ph', 'nlin.AO', 'nlin.CD', 'nlin.CG',
    'nlin.PS', 'nlin.SI', 'nucl-ex', 'nucl-th', 'physics.acc-ph', 'physics.ao-ph', 'physics.app-ph',
    'physics.atm-clus', 'physics.atom-ph', 'physics.bio-ph', 'physics.chem-ph', 'physics.class-ph',
    'physics.comp-ph', 'physics.data-an', 'physics.ed-ph', 'physics.flu-dyn', 'physics.gen-ph',
    'physics.geo-ph', 'physics.hist-ph', 'physics.ins-det', 'physics.med-ph', 'physics.optics',
    'physics.plasm-ph', 'physics.pop-ph', 'physics.soc-ph', 'physics.space-ph', 'quant-ph',
    'q-bio.BM', 'q-bio.CB', 'q-bio.GN', 'q-bio.MN', 'q-bio.NC', 'q-bio.OT', 'q-bio.PE', 'q-bio.QM',
    'q-bio.SC', 'q-bio.TO', 'q-fin.CP', 'q-fin.EC', 'q-fin.GN', 'q-fin.MF', 'q-fin.PM', 'q-fin.PR',
    'q-fin.RM', 'q-fin.ST', 'q-fin.TR', 'stat.AP', 'stat.CO', 'stat.ME', 'stat.ML', 'stat.OT', 'stat.TH'
}

def validate_category(cat, source=''):
    """Check if category is known to arXiv. Returns True if valid, warns if unknown."""
    cat = cat.strip()
    if cat in ARXIV_CATEGORIES:
        return True
    # Warn but allow unknown categories (may be new or archive-level)
    src = (" (%s)" % source) if source else ''
    sys.stderr.write("Warning: Unrecognized category '%s'%s - may be new or invalid\n" % (cat, src))
    return True

if os.getenv('XIV_CATEGORY'):
    for cat in DEFAULT_CATEGORY.split():
        validate_category(cat, 'XIV_CATEGORY')

# Warn about potential arXiv policy violations
if DEFAULT_DOWNLOAD_DELAY < 3.0 and os.getenv('XIV_DOWNLOAD_DELAY'):
    sys.stderr.write("Warning: XIV_DOWNLOAD_DELAY < 3.0 violates API limits and risks blocking\n")

def is_retryable_error(error):
    err_str = str(error).lower()
    return any(code in err_str for code in ['503', '502', '504', 'timeout'])

def retry_with_backoff(operation, error_msg_prefix):
    """Execute operation with exponential backoff retry logic"""
    for attempt in range(DEFAULT_RETRY_ATTEMPTS):
        try:
            return operation()
        except Exception as e:
            if attempt < DEFAULT_RETRY_ATTEMPTS - 1 and is_retryable_error(e):
                wait_time = (2 ** attempt)
                sys.stderr.write("%s (attempt %d/%d), retrying in %ds... (Ctrl+C to cancel)\n" %
                                (error_msg_prefix, attempt + 1, DEFAULT_RETRY_ATTEMPTS, wait_time))
                try:
                    time.sleep(wait_time)
                except KeyboardInterrupt:
                    sys.stderr.write("\nCancelled.\n")
                    return None
            else:
                sys.stderr.write("Error: %s\n" % e)
                return None
    return None

def search(query, max_results=10, sort='submittedDate', since=None, categories=None):
    """Query arXiv API and return list of matching papers"""
    cat_query = " OR ".join("cat:" + c for c in categories) if categories else "cat:" + DEFAULT_CATEGORY
    search_query = "(%s) AND (%s)" % (cat_query, query)

    def fetch_xml():
        url = "https://export.arxiv.org/api/query?" + urlencode({
            'search_query': search_query, 'start': 0, 'max_results': max_results,
            'sortBy': sort, 'sortOrder': 'descending'
        })
        req = Request(url, headers={'User-Agent': 'xiv/%s' % __version__})
        resp = urlopen(req)
        xml = resp.read().decode('utf-8')
        resp.close()
        return xml

    xml = retry_with_backoff(fetch_xml, "ArXiv unavailable")
    if not xml:
        return []

    # Handle Python 2/3 encoding differences
    try:
        root = ET.fromstring(xml.encode('utf-8'))
    except (UnicodeDecodeError, ET.ParseError):
        root = ET.fromstring(xml)

    papers = []
    for entry in root.findall('a:entry', NS):
        pub = entry.find('a:published', NS).text[:DATE_PREFIX_LENGTH]
        if since and pub < since:
            continue

        authors = [a.find('a:name', NS).text for a in entry.findall('a:author', NS)]
        auth = ", ".join(authors[:DEFAULT_MAX_AUTHORS])
        if len(authors) > DEFAULT_MAX_AUTHORS:
            auth += " et al. (%d)" % len(authors)

        papers.append({
            'title': re.sub(r'\s+', ' ', entry.find('a:title', NS).text.strip()),
            'authors': auth,
            'published': pub,
            'link': entry.find('a:id', NS).text,
            'abstract': re.sub(r'\s+', ' ', entry.find('a:summary', NS).text.strip())
        })
    return papers

def is_captcha(path):
    """Detect if downloaded file is HTML CAPTCHA page instead of PDF"""
    if os.path.getsize(path) >= MIN_VALID_PDF_SIZE:
        return False
    with open(path, 'rb') as f:
        content = f.read(CAPTCHA_CHECK_BYTES).lower()
    return b'<html' in content or b'captcha' in content or b'<!doctype' in content

def download(link, output_dir):
    """Download single paper PDF with retry logic. Returns True, False, or 'captcha'"""
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
    except (OSError, IOError) as e:
        sys.stderr.write("Error: Cannot create directory '%s': %s\n" % (output_dir, e))
        return False

    paper_id = link.split('/')[-1]
    path = os.path.join(output_dir, paper_id.replace('/', '-') + '.pdf')

    sys.stderr.write("  %s... " % paper_id)
    sys.stderr.flush()

    def fetch_pdf():
        pdf_url = "https://arxiv.org/pdf/%s.pdf" % paper_id
        req = Request(pdf_url, headers={'User-Agent': 'xiv/%s' % __version__})
        r = urlopen(req)
        with open(path, 'wb') as f:
            f.write(r.read())
        r.close()

        if is_captcha(path):
            os.remove(path)
            return 'captcha'
        return True

    for attempt in range(DEFAULT_RETRY_ATTEMPTS):
        try:
            result = fetch_pdf()
            if result == 'captcha':
                sys.stderr.write("CAPTCHA\n")
                return 'captcha'
            sys.stderr.write("OK\n")
            return True
        except Exception as e:
            if os.path.exists(path):
                os.remove(path)

            if attempt < DEFAULT_RETRY_ATTEMPTS - 1 and is_retryable_error(e):
                wait_time = (2 ** attempt)
                sys.stderr.write("retry %ds... " % wait_time)
                sys.stderr.flush()
                try:
                    time.sleep(wait_time)
                except KeyboardInterrupt:
                    sys.stderr.write("cancelled\n")
                    return False
            else:
                sys.stderr.write("Err\n")
                return False

def format_json(papers):
    print(json.dumps(papers, indent=2, ensure_ascii=False))

def format_compact(papers):
    w = len(str(len(papers)))
    for i, p in enumerate(papers, 1):
        print("[%s, %s] %s" % (str(i).zfill(w), p['published'], p['title']))

def format_detailed(papers):
    for i, p in enumerate(papers, 1):
        print("\n[%d] %s" % (i, p['title']))
        print("    %s\n    %s | %s\n    %s" % (p['authors'], p['published'], p['link'], p['abstract']))

def parse_indices(spec, total):
    """Parse index specification like '1,3-5,8' into list of 0-based indices.

    Returns list of valid indices or None if spec is invalid.
    Examples: '1,3,5' -> [0,2,4], '1-3' -> [0,1,2], '1,3-5,8' -> [0,2,3,4,7]
    """
    if not spec:
        return None

    indices = set()
    try:
        for part in spec.split(','):
            part = part.strip()
            if '-' in part:
                start, end = part.split('-', 1)
                start_idx = int(start) - 1
                end_idx = int(end) - 1
                if start_idx < 0 or end_idx >= total or start_idx > end_idx:
                    return None
                indices.update(range(start_idx, end_idx + 1))
            else:
                idx = int(part) - 1
                if idx < 0 or idx >= total:
                    return None
                indices.add(idx)
        return sorted(list(indices))
    except (ValueError, AttributeError):
        return None

def download_papers(papers, output_dir, indices=None):
    """Download papers to output_dir, optionally filtering by indices (0-based)"""
    selected_papers = [papers[i] for i in indices] if indices else papers

    sys.stderr.write("\nDownloading to '%s/'...\n" % output_dir)
    if len(selected_papers) > 1:
        sys.stderr.write("Rate limiting: %.1fs delay between downloads\n" % DEFAULT_DOWNLOAD_DELAY)

    ok = 0
    captcha_count = 0

    for i, p in enumerate(selected_papers, 1):
        sys.stderr.write("[%d/%d] " % (i, len(selected_papers)))
        sys.stderr.flush()
        result = download(p['link'], output_dir)

        if result == 'captcha':
            captcha_count += 1
        elif result:
            ok += 1

        if i < len(selected_papers):
            try:
                time.sleep(DEFAULT_DOWNLOAD_DELAY)
            except KeyboardInterrupt:
                sys.stderr.write("\n\nDownload cancelled by user.\n")
                sys.stderr.write("%d/%d saved before cancellation\n" % (ok, len(selected_papers)))
                sys.exit(EXIT_SIGINT)

    sys.stderr.write("\n%d/%d saved" % (ok, len(selected_papers)))
    if captcha_count > 0:
        sys.stderr.write(", %d CAPTCHA blocked\n\n" % captcha_count)
        sys.stderr.write("Rate limit triggered. Try:\n")
        sys.stderr.write("  - Wait a few minutes before retrying\n")
        sys.stderr.write("  - Reduce downloads: -n <number>\n")
        sys.stderr.write("  - Increase delay: XIV_DOWNLOAD_DELAY=5.0\n")
    sys.stderr.write("\n")

def show_config():
    """Display current configuration and exit"""
    print("Configuration:")
    print("")
    print("  XIV_MAX_RESULTS     = %-10s  %s" % (DEFAULT_RESULTS,
          "(default)" if not os.getenv('XIV_MAX_RESULTS') else ""))
    print("  XIV_CATEGORY        = %-10s  %s" % (DEFAULT_CATEGORY,
          "(default)" if not os.getenv('XIV_CATEGORY') else ""))
    print("  XIV_SORT            = %-10s  %s" % (DEFAULT_SORT,
          "(default)" if not os.getenv('XIV_SORT') else ""))
    print("  XIV_PDF_DIR         = %-10s  %s" % (DEFAULT_PDF_DIR,
          "(default)" if not os.getenv('XIV_PDF_DIR') else ""))
    print("  XIV_DOWNLOAD_DELAY  = %-10s  %s" % (DEFAULT_DOWNLOAD_DELAY,
          "(default)" if not os.getenv('XIV_DOWNLOAD_DELAY') else ""))
    print("  XIV_RETRY_ATTEMPTS  = %-10s  %s" % (DEFAULT_RETRY_ATTEMPTS,
          "(default)" if not os.getenv('XIV_RETRY_ATTEMPTS') else ""))
    print("  XIV_MAX_AUTHORS     = %-10s  %s" % (DEFAULT_MAX_AUTHORS,
          "(default)" if not os.getenv('XIV_MAX_AUTHORS') else ""))
    print("")
    print("Constraints:")
    print("")
    print("  XIV_MAX_RESULTS     1-2000")
    print("  XIV_SORT            date | updated | relevance")
    print("  XIV_DOWNLOAD_DELAY  0.0-60.0  (< 3.0 violates API limits, risks blocking)")
    print("  XIV_RETRY_ATTEMPTS  1-10")
    print("  XIV_MAX_AUTHORS     1-20")
    sys.exit(0)

def validate_download_dir(output_dir, source=''):
    """Validate directory can be created/written. Exits on error."""
    abs_dir = os.path.abspath(output_dir)
    parent = os.path.dirname(abs_dir) or '.'
    src = (" (%s)" % source) if source else ''
    if not os.path.exists(parent):
        sys.stderr.write("Error: Parent directory does not exist%s: %s\n" % (src, parent))
        sys.exit(1)
    if not os.access(parent, os.W_OK):
        sys.stderr.write("Error: No write permission%s for: %s\n" % (src, parent))
        sys.exit(1)

def parse_download_args(args, num_papers):
    """Parse -d arguments and return (output_dir, indices).

    Returns (None, None) if -d not specified.
    Exits with error if invalid.
    """
    if args is None:
        return None, None

    output_dir = DEFAULT_PDF_DIR
    indices_spec = None

    if len(args) == 0:
        pass  # -d alone: defaults
    elif len(args) == 1:
        # Could be DIR or INDICES - check if it looks like indices
        if re.match(r'^[\d,\-\s]+$', args[0]):
            indices_spec = args[0]
        else:
            output_dir = args[0]
    elif len(args) == 2:
        output_dir, indices_spec = args[0], args[1]
    else:
        sys.stderr.write("Error: -d accepts at most 2 arguments (DIR and INDICES)\n")
        sys.exit(1)

    validate_download_dir(output_dir, '-d')

    indices = None
    if indices_spec:
        indices = parse_indices(indices_spec, num_papers)
        if indices is None:
            sys.stderr.write("Error: Invalid index specification '%s'\n" % indices_spec)
            sys.stderr.write("Use format like: 1,3,5 or 1-5 or 1,3-5,8\n")
            sys.stderr.write("Valid range: 1-%d\n" % num_papers)
            sys.exit(1)

    return output_dir, indices

def parse_arguments():
    p = argparse.ArgumentParser(description='xiv', add_help=False,
        formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=30, width=100))

    p.add_argument('query', nargs='?', default='all', help='search query')
    p.add_argument('-n', type=int, metavar='N', help='max results (default: %d, env: XIV_MAX_RESULTS)' % DEFAULT_RESULTS)
    p.add_argument('-c', nargs='+', metavar='CAT', help='categories (default: %s, env: XIV_CATEGORY)' % DEFAULT_CATEGORY)
    p.add_argument('-t', type=int, metavar='T', help='papers from last T days (max results %d, use -n to limit further)' % MAX_TIME_RESULTS)
    p.add_argument('-s', choices=['date', 'updated', 'relevance'], metavar='SORT',
                   help='sort by: date, updated, relevance (default: %s, env: XIV_SORT)' % DEFAULT_SORT)
    p.add_argument('-d', nargs='*', metavar='ARG',
                   help='download PDFs; accepts: -d (default dir \'papers\', env: XIV_PDF_DIR), -d DIR, -d 1,3-5, -d DIR 1,3-5')
    p.add_argument('-j', action='store_true', help='output as JSON')
    p.add_argument('-l', action='store_true', help='compact list output')
    p.add_argument('-e', '--env', action='store_true', help='show environment configuration and exit')
    p.add_argument('-v', '--version', action='version', version='xiv ' + __version__, help='show version')
    p.add_argument('-h', action='help', help='show this help')

    return p.parse_args()

def main():
    args = parse_arguments()

    # Handle -e/--env flag
    if args.env:
        show_config()

    # Validate CLI arguments
    if args.n is not None and args.n < 1:
        sys.stderr.write("Error: -n must be at least 1\n")
        sys.exit(1)
    if args.n is not None and args.n > 2000:
        sys.stderr.write("Warning: -n > 2000 may be excessive; arXiv may limit results\n")
    if args.t is not None and args.t < 1:
        sys.stderr.write("Error: -t must be at least 1\n")
        sys.exit(1)

    # Validate categories (warns for unknown, doesn't block)
    if args.c:
        for cat in args.c:
            validate_category(cat, '-c')

    # Early directory validation (before expensive search)
    if args.d is not None:
        # Extract directory from args (could be DIR or INDICES in first arg)
        dir_to_validate = DEFAULT_PDF_DIR
        if args.d and not re.match(r'^[\d,\-\s]+$', args.d[0]):
            dir_to_validate = args.d[0]
        validate_download_dir(dir_to_validate, '-d')

    since = (datetime.now() - timedelta(days=args.t)).strftime('%Y-%m-%d') if args.t else None
    max_results = args.n if args.n else (MAX_TIME_RESULTS if args.t else DEFAULT_RESULTS)
    sort = SORTS.get(args.s or DEFAULT_SORT)

    papers = search(args.query, max_results, sort, since, args.c)

    if not papers:
        sys.stderr.write("No papers found matching your query.\n")
        sys.exit(1)

    if args.j:
        format_json(papers)
    elif args.l:
        format_compact(papers)
    else:
        format_detailed(papers)

    output_dir, indices = parse_download_args(args.d, len(papers))
    if output_dir:
        download_papers(papers, output_dir, indices)

if __name__ == "__main__":
    # Restore default SIGPIPE to avoid traceback on broken pipes
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except AttributeError:
        pass  # Windows doesn't have SIGPIPE

    try:
        main()
    except KeyboardInterrupt:
        sys.stderr.write("\n\nInterrupted.\n")
        sys.exit(EXIT_SIGINT)
