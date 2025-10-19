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

__version__ = "1.1.0"

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
MAX_AUTHORS_DISPLAYED = 3    # Show first N authors, rest as "et al."
DATE_PREFIX_LENGTH = 10      # YYYY-MM-DD format
MAX_TIME_RESULTS = 1000      # arXiv API limit for time-based queries
EXIT_SIGINT = 130            # POSIX exit code for SIGINT (128 + 2)

DEFAULT_RESULTS = int(os.getenv('XIV_MAX_RESULTS', '10'))
DEFAULT_CATEGORY = os.getenv('XIV_CATEGORY', 'cs.RO')
DEFAULT_SORT = os.getenv('XIV_SORT', 'date')
DEFAULT_PDF_DIR = os.getenv('XIV_PDF_DIR', 'papers')
DEFAULT_DOWNLOAD_DELAY = float(os.getenv('XIV_DOWNLOAD_DELAY', '3.0'))
DEFAULT_RETRY_ATTEMPTS = int(os.getenv('XIV_RETRY_ATTEMPTS', '3'))

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
        auth = ", ".join(authors[:MAX_AUTHORS_DISPLAYED])
        if len(authors) > MAX_AUTHORS_DISPLAYED:
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
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

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
    p.add_argument('-v', '--version', action='version', version='xiv ' + __version__, help='show version')
    p.add_argument('-h', action='help', help='show this help')

    return p.parse_args()

def main():
    args = parse_arguments()

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
