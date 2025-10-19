#!/usr/bin/env python
"""xiv - Search and download papers from arXiv"""
import argparse, sys, os, json, re, time, signal
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

__version__ = "1.0.0"

try:
    from urllib.request import urlopen, urlretrieve, Request
    from urllib.parse import urlencode
except ImportError:
    from urllib2 import urlopen, Request
    from urllib import urlencode
    urlretrieve = None

NS = {
    'a': 'http://www.w3.org/2005/Atom',
    'opensearch': 'http://a9.com/-/spec/opensearch/1.1/'
}
SORTS = {'date': 'submittedDate', 'updated': 'lastUpdatedDate', 'relevance': 'relevance'}

DEFAULT_RESULTS = int(os.getenv('XIV_MAX_RESULTS', '10'))
DEFAULT_CATEGORY = os.getenv('XIV_CATEGORY', 'cs.RO')
DEFAULT_SORT = os.getenv('XIV_SORT', 'date')
DEFAULT_PDF_DIR = os.getenv('XIV_PDF_DIR', 'papers')
DEFAULT_DOWNLOAD_DELAY = float(os.getenv('XIV_DOWNLOAD_DELAY', '3.0'))
DEFAULT_RETRY_ATTEMPTS = int(os.getenv('XIV_RETRY_ATTEMPTS', '3'))

def is_retryable_error(error):
    err_str = str(error).lower()
    return any(code in err_str for code in ['503', '502', '504', 'timeout'])

def search(query, max_results=10, sort='submittedDate', since=None, categories=None):
    cat_query = " OR ".join("cat:" + c for c in categories) if categories else "cat:" + DEFAULT_CATEGORY
    search_query = "(%s) AND (%s)" % (cat_query, query)

    xml = None
    for attempt in range(DEFAULT_RETRY_ATTEMPTS):
        try:
            url = "https://export.arxiv.org/api/query?" + urlencode({
                'search_query': search_query, 'start': 0, 'max_results': max_results,
                'sortBy': sort, 'sortOrder': 'descending'
            })
            req = Request(url, headers={'User-Agent': 'xiv/%s' % __version__})
            resp = urlopen(req)
            xml = resp.read().decode('utf-8')
            resp.close()
            break
        except Exception as e:
            if attempt < DEFAULT_RETRY_ATTEMPTS - 1 and is_retryable_error(e):
                wait_time = (2 ** attempt)
                sys.stderr.write("ArXiv unavailable (attempt %d/%d), retrying in %ds... (Ctrl+C to cancel)\n" %
                                (attempt + 1, DEFAULT_RETRY_ATTEMPTS, wait_time))
                try:
                    time.sleep(wait_time)
                except KeyboardInterrupt:
                    sys.stderr.write("\nCancelled.\n")
                    return []
            else:
                sys.stderr.write("Error querying arXiv: %s\n" % e)
                return []

    if not xml:
        return []

    try:
        root = ET.fromstring(xml.encode('utf-8'))
    except:
        root = ET.fromstring(xml)

    papers = []
    for entry in root.findall('a:entry', NS):
        pub = entry.find('a:published', NS).text[:10]
        if since and pub < since:
            continue

        authors = [a.find('a:name', NS).text for a in entry.findall('a:author', NS)]
        auth = ", ".join(authors[:3]) + (" et al. (%d)" % len(authors) if len(authors) > 3 else "")

        papers.append({
            'title': re.sub(r'\s+', ' ', entry.find('a:title', NS).text.strip()),
            'authors': auth,
            'published': pub,
            'link': entry.find('a:id', NS).text,
            'abstract': re.sub(r'\s+', ' ', entry.find('a:summary', NS).text.strip())
        })
    return papers

def is_captcha(path):
    if os.path.getsize(path) >= 100000:
        return False
    with open(path, 'rb') as f:
        content = f.read(1024).lower()
    return b'<html' in content or b'captcha' in content or b'<!doctype' in content

