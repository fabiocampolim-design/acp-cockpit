# SPDX-License-Identifier: Apache-2.0
"""The built wheel is the product. On 2026-09-05 it held 24 Python files and
none of the UI, the vendored schema, the agent profiles or the name file:
only an editable install from a checkout worked. `pip install acp-cockpit`
would have served a 404 for its own page."""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from acp_cockpit.core.profiles import load_profiles

MUST_SHIP = (
    "acp_cockpit/ui/web/index.html",
    "acp_cockpit/ui/web/app.js",
    "acp_cockpit/ui/web/style.css",
    "acp_cockpit/vendor/acp/registry.json",
    "acp_cockpit/vendor/acp/schema.json",
    "acp_cockpit/vendor/acp/VERSION",
    "acp_cockpit/agents/claude.toml",
    "acp_cockpit/agents/PROFILE-SCHEMA.md",
    "acp_cockpit/uiname.toml",
)


@pytest.mark.skipif(shutil.which("pip") is None and
                    subprocess.run([sys.executable, "-m", "pip", "--version"],
                                   capture_output=True).returncode != 0,
                    reason="pip not available")
def test_the_wheel_ships_the_ui_the_schema_the_profiles_and_the_name(tmp_path):
    # Built the way pip builds it: in an isolated environment with the
    # setuptools the pyproject asks for. `--no-build-isolation` used the
    # runner's preinstalled setuptools, which on the Python 3.11 cells was
    # too old for the PEP 639 `license = "Apache-2.0"` string (CI 2026-09-05).
    run = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
         "-q", "-w", str(tmp_path)],
        capture_output=True, text=True, timeout=900)
    assert run.returncode == 0, run.stderr[-2000:]
    wheel = next(tmp_path.glob("acp_cockpit-*.whl"))
    names = set(zipfile.ZipFile(wheel).namelist())
    missing = [n for n in MUST_SHIP if n not in names]
    assert not missing, f"wheel lacks {missing}"


def test_the_default_profiles_dir_is_inside_the_package():
    from acp_cockpit.__main__ import default_profiles_dirs
    dirs = default_profiles_dirs()
    assert (dirs[0] / "claude.toml").is_file()
    assert dirs[0].resolve().parent.name == "acp_cockpit"


def test_the_user_profile_directory_overlays_the_shipped_one(tmp_path):
    shipped = tmp_path / "shipped"
    mine = tmp_path / "mine"
    shipped.mkdir()
    mine.mkdir()
    base = ('id = "{id}"\nname = "{name}"\ncommand = ["x"]\n'
            'install_hint = "n/a"\nenv_scrub = []\n')
    (shipped / "claude.toml").write_text(base.format(id="claude", name="Shipped"),
                                         encoding="utf-8")
    (mine / "claude.toml").write_text(base.format(id="claude", name="Mine"),
                                      encoding="utf-8")
    (mine / "extra.toml").write_text(base.format(id="extra", name="Extra"),
                                     encoding="utf-8")
    profiles = load_profiles(shipped, mine)
    assert set(profiles) == {"claude", "extra"}
    assert profiles["claude"].name == "Mine"       # the later directory wins


def test_a_missing_user_profile_directory_is_not_an_error(tmp_path):
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "a.toml").write_text(
        'id = "a"\nname = "A"\ncommand = ["x"]\ninstall_hint = "n/a"\n'
        'env_scrub = []\n', encoding="utf-8")
    assert set(load_profiles(shipped, tmp_path / "nowhere")) == {"a"}


def test_the_registry_and_the_name_file_are_found_from_the_package():
    from acp_cockpit.core import sentinel, branding
    assert Path(sentinel._REGISTRY_PATH).is_file()
    assert sentinel._REGISTRY_PATH.parent.parent.parent.name == "acp_cockpit"
    assert (branding._PACKAGE_ROOT / "uiname.toml").is_file()
    assert branding._PACKAGE_ROOT.name == "acp_cockpit"
