from __future__ import annotations

from importlib.metadata import distribution, version

import rebuildwhy


def test_runtime_version_matches_distribution_metadata() -> None:
    assert rebuildwhy.__version__ == version("rebuildwhy")


def test_console_entry_point_is_published() -> None:
    entry_points = {
        entry_point.name: entry_point.value
        for entry_point in distribution("rebuildwhy").entry_points
        if entry_point.group == "console_scripts"
    }

    assert entry_points["rebuildwhy"] == "rebuildwhy.cli:main"
