"""Validate and ingest a tiny synthetic voxel array."""

from example_tasks.common import context, read_json, write_json


def main() -> None:
    ctx = context()
    image = read_json(ctx["files"]["data/synthetic_image.json"])
    expected = image["dimensions"][0] * image["dimensions"][1] * image["dimensions"][2]
    if expected != len(image["voxels"]):
        raise ValueError("Voxel count does not match the declared dimensions.")
    write_json(ctx["output_directory"], "image.json", image)
    write_json(
        ctx["output_directory"],
        "metadata.json",
        {"subject_label": ctx["configs"]["config/pipeline.yaml#/ingest/subject_label"]},
    )


if __name__ == "__main__":
    main()
