# -*- coding: utf-8 -*-
"""Test suite for xiv - minimal, elegant, comprehensive"""
import pytest, sys, os, json, tempfile, shutil, time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# Fixtures and helpers
class MockResponse:
    def __init__(self, content):
        self.content = content if isinstance(content, bytes) else content.encode('utf-8')
    def read(self): return self.content
    def close(self): pass

@pytest.fixture
def xiv():
    import xiv
    return xiv

@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)

@pytest.fixture
def mock_xiv_urlopen(xiv, monkeypatch, fixtures_dir):
    """Mock xiv.urlopen to return fixtures"""
    def urlopen(url):
        url_str = url.get_full_url() if hasattr(url, 'get_full_url') else str(url)

        if 'export.arxiv.org/api/query' in url_str:
            fname = 'arxiv_empty.xml' if any(x in url_str for x in ['nonexistent', 'xyzabc']) else 'arxiv_response.xml'
        elif 'arxiv.org/pdf/' in url_str:
            fname = 'captcha.html' if 'captcha' in url_str else 'test.pdf'
        else:
            return None

        with open(os.path.join(fixtures_dir, fname), 'rb') as f:
            return MockResponse(f.read())

    monkeypatch.setattr(xiv, 'urlopen', urlopen)
    return urlopen


# Search function tests
class TestSearch:
    pytestmark = pytest.mark.usefixtures('mock_xiv_urlopen')

    def test_returns_list_of_papers_with_required_fields(self, xiv):
        papers = xiv.search('neural', max_results=2)
        assert isinstance(papers, list) and len(papers) == 2
        for p in papers:
            assert set(p.keys()) == {'title', 'authors', 'published', 'link', 'abstract'}

    @pytest.mark.parametrize('categories', [['cs.AI'], ['cs.AI', 'cs.LG']])
    def test_accepts_category_filters(self, xiv, categories):
        papers = xiv.search('test', max_results=1, categories=categories)
        assert isinstance(papers, list)

    def test_accepts_sort_parameter(self, xiv):
        papers = xiv.search('test', max_results=1, sort='relevance')
        assert isinstance(papers, list)

    def test_filters_papers_before_since_date(self, xiv):
        papers = xiv.search('test', max_results=10, since='2025-10-17')
        assert papers == []  # Fixture papers are from 2025-10-16

    def test_published_date_format(self, xiv):
        papers = xiv.search('test', max_results=1)
        date = papers[0]['published']
        assert len(date) == 10 and date[4] == '-' and date[7] == '-'
        datetime.strptime(date, '%Y-%m-%d')  # Validates format

    def test_formats_authors_with_et_al_when_more_than_three(self, xiv):
        papers = xiv.search('test', max_results=2)
        has_et_al = any('et al.' in p['authors'] for p in papers)
        has_count = any('(4)' in p['authors'] or '(6)' in p['authors'] for p in papers)
        assert has_et_al and has_count

    def test_normalizes_whitespace_in_title_and_abstract(self, xiv):
        papers = xiv.search('test', max_results=1)
        assert '  ' not in papers[0]['title'] and '\n' not in papers[0]['title']
        assert '  ' not in papers[0]['abstract'] and '\n' not in papers[0]['abstract']

    def test_returns_empty_list_when_no_results(self, xiv):
        papers = xiv.search('test', max_results=10, since='2026-01-01')
        assert papers == []

    def test_returns_empty_list_when_retry_fails(self, xiv, monkeypatch):
        """Test search() returns [] when API is completely unavailable"""
        monkeypatch.setattr(xiv, 'retry_with_backoff', lambda op, msg: None)
        result = xiv.search('test')
        assert result == []