def download(link, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    paper_id = link.split('/')[-1]
    path = os.path.join(output_dir, paper_id.replace('/', '-') + '.pdf')

    sys.stderr.write("  %s... " % paper_id)
    sys.stderr.flush()

    for attempt in range(DEFAULT_RETRY_ATTEMPTS):
        try:
            pdf_url = "https://arxiv.org/pdf/%s.pdf" % paper_id
            req = Request(pdf_url, headers={'User-Agent': 'xiv/%s' % __version__})
            r = urlopen(req)
            with open(path, 'wb') as f:
                f.write(r.read())
            r.close()

            if is_captcha(path):
                os.remove(path)
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
    """Format papers as JSON"""
    print(json.dumps(papers, indent=2, ensure_ascii=False))

def format_compact(papers):
    """Format papers as compact list"""
    w = len(str(len(papers)))
    for i, p in enumerate(papers, 1):
        print("[%s, %s] %s" % (str(i).zfill(w), p['published'], p['title']))

def format_detailed(papers):
    """Format papers with full details"""
    for i, p in enumerate(papers, 1):
        print("\n[%d] %s" % (i, p['title']))
        print("    %s\n    %s | %s\n    %s" % (p['authors'], p['published'], p['link'], p['abstract']))

def download_papers(papers, output_dir):
    """Download all papers with rate limiting and progress tracking"""
    sys.stderr.write("\nDownloading to '%s/'...\n" % output_dir)
    if len(papers) > 1:
        sys.stderr.write("Rate limiting: %.1fs delay between downloads\n" % DEFAULT_DOWNLOAD_DELAY)

    ok = 0
    captcha_count = 0

    for i, p in enumerate(papers, 1):
        sys.stderr.write("[%d/%d] " % (i, len(papers)))
        sys.stderr.flush()
        result = download(p['link'], output_dir)

        if result == 'captcha':
            captcha_count += 1
        elif result:
            ok += 1

        # Delay between downloads to avoid CAPTCHA (except after last)
        if i < len(papers):
            try:
                time.sleep(DEFAULT_DOWNLOAD_DELAY)
            except KeyboardInterrupt:
                sys.stderr.write("\n\nDownload cancelled by user.\n")
                sys.stderr.write("%d/%d saved before cancellation\n" % (ok, len(papers)))
                sys.exit(130)

    # Report results
    sys.stderr.write("\n%d/%d saved" % (ok, len(papers)))
    if captcha_count > 0:
        sys.stderr.write(", %d CAPTCHA blocked\n\n" % captcha_count)
        sys.stderr.write("Rate limit triggered. Try:\n")
        sys.stderr.write("  - Wait a few minutes before retrying\n")
        sys.stderr.write("  - Reduce downloads: -n <number>\n")
        sys.stderr.write("  - Increase delay: XIV_DOWNLOAD_DELAY=5.0\n")
    sys.stderr.write("\n")

def parse_arguments():
    """Parse command line arguments"""
    p = argparse.ArgumentParser(description='xiv', add_help=False,
        formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=30, width=100))

    p.add_argument('query', nargs='?', default='all', help='search query')
    p.add_argument('-n', type=int, metavar='N', help='max results (default: %d, env: XIV_MAX_RESULTS)' % DEFAULT_RESULTS)
    p.add_argument('-c', nargs='+', metavar='CAT', help='categories (default: %s, env: XIV_CATEGORY)' % DEFAULT_CATEGORY)
    p.add_argument('-t', type=int, metavar='DAYS', help='papers from last N days (max results 1000, use -n to limit further)')
    p.add_argument('-s', choices=['date', 'updated', 'relevance'], metavar='SORT',
                   help='sort by: date, updated, relevance (default: %s, env: XIV_SORT)' % DEFAULT_SORT)
    p.add_argument('-d', nargs='?', const=DEFAULT_PDF_DIR, metavar='DIR',
                   help='download PDFs to DIR (default: %s, env: XIV_PDF_DIR)' % DEFAULT_PDF_DIR)
    p.add_argument('-j', action='store_true', help='output as JSON')
    p.add_argument('-l', action='store_true', help='compact list output')
    p.add_argument('-v', '--version', action='version', version='xiv ' + __version__, help='show version')
    p.add_argument('-h', action='help', help='show this help')

    return p.parse_args()

def main():
    args = parse_arguments()

    # Determine search parameters
    since = (datetime.now() - timedelta(days=args.t)).strftime('%Y-%m-%d') if args.t else None
    max_results = args.n if args.n else (1000 if args.t else DEFAULT_RESULTS)
    sort = SORTS.get(args.s or DEFAULT_SORT)

    # Execute search
    papers = search(args.query, max_results, sort, since, args.c)

    if not papers:
        sys.stderr.write("No papers found matching your query.\n")
        sys.exit(1)

    # Display results
    if args.j:
        format_json(papers)
    elif args.l:
        format_compact(papers)
    else:
        format_detailed(papers)

    # Download if requested
    if args.d:
        download_papers(papers, args.d)

if __name__ == "__main__":
    # Ignore SIGPIPE for clean broken pipe handling (Unix/Linux)
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except AttributeError:
        pass  # Windows doesn't have SIGPIPE

    try:
        main()
    except KeyboardInterrupt:
        sys.stderr.write("\n\nInterrupted.\n")
        sys.exit(130)
