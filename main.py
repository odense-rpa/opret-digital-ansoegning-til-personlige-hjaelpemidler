import sys
import asyncio
import logging

from datetime import datetime, timedelta
from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential
from kmd_nexus_client import NexusClientManager
from xflow_client import XFlowClient, ProcessClient
from odk_tools.tracking import Tracker
from odk_tools.reporting import Reporter
from xflow_processor import XFlowProcessor

nexus: NexusClientManager
xflow_client: XFlowClient
xflow_process_client: ProcessClient
tracker: Tracker
reporter: Reporter
xflow_processor = XFlowProcessor()

async def populate_queue(workqueue: Workqueue):
    xlow_søge_query = {
        "text": "",
        "processTemplateIds": [
            "726" #372
        ],
        "startIndex": 0,        
        "createdDateFrom": (datetime.today() - timedelta(days=1)).strftime('%d-%m-%Y'),
        "createdDateTo":  datetime.today().strftime('%d-%m-%Y'),
    }

    afsluttede_arbejdsgange = xflow_process_client.search_processes_by_current_activity(
        query=xlow_søge_query,
        activity_name="Slut" # TODO: Bør være RPAIntegration efter modificeret arbejdsgang
    )
        
    for arbejdsgang in afsluttede_arbejdsgange:
        kødata = xflow_processor.hent_dataudtræk_til_kødata(arbejdsgang)

        if kødata is not None:
            workqueue.add_item(data=kødata, reference=f"{kødata['ProcesId']}")


async def process_workqueue(workqueue: Workqueue):    

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict
 
            try:
                # Indlæs regelsæt
                # Indlæs blanket data og parse
                # Hent borger
                    # Findes borger ikke i Nexus, så opret
                # Check om borger har Sundhedsfagligt grundforløb > FSIII evt. Opret forløb
                # Tilknyt borger til organisation Team Kropsbårne hjælpemidler
                # Opret henvendelsesskema
                    # Opret henvendelsesskema V5
                    # Udfyld simple felter, flet hjælpemiddel deltajer ind i årsag til henvendelse og sagsbehandlingsforløb.
                    # Er der vedhæftede filer, så noter dette.
                # Upload vedhæftede dokumenter til forløb Korrespondace - Personlige hjælpemidler. Opret dette forløb, hvis det ikke findes.
                # Upload arbejdsgangen som pdf til samme forløb
                
                # Er Andet true?
                    # Opret konkret opgave type.
                # Ellers:
                    # Opret dokumenter (sagsnotat, sagsbehandling)
                # TODO: Undersøg om vi kan paste HTML indhold
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

