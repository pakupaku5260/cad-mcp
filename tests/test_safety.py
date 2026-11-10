"""
Path sandbox test: one by one override bypass method (v4 Section 11; checklist derived from Study Note 5.1).

List of gaps in the numbered notes corresponding to the study notes:
(1)..\\ Fallback (2) Extra-Root Absolute Path (3) ~ Escape (4) (5) Symbolic Link (6) UNC
(7) Reserved device name (8) NTFS ads (9) 8.3 Short name (10) Trailing dot/trailing space (11) Dial sign relative
(12) extension whitelist (13) overlay protection (14) read side sandbox (15) allow_outside audit

"""

import json
import sys

import pytest

from cadmcp import safety
from cadmcp.errors import CadMcpError
from cadmcp.safety import ensure_input_path, ensure_output_path


@pytest.fixture(autouse=True)
def audit_log(tmp_path):
    path = tmp_path / "audit.jsonl"
    safety.set_audit_path(path)
    yield path
    safety.set_audit_path(None)


@pytest.fixture()
def root(tmp_path):
    r = tmp_path / "ws"
    r.mkdir()
    return r


def expect_reject(fn, *args, code: str | None = None, **kwargs) -> CadMcpError:
    with pytest.raises(CadMcpError) as ei:
        fn(*args, **kwargs)
    if code is not None:
        assert ei.value.code == code, (
            f"expected {code}, got {ei.value.code}: {ei.value.message}"
        )
    return ei.value


def read_audit(path):
    lines = [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]
    return lines


# ---- Fundamentals of Release ----


def test_relative_path_allowed(root):
    out = ensure_output_path("part.sldprt", roots=root)
    assert out == (root / "part.sldprt").resolve()


def test_nested_relative_creates_parents(root):
    out = ensure_output_path("sub/dir/bracket.sldprt", roots=root)
    assert out.parent.is_dir()


def test_absolute_inside_root_allowed(root):
    out = ensure_output_path(str(root / "a.sldprt"), roots=root)
    assert out == (root / "a.sldprt").resolve()


def test_extension_case_insensitive(root):
    assert ensure_output_path("PART.SLDPRT", roots=root).name == "PART.SLDPRT"


# ---- (1) (2) (3) Escape ----


def test_dotdot_escape_rejected(root, audit_log):
    expect_reject(ensure_output_path, "a/../../evil.sldprt", roots=root,
                  code="PATH_OUTSIDE_SANDBOX")
    assert any(e["event"] == "path_rejected" for e in read_audit(audit_log))


def test_absolute_outside_rejected(root, tmp_path):
    expect_reject(ensure_output_path, str(tmp_path / "evil.sldprt"),
                  roots=root, code="PATH_OUTSIDE_SANDBOX")


def test_home_expansion_rejected(root):
    expect_reject(ensure_output_path, "~/evil.sldprt", roots=root,
                  code="PATH_OUTSIDE_SANDBOX")


# ---- (4) (5) Symbolic link ----


def test_symlink_to_inside_rejected(root):
    real = root / "real"
    real.mkdir()
    try:
        (root / "link").symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    expect_reject(ensure_output_path, "link/x.sldprt", roots=root,
                  code="PATH_SYMLINK_DENIED")


def test_symlink_to_outside_rejected(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "out").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    err = expect_reject(ensure_output_path, "out/x.sldprt", roots=root)
    assert err.code in {"PATH_SYMLINK_DENIED", "PATH_OUTSIDE_SANDBOX"}


def test_file_symlink_rejected(root, tmp_path):
    target = tmp_path / "orig.sldprt"
    target.write_text("x")
    try:
        (root / "alias.sldprt").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    err = expect_reject(ensure_output_path, "alias.sldprt", roots=root)
    assert err.code in {"PATH_SYMLINK_DENIED", "PATH_OUTSIDE_SANDBOX"}


# ---- (6) (8) (9) (11) Path morphology ----


def test_unc_windows_rejected(root):
    expect_reject(ensure_output_path, r"\\server\share\x.sldprt",
                  roots=root, code="PATH_INVALID")


def test_unc_posix_rejected(root):
    expect_reject(ensure_output_path, "//server/share/x.sldprt",
                  roots=root, code="PATH_INVALID")


def test_drive_relative_rejected(root):
    expect_reject(ensure_output_path, "D:foo.sldprt", roots=root, code="PATH_INVALID")


@pytest.mark.skipif(sys.platform == "win32", reason="D:\\ is a valid drive path on Windows; sandbox uses outside-root check")
def test_foreign_drive_absolute_rejected_on_posix(root):
    # Windows absolute path semantics cannot verify → rejection on non-Windows (Windows Runtime Native Release)
    expect_reject(ensure_output_path, "D:\\parts\\x.sldprt",
                  roots=root, code="PATH_INVALID")


