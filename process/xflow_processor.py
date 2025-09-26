from xflow_client import ProcessClient
from datetime import datetime
from kmd_nexus_client.tree_helpers import (
    filter_by_predicate,    
)

class XFlowProcessor:
    def is_non_empty(self, val):
        if val is None:
            return False
        if isinstance(val, (dict, list)) and not val:
            return False
        if isinstance(val, str) and not val.strip():
            return False
        return True

    def tilfoej_dokument_id_paa_uploaded_dokumenter(self, source, vedhaeftede_filer, felt_navn):
        source_list = [e for e in source if isinstance(e, dict) and e.get("identifier") == felt_navn]
        vedhaeftede_filer_element = source_list[0].get("values", {}) if source_list else None
        if vedhaeftede_filer_element is not None:
            for key, value in vedhaeftede_filer_element.items():
                if key.startswith("document") and self.is_non_empty(value):
                    vedhaeftede_filer.append(value)

    def extract_referable_elements_with_values(self, element):
        children = []
        for child in element.get("children", []):
            child_result = self.extract_referable_elements_with_values(child)
            if child_result is not None:
                children.append(child_result)
        if self.is_non_empty(element.get("values")):
            result = {
                "identifier": element.get("identifier"),
                "values": element.get("values")
            }
            if children:
                result["children"] = children
            return result
        if children:
            if len(children) == 1:
                return children[0]
            return children
        return None

    def traverse_json_for_referable_elements(self, obj):
        results = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "elementer" and isinstance(value, list):
                    for element in value:
                        res = self.extract_referable_elements_with_values(element)
                        if res is not None:
                            if isinstance(res, list):
                                results.extend(res)
                            else:
                                results.append(res)
                else:
                    results.extend(self.traverse_json_for_referable_elements(value))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(self.traverse_json_for_referable_elements(item))
        return results

    def hent_dataudtræk_til_kødata(self, arbejdsgang, xflow_process_client: ProcessClient) -> dict|None:
        try:
            blanketter = arbejdsgang["blanketter"]

            samlet_ansøgning = filter_by_predicate(
                roots=blanketter,
                predicate=lambda x: x["blanketnavn"] == "Kropsbårne hjælpemidler - samlet ansøgning V3 - Værdiliste"
            )
            person_oplysninger = filter_by_predicate(
                roots=blanketter,
                predicate=lambda x: x["blanketnavn"] == "Kropsbårne hjælpemidler - Personoplysninger V2"
            )
            filtreret_ansøgning = self.traverse_json_for_referable_elements(samlet_ansøgning[0])
            filtreret_person_oplysninger = self.traverse_json_for_referable_elements(person_oplysninger[0])

            hjælpemiddel = str(xflow_process_client.find_process_element_value(arbejdsgang, "ElementVaerdilisteTypeHjaelpemiddel", "Valgtetekst"))

            cpr = filter_by_predicate(
                roots=person_oplysninger[0]["elementer"],
                predicate=lambda x: x.get("identifier") in ("PersonoplysningerAnsoegerVedAndenPart", "PersonoplysningerAnsoegerSelv")
            )
            cpr = cpr[0].get("values", {}).get("CprNummer") if cpr else None

            genansøgning = next((e.get("values", {}).get("YesSelected") for e in filtreret_ansøgning if e.get("identifier") == "HarDuTidligereSoegt"), None)
            
            vedhæftede_filer = []

            bemærkninger_og_vedhæft_filer_list = [e for e in filtreret_ansøgning if e.get("identifier") == "BemærkningerOgVedhaeftFiler"]
            bemærkninger_og_vedhæft_filer = bemærkninger_og_vedhæft_filer_list[0].get("children", {}) if bemærkninger_og_vedhæft_filer_list else None
            if isinstance(bemærkninger_og_vedhæft_filer, list) and len(bemærkninger_og_vedhæft_filer) > 0:
                bemærkninger_og_vedhæft_filer = bemærkninger_og_vedhæft_filer[0]
                self.tilfoej_dokument_id_paa_uploaded_dokumenter(bemærkninger_og_vedhæft_filer, vedhæftede_filer, "UploadBilag")

            dokumentation = [e for e in filtreret_person_oplysninger if e.get("identifier") == "Dokumentation"]
            dokumentation = dokumentation[0].get("children", {}) if dokumentation else None
            if isinstance(dokumentation, list) and len(dokumentation) > 0:
                dokumentation = dokumentation[0]
                self.tilfoej_dokument_id_paa_uploaded_dokumenter(dokumentation, vedhæftede_filer, "UploadDokumentationVaerge")

            # TODO: Debug cpr:
            cpr = "010858-9995"

            kødata = {
                "Cpr": cpr,
                "Genansøgning": genansøgning if genansøgning is not None else False,
                "Hjælpemiddel": hjælpemiddel,
                "DokumentIds": vedhæftede_filer,
                "ProcesId": arbejdsgang["publicId"]
            }
            
            return kødata

        except Exception as e:
            return None
        
    def opdater_og_avancer_arbejdsgang(self, item_data: dict, succes: bool, xflow_process_client: ProcessClient):
        blanket_data = {
            "formValues": [
                {
                    "elementIdentifier": "RPASignatur",
                    "valueIdentifier": "Tekst",
                    "value": "Behandlet af Tyra (RPA)"      
                },
                {
                    "elementIdentifier": "RPABehandletDato",
                    "valueIdentifier": "Dato",
                    "value": datetime.today().strftime('%d-%m-%Y')      
                },
                {
                    "elementIdentifier": "ProcesVidereYesNo",
                    "valueIdentifier": "YesSelected",
                    "value": str(succes)     
                }
            ]        
        }

        xflow_process_client.update_process(item_data["ProcesId"], blanket_data)
        xflow_process_client.advance_process(process_id=item_data["ProcesId"])
        