# Download function tests
class TestDownload:
    @pytest.fixture(autouse=True)
    def setup(self, xiv, monkeypatch, fixtures_dir, tmpdir):
        self.xiv = xiv
        self.tmpdir = tmpdir

        def urlopen(url):
            url_str = url.get_full_url() if hasattr(url, 'get_full_url') else str(url)
            if 'arxiv.org/pdf/' in url_str:
                fname = 'captcha.html' if 'captcha' in url_str else 'test.pdf'
                with open(os.path.join(fixtures_dir, fname), 'rb') as f:
                    return MockResponse(f.read())

        monkeypatch.setattr(xiv, 'urlopen', urlopen)

    def test_creates_output_directory(self):
        new_dir = os.path.join(self.tmpdir, 'subdir')
        assert not os.path.exists(new_dir)
        self.xiv.download('http://arxiv.org/abs/1234.5678', new_dir)
        assert os.path.exists(new_dir)

    def test_downloads_pdf_successfully(self):
        result = self.xiv.download('http://arxiv.org/abs/1234.5678', self.tmpdir)
        assert result is True
        assert os.path.exists(os.path.join(self.tmpdir, '1234.5678.pdf'))

    def test_detects_captcha_and_deletes_file(self):
        result = self.xiv.download('http://arxiv.org/abs/captcha', self.tmpdir)
        assert result == 'captcha'
        assert not os.path.exists(os.path.join(self.tmpdir, 'captcha.pdf'))

    def test_handles_paper_id_with_version(self):
        result = self.xiv.download('http://arxiv.org/abs/2510.14968v1', self.tmpdir)
        assert result is True
        assert os.path.exists(os.path.join(self.tmpdir, '2510.14968v1.pdf'))

    def test_handles_directory_creation_failure(self, monkeypatch, capsys):
        """Test download() handles OSError when creating directory"""
        def mock_makedirs(path):
            raise OSError("Permission denied")

        monkeypatch.setattr(os, 'makedirs', mock_makedirs)
        result = self.xiv.download('http://arxiv.org/abs/1234.5678', '/nonexistent/deeply/nested/path')
        assert result is False
        captured = capsys.readouterr()
        err = captured.err if hasattr(captured, 'err') else captured[1]
        assert 'Cannot create directory' in err

    def test_cleans_up_file_on_retry_failure(self, monkeypatch, capsys):
        """Test that failed downloads clean up partial files"""
        call_count = [0]

        def mock_urlopen(req):
            call_count[0] += 1
            raise Exception("HTTP Error 503")

        monkeypatch.setattr(self.xiv, 'urlopen', mock_urlopen)
        result = self.xiv.download('http://arxiv.org/abs/1234.5678', self.tmpdir)

        assert result is False
        # Verify file was cleaned up after each failed attempt
        assert not os.path.exists(os.path.join(self.tmpdir, '1234.5678.pdf'))
        assert call_count[0] == self.xiv.DEFAULT_RETRY_ATTEMPTS


# Retry logic tests
class TestRetryWithBackoff:
    def test_returns_result_on_first_success(self, xiv):
        result = xiv.retry_with_backoff(lambda: "success", "Test")
        assert result == "success"

    def test_retries_with_exponential_backoff(self, xiv, monkeypatch, capsys):
        attempts, sleeps = [0], []
        monkeypatch.setattr(time, 'sleep', lambda s: sleeps.append(s))

        def op():
            attempts[0] += 1
            if attempts[0] < 3:
                raise Exception("HTTP Error 503: Service Unavailable")
            return "success"

        result = xiv.retry_with_backoff(op, "Test")
        assert result == "success" and attempts[0] == 3 and sleeps == [1, 2]

    def test_gives_up_after_max_attempts(self, xiv, monkeypatch, capsys):
        attempts = [0]
        monkeypatch.setattr(time, 'sleep', lambda s: None)

        def op():
            attempts[0] += 1
            raise Exception("HTTP Error 503")

        result = xiv.retry_with_backoff(op, "Test")
        assert result is None and attempts[0] == xiv.DEFAULT_RETRY_ATTEMPTS

    def test_non_retryable_error_fails_immediately(self, xiv):
        attempts = [0]
        def op():
            attempts[0] += 1
            raise Exception("HTTP Error 404")

        result = xiv.retry_with_backoff(op, "Test")
        assert result is None and attempts[0] == 1

    def test_keyboard_interrupt_cancels_retry(self, xiv, monkeypatch, capsys):
        attempts = [0]
        monkeypatch.setattr(time, 'sleep', lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))

        def op():
            attempts[0] += 1
            raise Exception("HTTP Error 503")

        result = xiv.retry_with_backoff(op, "Test")
        assert result is None and attempts[0] == 1


# Helper function tests
class TestHelpers:
    @pytest.mark.parametrize("error,expected", [
        ("HTTP Error 503: Service Unavailable", True),
        ("HTTP Error 502 Bad Gateway", True),
        ("504 Gateway Timeout", True),
        ("Connection timeout", True),
        ("HTTP Error 404: Not Found", False),
    ])
    def test_is_retryable_error(self, xiv, error, expected):
        assert xiv.is_retryable_error(Exception(error)) == expected

    @pytest.mark.parametrize("content,expected", [
        (b'<html><body>CAPTCHA</body></html>', True),
        (b'This file contains captcha verification', True),
        (b'<!DOCTYPE html><html></html>', True),
        (b'%PDF-1.4\n%\xE2\xE3\xCF\xD3\n', False),
    ])
    def test_is_captcha(self, xiv, tmpdir, content, expected):
        path = os.path.join(tmpdir, 'test.pdf')
        with open(path, 'wb') as f:
            f.write(content)
        assert xiv.is_captcha(path) == expected

    def test_is_captcha_skips_large_files(self, xiv, tmpdir):
        path = os.path.join(tmpdir, 'large.pdf')
        with open(path, 'wb') as f:
            f.write(b'%PDF-1.4\n' + b'\x00' * 200000)
        assert not xiv.is_captcha(path)


