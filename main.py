import os
import argparse
import sys
import asyncio
import logging

from datetime import datetime, timedelta
from automation_server_client import AutomationServer, Workqueue, WorkItemError, Credential
from kmd_nexus_client import NexusClientManager
from kmd_nexus_client.tree_helpers import (
    filter_by_path
)
from xflow_client import XFlowClient, ProcessClient, DocumentClient
from odk_tools.tracking import Tracker
from odk_tools.reporting import Reporter
from process.xflow_processor import XFlowProcessor
from process.config import get_excel_mapping, load_excel_mapping

nexus: NexusClientManager
xflow_client: XFlowClient
xflow_process_client: ProcessClient
xflow_document_client: DocumentClient
xflow_processor = XFlowProcessor()
tracker: Tracker
reporter: Reporter
proces_navn = "Opret digital ansøgning til personlige hjælpemidler"


async def populate_queue(workqueue: Workqueue):
    xlow_søge_query = {
        "text": "",
        "processTemplateIds": [
            "372" #372 #726
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
            pass
            #workqueue.add_item(data=kødata, reference=f"{kødata['ProcesId']}")

def hent_borger(cpr: str) -> dict:
    borger = nexus.borgere.hent_borger(cpr)

    if borger is None:
        nexus.borgere.opret_borger(borger_cpr=cpr)
        borger = nexus.borgere.hent_borger(cpr)

    if borger is None:
        raise WorkItemError(f"Borger med CPR {cpr} kunne ikke oprettes i Nexus.")

    return borger

def tilføj_borger_til_organisation(borger: dict, organisation_navn: str):
    organisation = nexus.organisationer.hent_organisation_ved_navn(organisation_navn)

    if organisation is None:
        raise WorkItemError(f"Organisation '{organisation_navn}' ikke fundet i Nexus.")

    nexus.organisationer.tilføj_borger_til_organisation(borger=borger, organisation=organisation)


def tilføj_forløb_til_borger(borger: dict) -> dict:     
    nexus.forløb.opret_forløb(
        borger=borger, 
        grundforløb_navn="Sundhedsfagligt grundforløb",
        forløb_navn="FSIII"
    )

    nexus.forløb.opret_forløb(
        borger=borger, 
        grundforløb_navn="Sundhedsfagligt grundforløb",
        forløb_navn="Korrespondance - Personlige hjælpemidler"
    )

    visning = nexus.borgere.hent_visning(borger)
    assert visning is not None

    referencer = nexus.borgere.hent_referencer(visning)
    assert referencer is not None

    forløb = filter_by_path(
            referencer,
            "/Sundhedsfagligt grundforløb/Korrespondance - Personlige hjælpemidler",
            active_pathways_only=True,
    )
    
    forløb = nexus.hent_fra_reference(forløb[0])

    if forløb is None:
        raise WorkItemError("Forløb 'Korrespondance - Personlige hjælpemidler' for borger kunne ikke hentes i Nexus.")
    
    return forløb

def upload_arbejdsgang_og_vedhæftede_filer(borger: dict, forløb: dict, item_data: dict):
    try:
        arbejdsgang_som_pdf = xflow_process_client.create_process_pdf(item_data["ProcesId"])

        if arbejdsgang_som_pdf is None:
            raise WorkItemError(f"Arbejdsgang med ID {item_data['ProcesId']} kunne ikke hentes som PDF fra Xflow.")

        for dokument_id in item_data["DokumentIds"]:
            dokument_data = xflow_document_client.hent_dokument_med_metadata(dokument_id)
            
            if dokument_data is None:
                raise WorkItemError(f"Dokument med ID {dokument_id} kunne ikke hentes fra Xflow.")
            
            nexus.forløb.opret_dokument(
                borger=borger,
                forløb=forløb,
                fil=dokument_data["byteArray"],
                filnavn=f"{dokument_data["filename"]}.{dokument_data["fileExtension"]}",
                titel=dokument_data["filename"],
                noter="",
                modtaget=datetime.now(),
                indholdstype=dokument_data["contentType"]
            )
    except Exception as e:
        raise WorkItemError(f"Fejl ved upload af arbejdsgang og vedhæftede filer til borger i Nexus: {e}")
       

def opret_henvendelsesskema_og_opgave(borger: dict, item_data: dict) -> None:
    regler = get_excel_mapping()
    
    skema_data = {
        "Henvendelse modtaget": datetime.now().isoformat,
        "Kilde som henveldensel kommer fra": "Borger",
        "Er borgeren indforstået med henvendelsen?": "Ja",
        "Hvad drejer henvendelsen sig om": "§112 kropsbårne",
        "Årsag til henvendelse og sagsbehandlingsforløb (OBS. Husk dato og initialer på noter, og skriv nyeste note nederst)": f"{'Genansøgning' if item_data['Genansøgning'] else 'Ansøgning'} - {item_data["Hjælpemiddel"]} - {'Vedhæftede filer' if len(item_data['DokumentIds']) > 0 else ''}"
    }

    skema = nexus.skemaer.opret_komplet_skema(
        objekt=borger,
        skematype_navn="Henvendelse/sagsåbning hjælpemidler v5",
        handling_navn="Udfyldt",
        data=skema_data,
        grundforløb="Sundhedsfagligt grundforløb",
        forløb="FSIII"        
    )

    if skema is None:
        raise WorkItemError("Henvendelsesskema kunne ikke oprettes i Nexus.")
    
    # TODO: Verificer om skema reference er komplet

    # TODO: Test
    hjælpemiddelstype = item_data["Hjælpemiddel"].split(">")[0].strip()   
    organisation = regler["Opgaveansvarlig organisation"][hjælpemiddelstype]

    nexus.opgaver.opret_opgave(
        objekt=skema,
        opgave_type="Myndighed Kropsbårne hjælpemidler - uden opgavefrist",
        titel=f"{datetime.now().strftime('%d%m%Y/')} - {'Genansøgning' if item_data['Genansøgning'] else 'Ansøgning'} - {item_data['Hjælpemiddel']}",
        ansvarlig_organisation=organisation,
        start_dato=datetime.now()
    )

def opret_sagsnotat_og_sagsbehandling(borger: dict, item_data: dict) -> None:
    sagsnotat_data = {
        "Emne": f"ddmmyyyy, gen/ansøgning hjælpemiddelstype",
        "Tekst": f"ddmmyyyy, gen/ansøgning hjælpemiddelstype"
    }

    sagsnotat = nexus.skemaer.opret_komplet_skema(
        objekt=borger,
        skematype_navn="Sagsnotat - Personlige hjælpemidler V2",
        handling_navn="Udfyldt",
        data=sagsnotat_data,
        grundforløb="Sundhedsfagligt grundforløb",
        forløb="FSIII"        
    )

    sagsbehandling_data = {
        "Angivsagsområde": "",
        "Ansøgning modtaget": datetime.now().isoformat,
        "Vurdering": f"ddmmyyyy, gen/ansøgning hjælpemiddelstype"
    }

    sagsbehandling = nexus.skemaer.opret_komplet_skema(
        objekt=borger,
        skematype_navn="Personlige hjælpemidler sagsbehandling",
        handling_navn="Udfyldt",
        data=sagsbehandling_data,
        grundforløb="Sundhedsfagligt grundforløb",
        forløb="FSIII"        
    )

    # TODO: Verificer om skemaerne oprettes korrekt.

async def process_workqueue(workqueue: Workqueue):
    for item in workqueue:
        with item:            
            data = item.data
 
            try:                
                borger = hent_borger(data["Cpr"])
                tilføj_borger_til_organisation(borger, "Team Kropsbårne hjælpemidler")
                korrespondance_forløb = tilføj_forløb_til_borger(borger)
                upload_arbejdsgang_og_vedhæftede_filer(borger, korrespondance_forløb, data["DokumentIds"])   
                opret_henvendelsesskema_og_opgave(borger=borger, item_data=data)

                if (data["Hjælpemiddel"].strip().lower() == "andet"):
                    #TODO: Advance XFlow Process
                    tracker.track_task(proces_navn)
                    return
                
                opret_sagsnotat_og_sagsbehandling(borger, data)
                # Ellers:
                    # Opret dokumenter (sagsnotat, sagsbehandling)      
                    # 
                #TODO: Advance XFlow Process           
                pass
            except WorkItemError as e:
                # A WorkItemError represents a soft error that indicates the item should be passed to manual processing or a business logic fault
                # Reject XFlow Process
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
        workqueue.clear_workqueue("new")
        asyncio.run(populate_queue(workqueue))
        exit(0)

    # Process workqueue
    asyncio.run(process_workqueue(workqueue))

