# SPDX-License-Identifier: Apache-2.0
import os
import pytest
from claudiu.core.policy import PathPolicy


def test_inside_root_allowed(tmp_path):
    pol = PathPolicy(tmp_path)
    inner = tmp_path / "sub" / "f.txt"
    assert pol.allowed(str(inner))
    assert pol.allowed(str(tmp_path))


def test_outside_and_traversal_denied(tmp_path):
    pol = PathPolicy(tmp_path / "proj")
    assert not pol.allowed(str(tmp_path / "other" / "f.txt"))
    assert not pol.allowed(str(tmp_path / "proj" / ".." / "other" / "f.txt"))


def test_relative_paths_denied(tmp_path):
    pol = PathPolicy(tmp_path)
    assert not pol.allowed("relative/file.txt")


def test_grant_extends_boundary(tmp_path):
    pol = PathPolicy(tmp_path / "proj")
    extra = tmp_path / "shared"
    assert not pol.allowed(str(extra / "f.txt"))
    pol.grant(extra)
    assert pol.allowed(str(extra / "f.txt"))
    assert str(extra.resolve()) in pol.describe()["grants"][0]


@pytest.mark.skipif(os.name != "nt", reason="case rule is Windows-specific")
def test_windows_case_insensitive(tmp_path):
    pol = PathPolicy(tmp_path)
    assert pol.allowed(str(tmp_path).upper() + os.sep + "F.TXT")


def test_prefix_sibling_not_allowed(tmp_path):
    # /proj must not admit /proj-evil via naive string prefix
    root = tmp_path / "proj"
    pol = PathPolicy(root)
    assert not pol.allowed(str(tmp_path / "proj-evil" / "f.txt"))


def test_symlink_escape_denied(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("no symlink privilege")
    assert not PathPolicy(root).allowed(str(link / "f.txt"))
