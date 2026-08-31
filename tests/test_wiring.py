# SPDX-License-Identifier: Apache-2.0
import claudiu


def test_version():
    assert claudiu.__version__.startswith("0.2.0")
