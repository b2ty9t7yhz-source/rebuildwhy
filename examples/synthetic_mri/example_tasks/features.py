"""Extract deterministic summary features from normalized voxels."""

from example_tasks.common import context, read_json, write_json


def main() -> None:
    ctx = context()
    image = read_json(ctx["artifacts"]["normalize:normalized.json"])
    values = image["voxels"]
    threshold = ctx["configs"]["config/pipeline.yaml#/features/threshold"]
    features = {
        "count": len(values),
        "mean": sum(values) / len(values),
        "above_threshold": sum(value > threshold for value in values),
        "threshold": threshold,
    }
    write_json(ctx["output_directory"], "features.json", features)


if __name__ == "__main__":
    main()
