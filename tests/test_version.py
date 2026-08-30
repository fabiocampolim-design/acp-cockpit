# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Fabio Campolim
import re

from claudiu import VERSION


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)
