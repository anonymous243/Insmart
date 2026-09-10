from typing import Dict, Type
from app.services.integrations.base_adapter import BaseAdapter
from app.services.integrations.rest_adapter import RESTAdapter
from app.services.integrations.file_adapter import FileAdapter
from app.services.integrations.sftp_adapter import SFTPAdapter

_ADAPTERS: Dict[str, Type[BaseAdapter]] = {
    "REST_API": RESTAdapter,
    "API": RESTAdapter,
    "FILE": FileAdapter,
    "SFTP": SFTPAdapter,
}

def get_adapter(integration_type: str) -> BaseAdapter:
    """
    Returns an instance of the integration adapter for the given integration type.
    """
    adapter_class = _ADAPTERS.get(integration_type)
    if not adapter_class:
        raise ValueError(f"Unsupported integration type: {integration_type}")
    return adapter_class()
