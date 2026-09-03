import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import settings
from app.db.session import init_db
from app.temporal.activities import (
    classify_event_activity,
    generate_final_summary_activity,
    record_activity,
    run_agent_activity,
    update_run_state,
)
from app.temporal.workflow import OrderSupervisorWorkflow

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    init_db()
    client = await Client.connect(settings.temporal_address)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[OrderSupervisorWorkflow],
        # Activities are synchronous (blocking LLM/DB calls) and run in this
        # thread pool so they never block the worker's asyncio event loop.
        activity_executor=ThreadPoolExecutor(max_workers=20),
        activities=[
            record_activity,
            update_run_state,
            classify_event_activity,
            run_agent_activity,
            generate_final_summary_activity,
        ],
    )
    logging.info("Worker started on task queue %s", settings.temporal_task_queue)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
