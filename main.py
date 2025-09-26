import os
import argparse
import sys
import asyncio
import logging

from datetime import datetime, timedelta
from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential, WorkItemStatus
from kmd_nexus_client import NexusClientManager
from xflow_client import XFlowClient, ProcessClient, DocumentClient
from odk_tools.tracking import Tracker
from odk_tools.reporting import Reporter
from process.nexus_service import NexusService
from process.xflow_service import XFlowService
from process.config import load_excel_mapping

nexus: NexusClientManager
xflow_client: XFlowClient
xflow_process_client: ProcessClient
xflow_document_client: DocumentClient
xflow_service: XFlowService
tracker: Tracker
reporter: Reporter
proces_navn = "Opret digital ansøgning til personlige hjælpemidler"


async def populate_queue(workqueue: Workqueue):
    xlow_søge_query = {
        "text": "",
        "processTemplateIds": [
            "744" #372 #726
        ],
        "startIndex": 0,        
        "createdDateFrom": (datetime.today() - timedelta(days=1)).strftime('%d-%m-%Y'),
        "createdDateTo":  datetime.today().strftime('%d-%m-%Y'),
    }

    afsluttede_arbejdsgange = xflow_process_client.search_processes_by_current_activity(
        query=xlow_søge_query,
        activity_name="RPAIntegration"
    )
        
    for arbejdsgang in afsluttede_arbejdsgange:
        eksisterende_kødata = workqueue.get_item_by_reference(arbejdsgang["publicId"])

        if len(eksisterende_kødata) > 0:
            continue

        kødata = xflow_service.hent_dataudtræk_til_kødata(arbejdsgang)

        if kødata is not None:            
            workqueue.add_item(data=kødata, reference=f"{kødata['ProcesId']}")

async def process_workqueue(workqueue: Workqueue):
    for item in workqueue:
        with item:            
            data = item.data
 
            try:                
                borger = nexus_service.hent_borger(data["Cpr"])
                nexus_service.tilføj_borger_til_organisation(borger, "Team Kropsbårne hjælpemidler")
                korrespondance_forløb = nexus_service.tilføj_forløb_til_borger(borger)
                nexus_service.upload_arbejdsgang_og_vedhæftede_filer(borger, korrespondance_forløb, data)   
                nexus_service.opret_henvendelsesskema_og_opgave(borger=borger, item_data=data)

                if (data["Hjælpemiddel"].strip().lower() == "andet"):
                    xflow_service.opdater_og_avancer_arbejdsgang(item_data=data, succes=True, xflow_process_client=xflow_process_client)
                    tracker.track_task(proces_navn)
                    return
                
                nexus_service.opret_sagsnotat_og_sagsbehandling(borger, data)
                xflow_service.opdater_og_avancer_arbejdsgang(item_data=data, succes=True, xflow_process_client=xflow_process_client)
                    
            except WorkItemError as e:                
                xflow_service.opdater_og_avancer_arbejdsgang(item_data=data, succes=False, xflow_process_client=xflow_process_client)
                
                logging.warning(
                    f"Anmodning med id: {data['ProcesId']} er fejlet og overgår til manuel behandling via mail-aflevering. Fejl: {e}"
                )
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
    xflow_document_client = DocumentClient(xflow_client)

    xflow_service = XFlowService(xflow_client, xflow_process_client)
    nexus_service = NexusService(nexus, xflow_process_client=xflow_process_client, xflow_document_client=xflow_document_client)
    
    tracker = Tracker(
        username=tracking_credential.username, 
        password=tracking_credential.password
    )

    reporter = Reporter(
        username=reporting_credential.username,
        password=reporting_credential.password
    )

     # Parse command line arguments
    parser = argparse.ArgumentParser(description=proces_navn)
    parser.add_argument(
        "--excel-file",
        default="./Regler.xlsx",
        help="Path to the Excel file containing mapping data (default: ./Regler.xlsx)",
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Populate the queue with test data and exit",
    )
    args = parser.parse_args()

    # Validate Excel file exists
    if not os.path.isfile(args.excel_file):
        raise FileNotFoundError(f"Excel file not found: {args.excel_file}")

    # Load excel mapping data once on startup
    load_excel_mapping(args.excel_file)

    logger = logging.getLogger(__name__)

    # Queue management
    if "--queue" in sys.argv:
        workqueue.clear_workqueue(WorkItemStatus.NEW)
        asyncio.run(populate_queue(workqueue))
        exit(0)

    # Process workqueue
    asyncio.run(process_workqueue(workqueue))

