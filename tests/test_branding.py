# SPDX-License-Identifier: Apache-2.0
"""The name on screen is configuration; the project name is not.

`acp-cockpit` is the project, the package and the docs. What the running
client calls itself is a separate thing, shipped as ClaudIU and changeable
without touching code — and always short enough for a browser tab, a
heading and a dialog title.
"""
from pathlib import Path

from acp_cockpit.core.branding import DEFAULT, KEY, MAX_LEN, ui_name


def test_the_shipped_default_is_claudiu():
    assert DEFAULT == "ClaudIU"
    assert ui_name(env={}) == "ClaudIU"


def test_the_environment_wins_over_the_file(tmp_path):
    f = tmp_path / "uiname.toml"
    f.write_text(f'{KEY} = "From The File"\n', encoding="utf-8")
    assert ui_name(f, env={}) == "From The File"
    assert ui_name(f, env={KEY: "From The Env"}) == "From The Env"


def test_a_long_name_is_cut_visibly_not_silently():
    long = "An Extremely Long Product Name"
    got = ui_name(env={KEY: long})
    assert len(got) == MAX_LEN
    assert got.endswith("…"), got
    assert long.startswith(got[:-1])


def test_a_name_of_exactly_the_limit_is_untouched():
    exact = "x" * MAX_LEN
    assert ui_name(env={KEY: exact}) == exact


def test_blank_and_broken_configuration_fall_back(tmp_path):
    assert ui_name(env={KEY: "   "}) == DEFAULT
    broken = tmp_path / "uiname.toml"
    broken.write_text("this is not toml {{{", encoding="utf-8")
    assert ui_name(broken, env={}) == DEFAULT
    assert ui_name(tmp_path / "absent.toml", env={}) == DEFAULT


def test_newlines_never_reach_a_title():
    assert "\n" not in ui_name(env={KEY: "two\nlines"})
    assert ui_name(env={KEY: "two\nlines"}) == "two lines"


def test_the_repository_ships_the_file_the_docs_describe():
    shipped = Path("uiname.toml").read_text(encoding="utf-8")
    assert f'{KEY} = "ClaudIU"' in shipped