def test_ntfs_ads_rejected(root):
    expect_reject(ensure_output_path, "part.sldprt:stream",
                  roots=root, code="PATH_INVALID")


# ---- (7) (10) (9) Reserved name and trailing characters ----


@pytest.mark.parametrize("name", ["CON", "NUL", "com1.sldprt", "sub/PRN.dat"])
def test_reserved_device_names_rejected(root, name):
    expect_reject(ensure_output_path, name, roots=root, code="PATH_INVALID")


def test_reserved_with_extension_rejected(root):
    expect_reject(ensure_output_path, "NUL.txt", roots=root, code="PATH_INVALID")


def test_trailing_dot_rejected(root):
    expect_reject(ensure_output_path, "x.sldprt.", roots=root, code="PATH_INVALID")


def test_trailing_space_rejected(root):
    expect_reject(ensure_output_path, "x.sldprt ", roots=root, code="PATH_INVALID")


def test_short_name_rejected(root):
    expect_reject(ensure_output_path, "PROGRA~1/x.sldprt", roots=root,
                  code="PATH_INVALID")


def test_null_byte_rejected(root):
    expect_reject(ensure_output_path, "a\x00.sldprt", roots=root, code="PATH_INVALID")


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_rejected(root, bad):
    expect_reject(ensure_output_path, bad, roots=root, code="PATH_INVALID")


def test_non_string_rejected(root):
    expect_reject(ensure_output_path, 123, roots=root, code="PATH_INVALID")  # type: ignore[arg-type]


# ---- (12) Extension Whitelist ----


def test_extension_denied(root):
    expect_reject(ensure_output_path, "evil.exe", roots=root,
                  code="PATH_EXTENSION_DENIED")
    expect_reject(ensure_output_path, "noext", roots=root,
                  code="PATH_EXTENSION_DENIED")


def test_custom_extension_set_replaces_default(root):
    assert ensure_output_path("a.foo", roots=root, extensions={".foo"})
    expect_reject(
        ensure_output_path, "a.sldprt", roots=root, extensions={".foo"},
        code="PATH_EXTENSION_DENIED",
    )


# ---- (13) Overlay Protection ----


def test_overwrite_requires_explicit_flag(root):
    existing = root / "model.sldprt"
    existing.write_text("original")
    expect_reject(ensure_output_path, "model.sldprt", roots=root,
                  code="PATH_OVERWRITE_DENIED")
    out = ensure_output_path("model.sldprt", roots=root, overwrite=True)
    assert out == existing.resolve()


# ---- (14) Reading Side Sandbox ----


def test_input_outside_roots_rejected(root, tmp_path):
    expect_reject(ensure_input_path, str(tmp_path / "x.sldprt"),
                  roots=root, code="PATH_OUTSIDE_SANDBOX")


def test_input_must_exist(root):
    expect_reject(ensure_input_path, "ghost.sldprt", roots=root,
                  code="PATH_NOT_FOUND")


def test_input_happy_path(root):
    (root / "in.sldprt").write_text("x")
    assert ensure_input_path("in.sldprt", roots=root) == (root / "in.sldprt").resolve()


def test_input_multi_root(tmp_path):
    r1, r2 = tmp_path / "w1", tmp_path / "w2"
    r1.mkdir()
    r2.mkdir()
    (r2 / "b.sldprt").write_text("x")
    assert ensure_input_path("b.sldprt", roots=[r1, r2])


# ---- (15) allow_outside Escape Pod + Audit ----


def test_allow_outside_is_explicit_and_audited(root, tmp_path, audit_log):
    outside = tmp_path / "approved.sldprt"
    expect_reject(ensure_output_path, str(outside), roots=root,
                  code="PATH_OUTSIDE_SANDBOX")
    out = ensure_output_path(str(outside), roots=root, allow_outside=True)
    assert out == outside.resolve()
    events = [e["event"] for e in read_audit(audit_log)]
    assert "path_allowed_outside" in events and "path_rejected" in events


def test_audit_records_reason(root, audit_log):
    expect_reject(ensure_output_path, "evil.exe", roots=root,
                  code="PATH_EXTENSION_DENIED")
    rec = read_audit(audit_log)[-1]
    assert rec["event"] == "path_rejected"
    assert rec["reason"] == "extension"
    assert rec["code"] == "PATH_EXTENSION_DENIED"


# Configuration


def test_default_root_name():
    assert safety.default_output_root().name == "cadmcp-workspace"
