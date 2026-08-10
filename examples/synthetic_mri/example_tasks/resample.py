"""Apply a deterministic synthetic resampling transform."""

from example_tasks.common import context, read_json, write_json


def main() -> None:
    ctx = context()
    image = read_json(ctx["artifacts"]["ingest:image.json"])
    spacing = ctx["configs"]["config/pipeline.yaml#/image/spacing"]
    method = ctx["configs"]["config/pipeline.yaml#/interpolation/method"]
    # This small demonstration preserves voxel bytes. Method and spacing are
    # provenance metadata, which makes same-content downstream reuse visible.
    write_json(ctx["output_directory"], "image.json", image)
    write_json(
        ctx["output_directory"],
        "metadata.json",
        {"interpolation": method, "spacing": spacing},
    )


if __name__ == "__main__":
    main()
