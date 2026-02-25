from __future__ import annotations


class PublishError(Exception):
    pass


class TransientPublishError(PublishError):
    def __init__(self, message: str, code: str = "TRANSIENT_ERROR") -> None:
        super().__init__(message)
        self.code = code


class PermanentPublishError(PublishError):
    def __init__(self, message: str, code: str = "PERMANENT_ERROR") -> None:
        super().__init__(message)
        self.code = code
