"""Unit tests never implicitly call the configured remote semantic model."""
from campus.app import create_app as actual_create_app


def create_app(*args,**kwargs):
    kwargs.setdefault('enable_semantics',False)
    return actual_create_app(*args,**kwargs)