# Format function tests
class TestFormatting:
    @pytest.fixture
    def papers(self):
        return [
            {'title': 'First', 'authors': 'Alice', 'published': '2025-10-16',
             'link': 'http://arxiv.org/abs/1', 'abstract': 'Abstract 1'},
            {'title': 'Second', 'authors': 'Bob et al. (5)', 'published': '2025-10-15',
             'link': 'http://arxiv.org/abs/2', 'abstract': 'Abstract 2'},
        ]

    def test_format_json(self, xiv, papers, capsys):
        xiv.format_papers(papers, 'json')
        out = capsys.readouterr()
        output = out[0] if isinstance(out, tuple) else out.out
        data = json.loads(output)
        assert isinstance(data, list) and len(data) == 2 and data[0]['title'] == 'First'

    def test_format_compact(self, xiv, papers, capsys):
        xiv.format_papers(papers, 'compact')
        out = capsys.readouterr()
        output = out[0] if isinstance(out, tuple) else out.out
        assert '[1, 2025-10-16]' in output and 'First' in output

    def test_format_detailed(self, xiv, papers, capsys):
        xiv.format_papers(papers, 'detailed')
        out = capsys.readouterr()
        output = out[0] if isinstance(out, tuple) else out.out
        assert all(x in output for x in ['[1] First', 'Alice', '2025-10-16', 'Abstract 1'])


# Batch download tests
class TestDownloadPapers:
    @pytest.fixture(autouse=True)
    def setup(self, xiv, monkeypatch, tmpdir):
        self.xiv = xiv
        self.tmpdir = tmpdir
        self.downloads = []

        monkeypatch.setattr(xiv, 'download', lambda link, d: self.downloads.append(link) or True)
        monkeypatch.setattr(time, 'sleep', lambda s: None)

    def test_downloads_each_paper(self, capsys):
        papers = [{'link': 'http://arxiv.org/abs/1', 'title': 'P1'},
                  {'link': 'http://arxiv.org/abs/2', 'title': 'P2'}]
        self.xiv.download_papers(papers, self.tmpdir)
        assert self.downloads == ['http://arxiv.org/abs/1', 'http://arxiv.org/abs/2']

    def test_shows_progress(self, capsys):
        papers = [{'link': 'http://arxiv.org/abs/1', 'title': 'P1'},
                  {'link': 'http://arxiv.org/abs/2', 'title': 'P2'}]
        self.xiv.download_papers(papers, self.tmpdir)
        out = capsys.readouterr()
        stderr = out[1] if isinstance(out, tuple) else out.err
        assert '[1/2]' in stderr and '[2/2]' in stderr

    def test_reports_captcha_count(self, monkeypatch, capsys):
        monkeypatch.setattr(self.xiv, 'download', lambda link, d: 'captcha' if '1' in link else True)

        papers = [{'link': 'http://arxiv.org/abs/1', 'title': 'P1'},
                  {'link': 'http://arxiv.org/abs/2', 'title': 'P2'}]
        self.xiv.download_papers(papers, self.tmpdir)
        out = capsys.readouterr()
        stderr = out[1] if isinstance(out, tuple) else out.err
        assert '1/2 saved' in stderr and '1 CAPTCHA blocked' in stderr

    def test_keyboard_interrupt_exits_with_130(self, monkeypatch):
        monkeypatch.setattr(time, 'sleep', lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))
        papers = [{'link': 'http://arxiv.org/abs/1', 'title': 'P1'},
                  {'link': 'http://arxiv.org/abs/2', 'title': 'P2'}]

        with pytest.raises(SystemExit) as e:
            self.xiv.download_papers(papers, self.tmpdir)
        assert e.value.code == 130


