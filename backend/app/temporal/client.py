from temporalio.client import Client

from app.config import settings

_client: Client | None = None


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(settings.temporal_address)
    return _client


def workflow_id_for_run(run_id: str) -> str:
    return f"order-supervisor-{run_id}"
