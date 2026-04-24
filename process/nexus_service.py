import base64

from datetime import datetime
from kmd_nexus_client import NexusClientManager
from kmd_nexus_client.tree_helpers import filter_by_path
from kmd_nexus_client.utils import sanitize_cpr
from xflow_client import ProcessClient, DocumentClient
from automation_server_client import WorkItemError
from process.config import get_excel_mapping


class NexusService:
    def __init__(
        self,
        nexus_client: NexusClientManager,
        xflow_process_client: ProcessClient,
        xflow_document_client: DocumentClient,
    ):
        self.nexus = nexus_client
        self.xflow_process = xflow_process_client
        self.xflow_document = xflow_document_client

    def _hent_sagsområde(self, hjælpemiddel: str) -> str | None:
        regler = get_excel_mapping()
        sagsområder = regler.get("XFlow - Nexus oversættelse", {})
        hjælpemiddelstype = hjælpemiddel.strip()

        if hjælpemiddelstype in sagsområder:
            sagsområde = sagsområder[hjælpemiddelstype]
        elif "Andet" in sagsområder:
            sagsområde = sagsområder["Andet"]
        else:
            return None

        return sagsområde

    def _hent_ansvarlig_organisation(self, item_data: dict) -> str:
        regler = get_excel_mapping()
        hjælpemiddelstype = item_data["Hjælpemiddel"].split("-")[0].strip()
        organisationer = regler.get("Opgaveansvarlig organisation", {})

        if hjælpemiddelstype in organisationer:
            organisation = organisationer[hjælpemiddelstype]
        elif "Andet" in organisationer:
            organisation = organisationer["Andet"]
        else:
            raise WorkItemError(
                f"Opgaveansvarlig organisation for '{hjælpemiddelstype}' ikke fundet."
            )

        return organisation

    def hent_borger(self, cpr: str) -> dict:
        cpr = sanitize_cpr(cpr)
        borger = self.nexus.borgere.hent_borger(cpr)

        if borger is None:
            self.nexus.borgere.opret_borger(borger_cpr=cpr)
            borger = self.nexus.borgere.hent_borger(cpr)
        elif borger.get("patientStatus") == "DRAFT":
            borger = self.nexus.borgere.aktiver_borger_fra_kladde(borger)

        if borger is None:
            raise WorkItemError(f"Borger med CPR {cpr} kunne ikke oprettes i Nexus.")

        return borger

    def tilføj_borger_til_organisation(self, borger: dict, organisation_navn: str):
        organisation = self.nexus.organisationer.hent_organisation_ved_navn(
            organisation_navn
        )

        if organisation is None:
            raise WorkItemError(
                f"Organisation '{organisation_navn}' ikke fundet i Nexus."
            )

        self.nexus.organisationer.tilføj_borger_til_organisation(
            borger=borger, organisation=organisation
        )

    def tilføj_forløb_til_borger(self, borger: dict) -> dict:
        self.nexus.forløb.opret_forløb(
            borger=borger,
            grundforløb_navn="Ældre og sundhedsfagligt grundforløb",
            forløb_navn="Sag SOFF: Kropsbårne hjælpemidler",
        )

        visning = self.nexus.borgere.hent_visning(borger)
        assert visning is not None

        referencer = self.nexus.borgere.hent_referencer(visning)
        assert referencer is not None
        forløb = filter_by_path(
            referencer,
            "/Ældre og sundhedsfagligt grundforløb/Sag SOFF: Kropsbårne hjælpemidler",
            active_pathways_only=True,
        )

        forløb = self.nexus.hent_fra_reference(forløb[0])

        if forløb is None:
            raise WorkItemError(
                "Forløb 'Sag SOFF: Kropsbårne hjælpemidler' for borger kunne ikke hentes i Nexus."
            )

        return forløb

    def upload_arbejdsgang_og_vedhæftede_filer(
        self, borger: dict, forløb: dict, item_data: dict
    ):
        try:
            arbejdsgang_som_pdf = self.xflow_process.create_process_pdf(
                item_data["ProcesId"]
            )

            if arbejdsgang_som_pdf is None:
                raise WorkItemError(
                    f"Arbejdsgang med ID {item_data['ProcesId']} kunne ikke hentes som PDF fra Xflow."
                )

            self.nexus.forløb.opret_dokument(
                borger=borger,
                forløb=forløb,
                fil=arbejdsgang_som_pdf,
                filnavn="ansøgning.pdf",
                titel=f"{'Genansøgning' if item_data['Genansøgning'] else 'Ansøgning'} {item_data['Hjælpemiddel']}",
                noter="",
                modtaget=datetime.now(),
                indholdstype="application/pdf",
            )

            for dokument_id in item_data["DokumentIds"]:
                dokument_data = self.xflow_document.hent_dokument_med_metadata(
                    dokument_id
                )

                if dokument_data is None:
                    raise WorkItemError(
                        f"Dokument med ID {dokument_id} kunne ikke hentes fra Xflow."
                    )

                byte_array_b64 = dokument_data.get("byteArray")
                if byte_array_b64 is not None:
                    try:
                        byte_array = base64.b64decode(byte_array_b64)
                    except Exception as decode_err:
                        raise WorkItemError(
                            f"Fejl ved base64-dekodning af dokument med ID {dokument_id}: {decode_err}"
                        )

                if byte_array is None:
                    raise WorkItemError(
                        f"Dokument med ID {dokument_id} indeholder ingen data."
                    )

                self.nexus.forløb.opret_dokument(
                    borger=borger,
                    forløb=forløb,
                    fil=byte_array,
                    filnavn=f"{dokument_data['filename']}",
                    titel=dokument_data["filename"],
                    noter="",
                    modtaget=datetime.now(),
                    indholdstype=dokument_data["contentType"],
                )
        except Exception as e:
            raise WorkItemError(
                f"Fejl ved upload af arbejdsgang og vedhæftede filer til borger i Nexus: {e}"
            )

    def opret_henvendelsesskema_og_opgave(self, borger: dict, item_data: dict) -> None:
        ansvarlig_organisation = self._hent_ansvarlig_organisation(item_data)
        sagsområde = self._hent_sagsområde(item_data["Hjælpemiddel"])

        if sagsområde is None:
            raise WorkItemError("Kan ikke finde tilsvarende sagsområde tag i Nexus.")

        skema_data = {
            "Henvendelse modtaget": datetime.now(),
            "Kilde som henvendelses kommer fra": "Borger", # Typo i Nexus
            "Er borgeren indforstået med henvendelsen?": "Ja",
            "Ansvarlig myndighedsorganisation": f"{'Indgangen' if ansvarlig_organisation == 'Sygeplejehjælpemidler' else 'Fysisk Funktionsnedsættelse'}",
            "Henvendelsesårsag": f"{'Genansøgning' if item_data['Genansøgning'] else 'Ansøgning'} - {item_data['Hjælpemiddel']}{' - Vedhæftede filer' if len(item_data['DokumentIds']) > 0 else ''}",
        }

        skema = self.nexus.skemaer.opret_komplet_skema(
            borger=borger,
            skematype_navn="Henvendelse - Kropsbårne hjælpemidler",
            handling_navn="Udfyldt",
            data=skema_data,
            tag_navn=sagsområde,
            grundforløb="Ældre og sundhedsfagligt grundforløb",
            forløb="Sag SOFF: Kropsbårne hjælpemidler",
        )

        if skema is None:
            raise WorkItemError("Henvendelsesskema kunne ikke oprettes i Nexus.")

        # Funny dato format for opgaver pga. underlige arbejdsvaner.
        self.nexus.opgaver.opret_opgave(
            objekt=skema,
            opgave_type="Myndighed Kropsbårne hjælpemidler - uden opgavefrist",
            titel=f"{datetime.now().strftime('%y%m%d')} - {'Genansøgning' if item_data['Genansøgning'] else 'Ansøgning'} - {item_data['Hjælpemiddel']}",
            ansvarlig_organisation=ansvarlig_organisation,
            start_dato=datetime.now(),
        )

    def opret_sagsnotat_og_sagsbehandling(self, borger: dict, item_data: dict) -> None:
        sagsområde = self._hent_sagsområde(item_data["Hjælpemiddel"])

        if sagsområde is None:
            raise WorkItemError("Kan ikke finde tilsvarende sagsområde tag i Nexus.")

        sagsnotat_data = {
            "Emne": f"{datetime.now().strftime('%d%m%y')} {'Genansøgning' if item_data['Genansøgning'] else 'Ansøgning'} - {item_data['Hjælpemiddel']}",
            "Tekst": f"{datetime.now().strftime('%d%m%y')} {'Genansøgning' if item_data['Genansøgning'] else 'Ansøgning'} - {item_data['Hjælpemiddel']}",
        }

        self.nexus.skemaer.opret_komplet_skema(
            borger=borger,
            skematype_navn="Sagsnotat - NY",
            handling_navn="Udfyldt",
            data=sagsnotat_data,
            tag_navn=sagsområde,
            grundforløb="Ældre og sundhedsfagligt grundforløb",
            forløb="Sag SOFF: Kropsbårne hjælpemidler",
        )

        sagsbehandling_data = {
            "Ansøgning modtaget": datetime.now(),
            "Vurdering": f"{datetime.now().strftime('%d%m%y')} {'Genansøgning' if item_data['Genansøgning'] else 'Ansøgning'} - {item_data['Hjælpemiddel']}",
        }

        self.nexus.skemaer.opret_komplet_skema(
            borger=borger,
            skematype_navn="Kropsbårne hjælpemidler sagsbehandling",
            handling_navn="Udfyldt",
            data=sagsbehandling_data,
            tag_navn=sagsområde,
            grundforløb="Ældre og sundhedsfagligt grundforløb",
            forløb="Sag SOFF: Kropsbårne hjælpemidler",
        )