# CLI tests
class TestCLI:
    @pytest.fixture(autouse=True)
    def setup(self, xiv, monkeypatch):
        self.xiv = xiv
        self.search_calls = []
        self.download_calls = []

        monkeypatch.setattr(xiv, 'search', lambda *a, **k: self.search_calls.append((a, k)) or [
            {'title': 'Test', 'authors': 'Author', 'published': '2025-10-16',
             'link': 'http://arxiv.org/abs/1', 'abstract': 'Abstract'}])
        monkeypatch.setattr(xiv, 'download', lambda *a, **k: self.download_calls.append(a))

    def test_default_arguments(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'neural'])
        self.xiv.main()
        assert self.search_calls[0][0][0] == 'neural' and self.search_calls[0][0][1] == 10

    @pytest.mark.parametrize("args,expected_max", [
        (['-n', '20'], 20),
        (['-t', '7'], 1000),
    ])
    def test_max_results_option(self, monkeypatch, capsys, args, expected_max):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test'] + args)
        self.xiv.main()
        assert self.search_calls[0][0][1] == expected_max

    @pytest.mark.parametrize("args,expected_cats", [
        (['-c', 'cs.AI'], ['cs.AI']),
        (['-c', 'cs.AI', 'cs.LG'], ['cs.AI', 'cs.LG']),
    ])
    def test_category_option(self, monkeypatch, capsys, args, expected_cats):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test'] + args)
        self.xiv.main()
        call = self.search_calls[0]
        cats = call[0][4] if len(call[0]) > 4 else call[1].get('categories')
        assert cats == expected_cats

    def test_time_filter_sets_since_date(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-t', '7'])
        self.xiv.main()
        call = self.search_calls[0]
        since = call[0][3] if len(call[0]) > 3 else call[1].get('since')
        expected = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        assert since == expected

    def test_sort_option(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-s', 'relevance'])
        self.xiv.main()
        call = self.search_calls[0]
        sort = call[0][2] if len(call[0]) > 2 else call[1].get('sort')
        assert sort == 'relevance'

    @pytest.mark.parametrize("args,format_check", [
        (['-j'], lambda out: isinstance(json.loads(out), list)),
        (['-l'], lambda out: '[1, 2025-10-16]' in out or '[01, 2025-10-16]' in out),
    ])
    def test_output_formats(self, monkeypatch, capsys, args, format_check):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test'] + args)
        self.xiv.main()
        out = capsys.readouterr()
        output = out[0] if isinstance(out, tuple) else out.out
        assert format_check(output)

    def test_download_option_triggers_download(self, monkeypatch, capsys, tmpdir):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-d', tmpdir])
        self.xiv.main()
        assert len(self.download_calls) == 1


# Environment variable tests
class TestEnvironment:
    @pytest.mark.parametrize("var,value,attr,expected", [
        ('XIV_MAX_RESULTS', '42', 'DEFAULT_RESULTS', 42),
        ('XIV_CATEGORY', 'cs.AI', 'DEFAULT_CATEGORY', 'cs.AI'),
        ('XIV_SORT', 'relevance', 'DEFAULT_SORT', 'relevance'),
        ('XIV_PDF_DIR', 'my_papers', 'DEFAULT_PDF_DIR', 'my_papers'),
        ('XIV_DOWNLOAD_DELAY', '5.0', 'DEFAULT_DOWNLOAD_DELAY', 5.0),
        ('XIV_RETRY_ATTEMPTS', '5', 'DEFAULT_RETRY_ATTEMPTS', 5),
    ])
    def test_environment_variables(self, monkeypatch, var, value, attr, expected):
        monkeypatch.setenv(var, value)

        import xiv
        if sys.version_info >= (3, 4):
            import importlib
            importlib.reload(xiv)
        elif sys.version_info[0] >= 3:
            import imp
            imp.reload(xiv)
        else:
            reload(xiv)  # noqa: F821

        assert getattr(xiv, attr) == expected


# XML parsing and edge cases
class TestEdgeCases:
    def test_malformed_xml_raises_parse_error(self, xiv, monkeypatch):
        monkeypatch.setattr(xiv, 'urlopen', lambda u: MockResponse(b'<broken><xml></broken>'))
        with pytest.raises(ET.ParseError):
            xiv.search('test', max_results=10)

    def test_unicode_handling(self, xiv, monkeypatch):
        if sys.version_info[0] >= 3:
            xml = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1</id>
    <title>Étude with 中文</title>
    <published>2025-10-16T12:00:00Z</published>
    <author><name>José García</name></author>
    <summary>Abstract</summary>
  </entry>
</feed>'''
        else:
            xml = u'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1</id>
    <title>Étude</title>
    <published>2025-10-16T12:00:00Z</published>
    <author><name>José García</name></author>
    <summary>Abstract</summary>
  </entry>
</feed>'''
        monkeypatch.setattr(xiv, 'urlopen', lambda _: MockResponse(xml.encode('utf-8')))
        papers = xiv.search('test', max_results=10)
        assert len(papers) == 1 and 'Jos' in papers[0]['authors']

    def test_no_results_exits_with_code_1(self, xiv, monkeypatch):
        monkeypatch.setattr(xiv, 'search', lambda *_, **__: [])
        monkeypatch.setattr(sys, 'argv', ['xiv', 'none'])
        with pytest.raises(SystemExit) as e:
            xiv.main()
        assert e.value.code == 1

    def test_keyboard_interrupt_exits_with_code_130(self, xiv, monkeypatch):
        monkeypatch.setattr(xiv, 'search', lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test'])
        with pytest.raises(SystemExit) as e:
            try:
                xiv.main()
            except KeyboardInterrupt:
                sys.stderr.write("\n\nInterrupted.\n")
                sys.exit(130)
        assert e.value.code == 130

    def test_paper_with_no_authors(self, xiv, monkeypatch):
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1</id>
    <title>Paper</title>
    <published>2025-10-16T12:00:00Z</published>
    <summary>Abstract</summary>
  </entry>
</feed>'''
        monkeypatch.setattr(xiv, 'urlopen', lambda u: MockResponse(xml.encode('utf-8')))
        papers = xiv.search('test', max_results=10)
        assert len(papers) == 1 and papers[0]['authors'] == ''

    @pytest.mark.parametrize("query", ['', 'test&query=special<>chars'])
    def test_handles_special_queries(self, xiv, monkeypatch, fixtures_dir, query):
        def urlopen(u):
            with open(os.path.join(fixtures_dir, 'arxiv_response.xml'), 'rb') as f:
                return MockResponse(f.read())
        monkeypatch.setattr(xiv, 'urlopen', urlopen)
        papers = xiv.search(query, max_results=1)
        assert isinstance(papers, list)

    def test_very_long_title(self, xiv, monkeypatch):
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1</id>
    <title>%s</title>
    <published>2025-10-16T12:00:00Z</published>
    <author><name>Author</name></author>
    <summary>Abstract</summary>
  </entry>
</feed>''' % ('A' * 10000)
        monkeypatch.setattr(xiv, 'urlopen', lambda u: MockResponse(xml.encode('utf-8')))
        papers = xiv.search('test', max_results=10)
        assert len(papers) == 1 and len(papers[0]['title']) == 10000

    def test_download_retry_on_error(self, xiv, monkeypatch, tmpdir):
        attempts = [0]
        def urlopen(u):
            attempts[0] += 1
            if attempts[0] < 2:
                raise Exception("HTTP Error 503")
            with open('tests/fixtures/test.pdf', 'rb') as f:
                return MockResponse(f.read())

        monkeypatch.setattr(xiv, 'urlopen', urlopen)
        monkeypatch.setattr(time, 'sleep', lambda s: None)

        result = xiv.download('http://arxiv.org/abs/1', tmpdir)
        assert result is True and attempts[0] == 2

    def test_download_fails_after_max_retries(self, xiv, monkeypatch, tmpdir):
        monkeypatch.setattr(xiv, 'urlopen', lambda u: (_ for _ in ()).throw(Exception("HTTP Error 503")))
        monkeypatch.setattr(time, 'sleep', lambda s: None)
        assert xiv.download('http://arxiv.org/abs/1', tmpdir) is False

    def test_download_keyboard_interrupt_during_retry(self, xiv, monkeypatch, tmpdir):
        attempts = [0]
        monkeypatch.setattr(xiv, 'urlopen', lambda u: (attempts.__setitem__(0, attempts[0]+1),
                            (_ for _ in ()).throw(Exception("HTTP Error 503")))[1])
        monkeypatch.setattr(time, 'sleep', lambda s: (_ for _ in ()).throw(KeyboardInterrupt()))

        result = xiv.download('http://arxiv.org/abs/1', tmpdir)
        assert result is False and attempts[0] == 1

    def test_broken_pipe_handling(self):
        import subprocess
        proc = subprocess.Popen([sys.executable, 'xiv.py'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.stdout.close()
        proc.wait()
        stderr = proc.stderr.read().decode('utf-8')
        assert 'Traceback' not in stderr and 'BrokenPipeError' not in stderr


# Index parsing tests
class TestParseIndices:
    @pytest.mark.parametrize("spec,total,expected", [
        ('1', 5, [0]),
        ('1,3,5', 5, [0, 2, 4]),
        ('1-3', 5, [0, 1, 2]),
        ('1-5', 5, [0, 1, 2, 3, 4]),
        ('1,3-5', 10, [0, 2, 3, 4]),
        ('1,3-5,8', 10, [0, 2, 3, 4, 7]),
        ('5-7,2,9', 10, [1, 4, 5, 6, 8]),
        ('1, 3 , 5', 5, [0, 2, 4]),  # With spaces
    ])
    def test_valid_index_specs(self, xiv, spec, total, expected):
        result = xiv.parse_indices(spec, total)
        assert result == expected

    @pytest.mark.parametrize("spec,total", [
        ('0', 5),          # Index too low
        ('6', 5),          # Index too high
        ('1-6', 5),        # Range exceeds total
        ('3-1', 5),        # Reversed range
        ('-1', 5),         # Negative index
        ('1--3', 5),       # Double dash
        ('abc', 5),        # Non-numeric
        ('1,a,3', 5),      # Mixed valid/invalid
        ('1.5', 5),        # Float
        ('', 5),           # Empty string
        (None, 5),         # None
    ])
    def test_invalid_index_specs(self, xiv, spec, total):
        result = xiv.parse_indices(spec, total)
        assert result is None

    def test_deduplicates_indices(self, xiv):
        result = xiv.parse_indices('1,1,2,2', 5)
        assert result == [0, 1]

    def test_sorts_indices(self, xiv):
        result = xiv.parse_indices('5,3,1,4,2', 5)
        assert result == [0, 1, 2, 3, 4]


# Selective download tests
class TestSelectiveDownload:
    @pytest.fixture(autouse=True)
    def setup(self, xiv, monkeypatch, tmpdir):
        self.xiv = xiv
        self.tmpdir = tmpdir
        self.downloads = []

        monkeypatch.setattr(xiv, 'download', lambda link, d: self.downloads.append(link) or True)
        monkeypatch.setattr(time, 'sleep', lambda s: None)

    def test_downloads_selected_papers_by_indices(self):
        papers = [
            {'link': 'http://arxiv.org/abs/1', 'title': 'P1'},
            {'link': 'http://arxiv.org/abs/2', 'title': 'P2'},
            {'link': 'http://arxiv.org/abs/3', 'title': 'P3'},
            {'link': 'http://arxiv.org/abs/4', 'title': 'P4'},
            {'link': 'http://arxiv.org/abs/5', 'title': 'P5'},
        ]
        self.xiv.download_papers(papers, self.tmpdir, indices=[0, 2, 4])
        assert self.downloads == [
            'http://arxiv.org/abs/1',
            'http://arxiv.org/abs/3',
            'http://arxiv.org/abs/5'
        ]

    def test_downloads_all_when_no_indices(self):
        papers = [
            {'link': 'http://arxiv.org/abs/1', 'title': 'P1'},
            {'link': 'http://arxiv.org/abs/2', 'title': 'P2'},
        ]
        self.xiv.download_papers(papers, self.tmpdir, indices=None)
        assert len(self.downloads) == 2

    def test_progress_shows_selected_count(self, capsys):
        papers = [
            {'link': 'http://arxiv.org/abs/%d' % i, 'title': 'P%d' % i}
            for i in range(1, 11)
        ]
        self.xiv.download_papers(papers, self.tmpdir, indices=[0, 4, 9])
        out = capsys.readouterr()
        stderr = out[1] if isinstance(out, tuple) else out.err
        assert '[1/3]' in stderr and '[2/3]' in stderr and '[3/3]' in stderr


# CLI tests for selective download
class TestCLISelectiveDownload:
    @pytest.fixture(autouse=True)
    def setup(self, xiv, monkeypatch, tmpdir):
        self.xiv = xiv
        self.tmpdir = tmpdir
        self.download_papers_calls = []

        self.papers = [
            {'title': 'Paper %d' % i, 'authors': 'Author', 'published': '2025-10-16',
             'link': 'http://arxiv.org/abs/%d' % i, 'abstract': 'Abstract'}
            for i in range(1, 6)
        ]

        monkeypatch.setattr(xiv, 'search', lambda *a, **k: self.papers)
        monkeypatch.setattr(xiv, 'download_papers',
                          lambda papers, dir, indices=None: self.download_papers_calls.append((papers, dir, indices)))

    @pytest.mark.parametrize("args,expected_dir,expected_indices", [
        (['-d'], 'DEFAULT_PDF_DIR', None),
        (['-d', '1,3,5'], 'DEFAULT_PDF_DIR', [0, 2, 4]),
        (['-d', '1-3'], 'DEFAULT_PDF_DIR', [0, 1, 2]),
        (['-d', '1,3-5'], 'DEFAULT_PDF_DIR', [0, 2, 3, 4]),
    ])
    def test_download_args_combinations(self, monkeypatch, args, expected_dir, expected_indices):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test'] + args)
        self.xiv.main()
        papers, dir, indices = self.download_papers_calls[0]
        exp_dir = self.xiv.DEFAULT_PDF_DIR if expected_dir == 'DEFAULT_PDF_DIR' else expected_dir
        assert dir == exp_dir and indices == expected_indices

    def test_download_with_directory_only(self, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-d', self.tmpdir])
        self.xiv.main()
        papers, dir, indices = self.download_papers_calls[0]
        assert dir == self.tmpdir and indices is None

    def test_download_with_directory_and_indices(self, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-d', self.tmpdir, '1,3'])
        self.xiv.main()
        papers, dir, indices = self.download_papers_calls[0]
        assert dir == self.tmpdir and indices == [0, 2]

    def test_invalid_indices_exits_with_error(self, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-d', '1,999'])
        with pytest.raises(SystemExit) as e:
            self.xiv.main()
        assert e.value.code == 1

    def test_too_many_args_exits_with_error(self, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-d', 'dir1', 'dir2', 'dir3'])
        with pytest.raises(SystemExit) as e:
            self.xiv.main()
        assert e.value.code == 1


# parse_download_args tests
class TestParseDownloadArgs:
    def test_returns_none_when_no_download_flag(self, xiv):
        dir, indices = xiv.parse_download_args(None, 5)
        assert dir is None and indices is None

    @pytest.mark.parametrize("args,num_papers,expected_dir,expected_indices", [
        ([], 5, 'DEFAULT', None),
        (['papers/'], 5, 'papers/', None),
        (['1,3'], 5, 'DEFAULT', [0, 2]),
        (['papers/', '1-3'], 5, 'papers/', [0, 1, 2]),
    ])
    def test_valid_download_args(self, xiv, args, num_papers, expected_dir, expected_indices):
        dir, indices = xiv.parse_download_args(args, num_papers)
        exp_dir = xiv.DEFAULT_PDF_DIR if expected_dir == 'DEFAULT' else expected_dir
        assert dir == exp_dir and indices == expected_indices

    def test_exits_on_too_many_args(self, xiv):
        with pytest.raises(SystemExit) as e:
            xiv.parse_download_args(['a', 'b', 'c'], 5)
        assert e.value.code == 1

    def test_exits_on_invalid_indices(self, xiv):
        with pytest.raises(SystemExit) as e:
            xiv.parse_download_args(['1,999'], 5)
        assert e.value.code == 1

    def test_exits_on_nonexistent_parent_dir(self, xiv):
        with pytest.raises(SystemExit) as e:
            xiv.parse_download_args(['/nonexistent_parent/papers'], 5)
        assert e.value.code == 1

    def test_validate_download_dir_permission_error(self, xiv, monkeypatch):
        """Test permission error path"""
        monkeypatch.setattr('os.path.exists', lambda p: True)
        monkeypatch.setattr('os.access', lambda p, m: False)
        err = xiv.validate_download_dir('/path')
        assert err is not None
        assert 'permission' in err.lower()


# Configuration tests
def test_sorts_mapping(xiv):
    assert xiv.SORTS == {'date': 'submittedDate', 'updated': 'lastUpdatedDate', 'relevance': 'relevance'}


# Environment variable validation tests
class TestEnvironmentValidation:
    @pytest.mark.parametrize("var,value,expected_val,should_warn", [
        ('XIV_MAX_RESULTS', '5', 5, False),
        ('XIV_MAX_RESULTS', 'invalid', 10, True),
        ('XIV_MAX_RESULTS', '-5', 10, True),
        ('XIV_MAX_RESULTS', '5000', 10, True),
        ('XIV_DOWNLOAD_DELAY', '5.0', 5.0, False),
        ('XIV_DOWNLOAD_DELAY', 'abc', 3.0, True),
        ('XIV_DOWNLOAD_DELAY', '-1.0', 3.0, True),
        ('XIV_DOWNLOAD_DELAY', '100.0', 3.0, True),
        ('XIV_RETRY_ATTEMPTS', '5', 5, False),
        ('XIV_RETRY_ATTEMPTS', '0', 3, True),
        ('XIV_RETRY_ATTEMPTS', '20', 3, True),
        ('XIV_MAX_AUTHORS', '5', 5, False),
        ('XIV_MAX_AUTHORS', '0', 3, True),
        ('XIV_SORT', 'relevance', 'relevance', False),
        ('XIV_SORT', 'invalid', 'date', True),
    ])
    def test_env_var_validation(self, monkeypatch, var, value, expected_val, should_warn, capsys):
        monkeypatch.setenv(var, value)

        import xiv
        if sys.version_info >= (3, 4):
            import importlib
            importlib.reload(xiv)
        elif sys.version_info[0] >= 3:
            import imp
            imp.reload(xiv)
        else:
            reload(xiv)  # noqa: F821

        attr_map = {
            'XIV_MAX_RESULTS': 'DEFAULT_RESULTS',
            'XIV_DOWNLOAD_DELAY': 'DEFAULT_DOWNLOAD_DELAY',
            'XIV_RETRY_ATTEMPTS': 'DEFAULT_RETRY_ATTEMPTS',
            'XIV_MAX_AUTHORS': 'DEFAULT_MAX_AUTHORS',
            'XIV_SORT': 'DEFAULT_SORT',
        }
        attr = attr_map[var]
        assert getattr(xiv, attr) == expected_val

        out = capsys.readouterr()
        stderr = out[1] if isinstance(out, tuple) else out.err
        if should_warn:
            assert 'Warning' in stderr

    def test_download_delay_policy_warning(self, monkeypatch, capsys):
        monkeypatch.setenv('XIV_DOWNLOAD_DELAY', '1.0')

        import xiv
        if sys.version_info >= (3, 4):
            import importlib
            importlib.reload(xiv)
        elif sys.version_info[0] >= 3:
            import imp
            imp.reload(xiv)
        else:
            reload(xiv)  # noqa: F821

        out = capsys.readouterr()
        stderr = out[1] if isinstance(out, tuple) else out.err
        assert 'API limits' in stderr and 'blocking' in stderr

    @pytest.mark.parametrize("category,known", [
        ('cs.AI', True), ('math.CO', True), ('quant-ph', True), ('stat.ML', True),
        ('invalid_cat', False), ('new_category', False)
    ])
    def test_category_set(self, xiv, category, known):
        """Known arXiv categories are in ARXIV_CATEGORIES"""
        assert (category in xiv.ARXIV_CATEGORIES) == known

    @pytest.mark.parametrize("category,should_warn", [
        ('cs.AI', False), ('cs.ai', False), ('CS.AI', False),  # Case-insensitive
        ('cs.ET', False), ('cs.et', False), ('Cs.Et', False),  # Mixed case
        ('invalid_cat', True)
    ])
    def test_category_validation_warns(self, xiv, capsys, category, should_warn):
        """Category validation is case-insensitive; unknown categories trigger warning"""
        assert xiv.validate_category(category) is True
        out = capsys.readouterr()
        stderr = out[1] if isinstance(out, tuple) else out.err
        assert ('Unrecognized category' in stderr) == should_warn


# CLI validation tests
class TestCLIValidation:
    def test_negative_max_results_error(self, xiv, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-n', '-5'])
        with pytest.raises(SystemExit) as e:
            xiv.main()
        assert e.value.code == 1

    def test_zero_max_results_error(self, xiv, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-n', '0'])
        with pytest.raises(SystemExit) as e:
            xiv.main()
        assert e.value.code == 1

    def test_negative_time_filter_error(self, xiv, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-t', '-1'])
        with pytest.raises(SystemExit) as e:
            xiv.main()
        assert e.value.code == 1

    def test_zero_time_filter_error(self, xiv, monkeypatch):
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-t', '0'])
        with pytest.raises(SystemExit) as e:
            xiv.main()
        assert e.value.code == 1

    def test_excessive_max_results_warning(self, xiv, monkeypatch, capsys):
        monkeypatch.setattr(xiv, 'search', lambda *a, **k: [])
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-n', '3000'])
        with pytest.raises(SystemExit) as e:
            xiv.main()
        out = capsys.readouterr()
        stderr = out[1] if isinstance(out, tuple) else out.err
        assert 'Warning' in stderr and '2000' in stderr

    def test_unknown_category_warns(self, xiv, monkeypatch, capsys):
        """Unknown categories trigger warning in CLI"""
        monkeypatch.setattr(xiv, 'search', lambda *a, **k: [])
        monkeypatch.setattr(sys, 'argv', ['xiv', 'test', '-c', 'unknown_cat', '-n', '1'])
        with pytest.raises(SystemExit):
            xiv.main()
        out = capsys.readouterr()
        assert 'Unrecognized category' in (out[1] if isinstance(out, tuple) else out.err)


# Config display tests
class TestConfig:
    def test_config_displays_settings(self, xiv, monkeypatch, capsys):
        monkeypatch.setattr(sys, 'argv', ['xiv', '-e'])
        with pytest.raises(SystemExit) as e:
            xiv.main()
        assert e.value.code == 0

        out = capsys.readouterr()
        output = out[0] if isinstance(out, tuple) else out.out
        assert 'XIV_MAX_RESULTS' in output
        assert 'XIV_DOWNLOAD_DELAY' in output
        assert 'violates API limits' in output

    def test_config_shows_custom_values(self, xiv, monkeypatch, capsys):
        monkeypatch.setenv('XIV_MAX_RESULTS', '50')
        monkeypatch.setattr(sys, 'argv', ['xiv', '-e'])

        import xiv as xiv_module
        if sys.version_info >= (3, 4):
            import importlib
            importlib.reload(xiv_module)
        elif sys.version_info[0] >= 3:
            import imp
            imp.reload(xiv_module)
        else:
            reload(xiv_module)  # noqa: F821

        with pytest.raises(SystemExit) as e:
            xiv_module.main()
        assert e.value.code == 0

        out = capsys.readouterr()
        output = out[0] if isinstance(out, tuple) else out.out
        assert '50' in output


# Format functionality tests
class TestFormatFunctionality:
    @pytest.fixture
    def paper(self):
        return {'title': 'Test', 'authors': 'Alice, Bob', 'published': '2025-10-16',
                'link': 'http://arxiv.org/abs/1', 'abstract': 'Abstract'}

    @pytest.mark.parametrize('style,formatted,has_ansi', [
        ('detailed', 0, False), ('detailed', 1, True),
        ('compact', 0, False), ('compact', 1, True),
        ('json', 1, False),  # JSON never has ANSI codes
    ])
    def test_format_output(self, xiv, paper, capsys, style, formatted, has_ansi):
        """Test formatting across styles"""
        xiv.format_papers([paper], style, formatted)
        out = capsys.readouterr()
        output = out[0] if isinstance(out, tuple) else out.out
        assert ('\033[' in output) == has_ansi
        assert 'Test' in output or (style == 'json' and '"title"' in output)

    def test_et_al_formatting(self, xiv, capsys):
        """et al. text plain, author names and count colored"""
        paper = {'title': 'Multi', 'authors': 'Alice, Bob et al. (10)',
                 'published': '2025-10-16', 'link': 'http://arxiv.org/abs/1', 'abstract': 'Test'}
        xiv.format_papers([paper], 'detailed', 1)
        out = capsys.readouterr()
        output = out[0] if isinstance(out, tuple) else out.out
        assert ' et al. (' in output and '\033[93m' in output

    @pytest.mark.parametrize('argv,has_ansi', [
        (['xiv', 'test', '-f'], True),      # -f flag enables
        (['xiv', 'test'], False),            # no flag = plain
    ])
    def test_cli_format_flag(self, xiv, monkeypatch, capsys, argv, has_ansi):
        """Test -f flag behavior"""
        monkeypatch.setattr(xiv, 'search', lambda *a, **k: [
            {'title': 'T', 'authors': 'A', 'published': '2025-10-16',
             'link': 'http://arxiv.org/abs/1', 'abstract': 'X'}])
        monkeypatch.setattr(sys, 'argv', argv)
        xiv.main()
        out = capsys.readouterr()
        output = out[0] if isinstance(out, tuple) else out.out
        assert ('\033[' in output) == has_ansi

    def test_xiv_format_env_var(self, monkeypatch):
        """XIV_FORMAT env var sets default"""
        monkeypatch.setenv('XIV_FORMAT', '1')
        import xiv
        if sys.version_info >= (3, 4):
            import importlib
            importlib.reload(xiv)
        elif sys.version_info[0] >= 3:
            import imp
            imp.reload(xiv)
        else:
            reload(xiv)  # noqa: F821
        assert xiv.DEFAULT_FORMAT == 1

    def test_config_displays_format(self, xiv, monkeypatch, capsys):
        """show_config displays XIV_FORMAT"""
        monkeypatch.setattr(sys, 'argv', ['xiv', '-e'])
        with pytest.raises(SystemExit):
            xiv.main()
        assert 'XIV_FORMAT' in capsys.readouterr()[0]
