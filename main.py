import asyncio
import logging
import sys

from datetime import datetime, timedelta
from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential
from kmd_nexus_client import NexusClientManager
from xflow_client import XFlowClient, ProcessClient
from odk_tools.tracking import Tracker
from odk_tools.reporting import Reporter

nexus: NexusClientManager
xflow_client: XFlowClient
xflow_process_client: ProcessClient
tracker: Tracker
reporter: Reporter

from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential

async def populate_queue(workqueue: Workqueue):
    xlow_søge_query = {
        "text": "ANSØGNING OM KROPSBÅRNE HJÆLPEMIDLER",
        "processTemplateIds": [
            "726"
        ],
        "startIndex": 0,        
        "createdDateFrom": (datetime.today() - timedelta(days=1)).strftime('%d-%m-%Y'),
        "createdDateTo":  datetime.today().strftime('%d-%m-%Y'),
    }

    igangværende_processer = xflow_process_client.search_processes_by_current_activity(
        query=xlow_søge_query,
        activity_name="Slut"
    )

    break_point = ""


async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from process workqueue!")

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict
 
            try:
                # Process the item here
                pass
            except WorkItemError as e:
                # A WorkItemError represents a soft error that indicates the item should be passed to manual processing or a business logic fault
                logger.error(f"Error processing item: {data}. Error: {e}")
                item.fail(str(e))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO        
    )

    ats = AutomationServer.from_environment()
    workqueue = ats.workqueue()

    nexus_credential = Credential.get_credential("KMD Nexus - produktion")    
    xflow_credential = Credential.get_credential("Xflow - produktion")
    tracking_credential = Credential.get_credential("Odense SQL Server")
    reporting_credential = Credential.get_credential("RoboA")
    
    nexus = NexusClientManager(
        client_id=nexus_credential.username,
        client_secret=nexus_credential.password,
        instance=nexus_credential.data["instance"],
    )    

    xflow_client = XFlowClient(
        token=xflow_credential.password,
        instance=xflow_credential.data["instance"],
    )
    xflow_process_client = ProcessClient(xflow_client)
    
    tracker = Tracker(
        username=tracking_credential.username, 
        password=tracking_credential.password
    )

    reporter = Reporter(
        username=reporting_credential.username,
        password=reporting_credential.password
    )

    logger = logging.getLogger(__name__)

    # Queue management
    if "--queue" in sys.argv:
        workqueue.clear_workqueue("new")
        asyncio.run(populate_queue(workqueue))
        exit(0)

    # Process workqueue
    asyncio.run(process_workqueue(workqueue))
