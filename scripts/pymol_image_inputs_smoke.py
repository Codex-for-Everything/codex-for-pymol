"""Exercise image normalization with a real PyMOL Qt runtime."""

import os
import stat
import tempfile
from pathlib import Path

from pymol.Qt import QtGui, QtWidgets

from codex_for_pymol import image_inputs
from codex_for_pymol.image_inputs import ImageAttachmentStore, ImageInputError


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def require_error(code, callback):
    try:
        callback()
    except ImageInputError as error:
        require(
            error.code == code,
            "expected {}, got {}".format(code, error.code),
        )
    else:
        raise RuntimeError("expected image error: {}".format(code))


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    with tempfile.TemporaryDirectory(
        prefix="codex-for-pymol-image-smoke-"
    ) as directory:
        root = Path(directory)
        store = ImageAttachmentStore(root / "attachments")

        source_image = QtGui.QImage(80, 40, QtGui.QImage.Format_ARGB32)
        source_image.fill(QtGui.QColor(12, 140, 170, 127))
        source_image.setText("private-note", "must not survive normalization")
        source_image.setDotsPerMeterX(12345)
        source_image.setDotsPerMeterY(23456)
        source_image.setDevicePixelRatio(2.0)
        if hasattr(QtGui, "QColorSpace"):
            source_image.setColorSpace(
                QtGui.QColorSpace(QtGui.QColorSpace.SRgb)
            )

        source_path = root / "source.png"
        require(source_image.save(str(source_path), "PNG"), "could not save PNG")
        attachment = store.add_file(source_path)
        normalized_path = Path(attachment.path)
        normalized = QtGui.QImage(str(normalized_path))
        require(not normalized.isNull(), "normalized PNG could not be read")
        require(
            normalized_path != source_path
            and normalized_path.suffix == ".png"
            and normalized.size() == source_image.size()
            and normalized.pixelColor(0, 0)
            == source_image.pixelColor(0, 0),
            "normalization changed the path, format, dimensions, or pixels",
        )
        require(
            "private-note" not in normalized.textKeys()
            and normalized.dotsPerMeterX() != 12345
            and normalized.dotsPerMeterY() != 23456
            and normalized.devicePixelRatio() == 1.0,
            "normalized PNG retained source metadata",
        )
        if hasattr(normalized, "colorSpace"):
            require(
                not normalized.colorSpace().isValid(),
                "normalized PNG retained the source color profile",
            )
        if os.name != "nt":
            require(
                stat.S_IMODE(store.directory.stat().st_mode) == 0o700
                and stat.S_IMODE(normalized_path.stat().st_mode) == 0o600,
                "normalized image storage is not private",
            )

        writer_formats = {
            bytes(value).lower()
            for value in QtGui.QImageWriter.supportedImageFormats()
        }
        for suffix, image_format in (
            ("jpg", b"jpeg"),
            ("webp", b"webp"),
            ("bmp", b"bmp"),
            ("tiff", b"tiff"),
        ):
            if image_format not in writer_formats:
                continue
            path = root / ("source." + suffix)
            require(
                source_image.save(str(path), bytes(image_format).decode("ascii")),
                "could not save {}".format(suffix),
            )
            converted = store.add_file(path)
            require(
                Path(converted.path).suffix == ".png"
                and QtGui.QImage(converted.path).size() == source_image.size(),
                "{} input was not normalized".format(suffix),
            )
            store.discard(converted)

        static_gif = root / "static.gif"
        static_gif.write_bytes(
            bytes.fromhex(
                "47494638396101000100800000000000ffffff"
                "21f90400000000002c00000000010001000002024401003b"
            )
        )
        static_attachment = store.add_file(static_gif)
        require(
            QtGui.QImage(static_attachment.path).size()
            == QtGui.QImage(str(static_gif)).size(),
            "static GIF was not normalized",
        )
        store.discard(static_attachment)

        animated_gif = root / "animated.gif"
        animated_gif.write_bytes(
            bytes.fromhex(
                "47494638396101000100800000000000ffffff"
                "21f90400000000002c0000000001000100000202440100"
                "21f90400000000002c00000000010001000002024401003b"
            )
        )
        require_error("animated", lambda: store.add_file(animated_gif))

        unsupported = root / "not-an-image.txt"
        unsupported.write_text("not an image", encoding="utf-8")
        require_error("unsupported", lambda: store.add_file(unsupported))

        oversized_source = root / "too-large.png"
        with oversized_source.open("wb") as handle:
            handle.seek(image_inputs.MAX_SOURCE_BYTES)
            handle.write(b"x")
        require_error(
            "source_too_large",
            lambda: store.add_file(oversized_source),
        )

        previous_pixel_limit = image_inputs.MAX_SOURCE_PIXELS
        try:
            image_inputs.MAX_SOURCE_PIXELS = 1
            require_error(
                "dimensions_too_large",
                lambda: store.add_image(source_image),
            )
        finally:
            image_inputs.MAX_SOURCE_PIXELS = previous_pixel_limit

        wide = QtGui.QImage(
            image_inputs.MAX_EDGE + 1,
            2,
            QtGui.QImage.Format_ARGB32,
        )
        wide.fill(QtGui.QColor("green"))
        downscaled = store.add_image(wide)
        require(
            max(downscaled.width, downscaled.height) == image_inputs.MAX_EDGE,
            "oversized image edge was not bounded",
        )
        store.discard(downscaled)
        wide_path = root / "wide.png"
        require(wide.save(str(wide_path), "PNG"), "could not save wide PNG")
        file_downscaled = store.add_file(wide_path)
        require(
            max(file_downscaled.width, file_downscaled.height)
            == image_inputs.MAX_EDGE,
            "oversized file edge was not bounded during decoding",
        )
        store.discard(file_downscaled)

        previous_normalized_limit = image_inputs.MAX_NORMALIZED_BYTES
        existing_files = set(store.directory.glob("*.png"))
        try:
            image_inputs.MAX_NORMALIZED_BYTES = 0
            require_error(
                "normalized_too_large",
                lambda: store.add_image(source_image),
            )
        finally:
            image_inputs.MAX_NORMALIZED_BYTES = previous_normalized_limit
        require(
            set(store.directory.glob("*.png")) == existing_files,
            "an oversized normalized image was not removed",
        )

        previous_limit = image_inputs.MAX_STORED_BYTES
        try:
            image_inputs.MAX_STORED_BYTES = store.total_bytes()
            require_error(
                "storage_limit",
                lambda: store.add_image(source_image),
            )
        finally:
            image_inputs.MAX_STORED_BYTES = previous_limit
        require(
            set(store.directory.glob("*.png")) == existing_files,
            "a rejected normalized image was not removed",
        )

        store.clear()
        require(
            not store.directory.exists(),
            "image store did not remove its empty private directory",
        )

    print("PyMOL image input smoke test passed")
    del app


if __name__ == "__main__":
    main()
