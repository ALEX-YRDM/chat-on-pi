class ServiceError(Exception):
    """An expected failure safe to display to a LAN user."""
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code
