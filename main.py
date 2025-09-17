import sys
import asyncio
import logging

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

def tilføj_dokument_id_på_uploaded_dokumenter(source, vedhæftede_filer, felt_navn):
    source_list = [e for e in source if isinstance(e, dict) and e.get("identifier") == felt_navn]
    vedhæftede_filer_element = source_list[0].get("values", {}) if source_list else None
    if vedhæftede_filer_element is not None:
        for key, value in vedhæftede_filer_element.items():
            if key.startswith("document") and is_non_empty(value):
                vedhæftede_filer.append(value)

def is_non_empty(val):
    if val is None:
        return False
    if isinstance(val, (dict, list)) and not val:
        return False
    if isinstance(val, str) and not val.strip():
        return False
    return True

def extract_referable_elements_with_values(element):
    children = []
    for child in element.get("children", []):
        child_result = extract_referable_elements_with_values(child)
        if child_result is not None:
            children.append(child_result)
    if is_non_empty(element.get("values")):
        result = {
            "identifier": element.get("identifier"),
            "values": element.get("values")
        }
        if children:
            result["children"] = children
        return result
    # If this element has no values, but children do, return the children directly (flatten)
    if children:
        if len(children) == 1:
            return children[0]
        return children
    return None

def traverse_json_for_referable_elements(obj):
    results = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "elementer" and isinstance(value, list):
                for element in value:
                    res = extract_referable_elements_with_values(element)
                    if res is not None:
                        if isinstance(res, list):
                            results.extend(res)
                        else:
                            results.append(res)
            else:
                results.extend(traverse_json_for_referable_elements(value))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(traverse_json_for_referable_elements(item))
    return results


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

    afsluttede_processer = xflow_process_client.search_processes_by_current_activity(
        query=xlow_søge_query,
        activity_name="Slut"
    )
        
    for proces in afsluttede_processer:
        blanketter = proces["blanketter"]

        samlet_ansøgning = [b for b in blanketter if b["blanketnavn"] == "Kropsbårne hjælpemidler - samlet ansøgning V2"]
        person_oplysninger = [b for b in blanketter if b["blanketnavn"] == "Kropsbårne hjælpemidler - Personoplysninger V2"]

        filtreret_ansøgning = traverse_json_for_referable_elements(samlet_ansøgning[0])
        filtreret_person_oplysninger = traverse_json_for_referable_elements(person_oplysninger[0])
        
        paa_vegne_af_valg = [e for e in filtreret_person_oplysninger if e["identifier"] == "PaaVegneAfValg"][0]

        children = paa_vegne_af_valg.get("children")[0]
        if isinstance(children, list):
            personoplysninger_child = next(
                (child for child in children if isinstance(child, dict) and child.get("identifier") == "PersonoplysningerAnsoegerVedAndenPart" or child.get("identifier") == "PersonoplysningerAnsoegerSelv"),
                None
            )
        else:
            personoplysninger_child = None

        cpr = personoplysninger_child.get("values", {}).get("CprNummer") if personoplysninger_child else None
        genansøgning = next((e.get("values", {}).get("YesSelected") for e in filtreret_ansøgning if e.get("identifier") == "HarDuTidligereSoegt"), None)
        
        vedhæftede_filer = []

        bemærkninger_og_vedhæft_filer_list = [e for e in filtreret_ansøgning if e.get("identifier") == "BemærkningerOgVedhaeftFiler"]
        bemærkninger_og_vedhæft_filer = bemærkninger_og_vedhæft_filer_list[0].get("children", {}) if bemærkninger_og_vedhæft_filer_list else None
        if isinstance(bemærkninger_og_vedhæft_filer, list) and len(bemærkninger_og_vedhæft_filer) > 0:
            bemærkninger_og_vedhæft_filer = bemærkninger_og_vedhæft_filer[0]
            tilføj_dokument_id_på_uploaded_dokumenter(bemærkninger_og_vedhæft_filer, vedhæftede_filer, "UploadBilag")

        dokumentation = [e for e in filtreret_person_oplysninger if e.get("identifier") == "Dokumentation"]
        dokumentation = dokumentation[0].get("children", {}) if dokumentation else None
        if isinstance(dokumentation, list) and len(dokumentation) > 0:
            dokumentation = dokumentation[0]
            tilføj_dokument_id_på_uploaded_dokumenter(dokumentation, vedhæftede_filer, "UploadBilag")
        
        kødata = {
            "Cpr": cpr,            
            "Genansøgning": genansøgning if genansøgning is not None else False,
            #TODO: Hjælpemiddel
            "DokumentIds": vedhæftede_filer,
            "ProcesId": proces["publicId"]
        }

        memes = ""


async def process_workqueue(workqueue: Workqueue):
    logger = logging.getLogger(__name__)

    logger.info("Hello from process workqueue!")

    for item in workqueue:
        with item:
            data = item.data  # Item data deserialized from json as dict
 
            try:
                # Indlæs regelsæt
                # Indlæs blanket data og parse
                # Hent borger
                    # Findes borger ikke i Nexus, så opret

                # Opret henvendelsesskema
                # Upload blanket som pdf til forløb
                # Er Andet true?
                    # Opret konkret opgave type.
                # Opret dokumenter (sagsnotat, sagsbehandling, PDF af blanketter)
                # 
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

