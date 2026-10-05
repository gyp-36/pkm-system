"""Supported file extensions and their stable media types."""

IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "bmp", "webp", "tif", "tiff", "ico"})

IMAGE_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "webp": "image/webp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "ico": "image/x-icon",
}

ALLOWED_EXTENSIONS = frozenset({"md", "docx", "xlsx", "pdf", "doc", "xls"}) | IMAGE_EXTENSIONS

MIME_BY_EXT = {
    "md": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    **IMAGE_MIME_BY_EXT,
}

# PIL format names are used to reject files whose extension does not match the
# actual encoded image, while allowing JPEG's two common extensions.
PIL_FORMAT_BY_EXT = {
    "png": {"PNG"},
    "jpg": {"JPEG"},
    "jpeg": {"JPEG"},
    "gif": {"GIF"},
    "bmp": {"BMP"},
    "webp": {"WEBP"},
    "tif": {"TIFF"},
    "tiff": {"TIFF"},
    "ico": {"ICO"},
}
