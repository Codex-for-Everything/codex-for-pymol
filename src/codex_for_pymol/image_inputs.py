"""Private, bounded image attachments for Codex user turns."""

import uuid
from dataclasses import dataclass
from pathlib import Path

from pymol.Qt import QtCore, QtGui

from .executor import _ensure_private_directory, _secure_file


MAX_DRAFT_IMAGES = 4
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000
MAX_EDGE = 4096
MAX_NORMALIZED_BYTES = 32 * 1024 * 1024
MAX_STORED_BYTES = 200 * 1024 * 1024
SUPPORTED_SOURCE_FORMATS = frozenset(
    (b"png", b"jpeg", b"jpg", b"webp", b"gif", b"bmp", b"tif", b"tiff")
)


class ImageInputError(ValueError):
    """Image attachment error with a stable localization code."""

    def __init__(self, code, detail=""):
        super().__init__(detail or code)
        self.code = str(code)
        self.detail = str(detail or "")


@dataclass(frozen=True)
class ImageAttachment:
    """One normalized image kept alive for the current Codex thread."""

    attachment_id: str
    path: str
    width: int
    height: int
    byte_count: int


class ImageAttachmentStore:
    """Normalize user-selected images into a private per-thread directory."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self._attachments = {}

    def add_file(self, source_path):
        source = Path(source_path)
        try:
            byte_count = source.stat().st_size
        except OSError as exc:
            raise ImageInputError("unreadable", str(exc))
        if not source.is_file():
            raise ImageInputError("unreadable", str(source))
        if byte_count > MAX_SOURCE_BYTES:
            raise ImageInputError("source_too_large")

        reader = QtGui.QImageReader(str(source))
        reader.setAutoTransform(True)
        image_format = bytes(reader.format()).lower()
        if image_format not in SUPPORTED_SOURCE_FORMATS:
            raise ImageInputError("unsupported")
        if reader.imageCount() > 1:
            raise ImageInputError("animated")
        size = reader.size()
        if not size.isValid() or size.width() <= 0 or size.height() <= 0:
            raise ImageInputError("unreadable", reader.errorString())
        if size.width() * size.height() > MAX_SOURCE_PIXELS:
            raise ImageInputError("dimensions_too_large")
        if max(size.width(), size.height()) > MAX_EDGE:
            reader.setScaledSize(
                size.scaled(
                    QtCore.QSize(MAX_EDGE, MAX_EDGE),
                    QtCore.Qt.KeepAspectRatio,
                )
            )

        image = reader.read()
        if image.isNull():
            raise ImageInputError("unreadable", reader.errorString())
        return self.add_image(image)

    def add_image(self, image):
        if isinstance(image, QtGui.QPixmap):
            image = image.toImage()
        if not isinstance(image, QtGui.QImage) or image.isNull():
            raise ImageInputError("unreadable")
        width = int(image.width())
        height = int(image.height())
        if width <= 0 or height <= 0:
            raise ImageInputError("unreadable")
        if width * height > MAX_SOURCE_PIXELS:
            raise ImageInputError("dimensions_too_large")

        normalized = image
        if max(width, height) > MAX_EDGE:
            normalized = normalized.scaled(
                MAX_EDGE,
                MAX_EDGE,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        if normalized.isNull():
            raise ImageInputError("unreadable")
        normalized = self._copy_pixels(normalized)

        _ensure_private_directory(self.directory)
        attachment_id = uuid.uuid4().hex
        path = self.directory / ("image-{}.png".format(attachment_id))
        try:
            normalized = self._save_bounded_png(normalized, path)
            byte_count = path.stat().st_size
            if self.total_bytes() + byte_count > MAX_STORED_BYTES:
                raise ImageInputError("storage_limit")
            _secure_file(path)
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass
            raise

        attachment = ImageAttachment(
            attachment_id=attachment_id,
            path=str(path),
            width=int(normalized.width()),
            height=int(normalized.height()),
            byte_count=int(byte_count),
        )
        self._attachments[attachment_id] = attachment
        return attachment

    @staticmethod
    def _copy_pixels(image):
        """Copy pixels without carrying source text, profile, or scale metadata."""
        clean = QtGui.QImage(
            image.width(),
            image.height(),
            QtGui.QImage.Format_ARGB32,
        )
        clean.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(clean)
        try:
            painter.setCompositionMode(
                QtGui.QPainter.CompositionMode_Source
            )
            painter.drawImage(clean.rect(), image, image.rect())
        finally:
            painter.end()
        return clean

    def _save_bounded_png(self, image, path):
        candidate = image
        for _attempt in range(4):
            if not candidate.save(str(path), "PNG"):
                raise ImageInputError("save_failed")
            try:
                byte_count = path.stat().st_size
            except OSError as exc:
                raise ImageInputError("save_failed", str(exc))
            if byte_count <= MAX_NORMALIZED_BYTES:
                return candidate
            next_width = max(1, int(candidate.width() * 0.75))
            next_height = max(1, int(candidate.height() * 0.75))
            if next_width == candidate.width() and next_height == candidate.height():
                break
            candidate = candidate.scaled(
                next_width,
                next_height,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        raise ImageInputError("normalized_too_large")

    def total_bytes(self):
        return sum(item.byte_count for item in self._attachments.values())

    def discard(self, attachment):
        attachment_id = getattr(attachment, "attachment_id", "")
        stored = self._attachments.pop(attachment_id, None)
        if stored is None:
            return False
        try:
            Path(stored.path).unlink()
        except OSError:
            pass
        return True

    def clear(self):
        for attachment in list(self._attachments.values()):
            self.discard(attachment)
        try:
            self.directory.rmdir()
        except OSError:
            pass
