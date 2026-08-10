"""Normalize synthetic voxels into the interval [0, 1]."""

from example_tasks.common import context, read_json, write_json


def main() -> None:
    ctx = context()
    image = read_json(ctx["artifacts"]["resample:image.json"])
    values = image["voxels"]
    method = ctx["configs"]["config/pipeline.yaml#/normalization/method"]
    if method != "min-max":
        raise ValueError("The demo supports only min-max normalization.")
    low, high = min(values), max(values)
    scale = high - low
    normalized = [0.0 if scale == 0 else (value - low) / scale for value in values]
    write_json(ctx["output_directory"], "normalized.json", {"voxels": normalized})


if __name__ == "__main__":
    main()
