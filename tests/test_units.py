"""Pure unit tests for small helpers: these must run on ANY machine
(no Macaulay2, no subprocesses) so refactors stay cheap (U-c)."""

from macaulay2_mcp.config import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, _parse_version, clamp_timeout
from macaulay2_mcp.gatekeep import rejection_message
from macaulay2_mcp.journal import Journal
from macaulay2_mcp.kernel import (
    _strip_trailing_prompt,
    parse_footprint_peak,
    parse_proc_memory,
    parse_ps_rss,
    parse_swapusage,
)
from macaulay2_mcp.scanner import mask
from macaulay2_mcp.server import (
    _clip_output,
    _escape_m2_string,
    _human_duration,
    _human_size,
    _memory_footnote,
)

# ------------------------------------------------------------------ config


def test_clamp_timeout_bounds():
    assert clamp_timeout(120) == 120
    assert clamp_timeout(0) == 1
    assert clamp_timeout(-5) == 1
    assert clamp_timeout(10**9) == MAX_TIMEOUT_S
    assert clamp_timeout(12.7) == 12


def test_clamp_timeout_garbage_falls_back():
    # a malformed JSON argument must never raise out of the tool boundary
    for bad in (None, "abc", float("nan"), float("inf")):
        assert clamp_timeout(bad) == DEFAULT_TIMEOUT_S


def test_parse_version():
    assert _parse_version("Macaulay2 1.26.06\n") == ((1, 26, 6), "1.26.06")
    assert _parse_version("no dots here") is None
    assert _parse_version("1.26") is None  # patch component required


# ------------------------------------------------------------------ kernel


def test_strip_trailing_prompt():
    assert _strip_trailing_prompt("out line\ni12 : \n") == "out line"
    assert _strip_trailing_prompt("a\n\ni3 :") == "a"
    assert _strip_trailing_prompt("plain") == "plain"


def test_parse_proc_memory():
    status = (
        "Name:\tM2\nState:\tS (sleeping)\nVmPeak:\t  999999 kB\n"
        "VmRSS:\t   98765 kB\nVmHWM:\t  131072 kB\nVmSwap:\t    204 kB\n"
    )
    assert parse_proc_memory(status) == (98765, 131072, 204)
    assert parse_proc_memory("Name:\tM2\n") == (None, None, None)
    assert parse_proc_memory("VmRSS:\tabc kB\n") == (None, None, None)
    assert parse_proc_memory("XVmHWM:\t5 kB\n") == (None, None, None)
    # partial files are fine: each field stands alone
    assert parse_proc_memory("VmRSS:\t10 kB\n") == (10, None, None)


def test_parse_ps_rss():
    assert parse_ps_rss(" 12345\n") == 12345
    assert parse_ps_rss("") is None
    assert parse_ps_rss("ps: unknown process\n") is None


def test_parse_footprint_peak():
    out = (
        "Auxiliary data:\n    phys_footprint: 103 MB\n"
        "    phys_footprint_peak: 1.5 GB\n\n"
    )
    assert parse_footprint_peak(out) == int(1.5 * 1024**3)
    assert parse_footprint_peak("phys_footprint_peak: 263 MB") == 263 * 1024**2
    assert parse_footprint_peak("phys_footprint_peak: 512 KB") == 512 * 1024
    assert parse_footprint_peak("no aux block here") is None
    assert parse_footprint_peak("phys_footprint_peak: junk MB") is None


def test_parse_swapusage():
    out = "vm.swapusage: total = 6144.00M  used = 3721.75M  free = 2422.25M  (encrypted)"
    assert parse_swapusage(out) == int(3721.75 * 1024**2)
    assert parse_swapusage("total = 0.00M  used = 0.00M  free = 0.00M") == 0
    assert parse_swapusage("garbage") is None


def test_memory_footnote_forms():
    from macaulay2_mcp.kernel import MemoryInfo

    assert (
        _memory_footnote(MemoryInfo(118 * 1024**2, 121 * 1024**2, 0))
        == "(M2 memory: 118.0 MB resident, peak 121.0 MB)"
    )
    # swap appears only when paging, and drags the advisory note along
    swapping = _memory_footnote(MemoryInfo(118 * 1024**2, 4 * 1024**3, 2 * 1024**3))
    assert swapping.startswith("(M2 memory: 118.0 MB resident, peak 4.0 GB; swap 2.0 GB)")
    assert "ORDERS OF MAGNITUDE" in swapping
    assert "m2_interrupt" in swapping
    # peak unknown (probe failure) still shows resident; all-unknown -> None
    assert _memory_footnote(MemoryInfo(1024, None, None)) == "(M2 memory: 1.0 KB resident)"
    assert _memory_footnote(MemoryInfo(None, None, None)) is None


def test_human_duration():
    assert _human_duration(47.9) == "47s"
    assert _human_duration(192) == "3m 12s"
    assert _human_duration(3723) == "1h 02m"
    assert _human_duration(None) == "unknown"


# ---------------------------------------------------------------- scanner


def test_mask_blanks_comment_and_string_interiors():
    m = mask(r'print "quote \" and -- dashes inside"  -- real comment')
    assert "--" not in m.text  # both comment and in-string dashes blanked
    assert m.text.count('"') == 2  # delimiters survive
    assert not m.ends_in_string


def test_mask_ends_in_string():
    m = mask('x = "oops')
    assert m.ends_in_string
    assert "oops" not in m.text


# ------------------------------------------------------------------ server


def test_escape_m2_string():
    assert _escape_m2_string('a"b') == 'a\\"b'
    assert _escape_m2_string("a\\b") == "a\\\\b"


def test_human_size():
    assert _human_size(500) == "500 B"
    assert _human_size(40_000) == "39.1 KB"


# ------------------------------------------------------- long-output policy


def _journal(tmp_path) -> Journal:
    return Journal(tmp_path, "test")


def test_clip_passthrough_under_both_limits(tmp_path):
    j = _journal(tmp_path)
    text = "\n".join(f"line {i}" for i in range(120))  # exactly 120, small bytes
    assert _clip_output(text, j, None) == text


def test_clip_many_lines_mentions_journal_seq(tmp_path):
    j = _journal(tmp_path)
    text = "\n".join(f"l{i} " + "x" * 50 for i in range(500))
    seq = j.record("evaluate", output=text)
    out = _clip_output(text, j, seq)
    assert "excerpted for display" in out
    assert f"seq {seq}" in out
    assert str(j.path) in out
    assert out.startswith("l0 ")
    assert out.rstrip().endswith("l499 " + "x" * 50)  # tail preserved
    assert len(out.encode()) < len(text.encode())


def test_clip_journal_disabled_says_not_stored(tmp_path):
    j = Journal(None, "test")
    out = _clip_output("y\n" * 300, j, None)
    assert "NOT stored" in out


def test_clip_single_long_line_is_byte_bound(tmp_path):
    j = _journal(tmp_path)
    text = "L" * 100_000  # ONE line, over the byte limit
    seq = j.record("evaluate", output=text)
    out = _clip_output(text, j, seq)
    assert "long line truncated by the server" in out
    assert len(out.encode()) < 30_000


# ------------------------------------------------------- gate messages (A)


def test_rejection_message_links_rationale():
    msg = rejection_message("runProgram")
    assert "github.com/youngsu-Kim/macaulay2-mcp#the-os-access-gate" in msg
    assert "ordinary word" not in msg  # unambiguous symbol: no rename hint


def test_rejection_message_ambiguous_word_gets_rename_hint():
    msg = rejection_message("lines")
    assert "ordinary word" in msg
    assert "rename" in msg
    assert "file-reading function" in msg
