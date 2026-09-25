"""Provider-specific text adapters. Never fall back to another paid service."""


class RequestRejected(Exception):
    """Provider explicitly rejected the request before successful generation."""
