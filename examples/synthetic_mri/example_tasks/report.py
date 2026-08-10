"""Render a compact Markdown report from synthetic features."""

from pathlib import Path

from example_tasks.common import context, read_json


def main() -> None:
    ctx = context()
    features = read_json(ctx["artifacts"]["features:features.json"])
    title = ctx["configs"]["config/pipeline.yaml#/report/title"]
    report = (
        f"# {title}\n\n"
        f"- Voxels: {features['count']}\n"
        f"- Mean normalized intensity: {features['mean']:.6f}\n"
        f"- Above threshold: {features['above_threshold']}\n"
    )
    Path(ctx["output_directory"], "report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
