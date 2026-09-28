# Opret digital ansøgning til personlige hjælpemidler

Automatisering der behandler afsluttede XFlow-arbejdsgange for ansøgninger om kropsbårne hjælpemidler og opretter tilhørende sag i KMD Nexus.

## Hvad gør robotten?

1. **Henter afsluttede arbejdsgange** fra XFlow (proces-skabelon for "Kropsbårne hjælpemidler") der står i aktiviteten `RPAIntegration`
2. **Udtrækker data** fra ansøgningens blanketter (CPR-nummer, hjælpemiddel, evt. genansøgning, vedhæftede dokumenter)
3. **Opretter eller finder borgeren** i KMD Nexus og tilføjer borgeren til "Team Kropsbårne hjælpemidler"
4. **Opretter forløb** "Sag SOFF: Kropsbårne hjælpemidler" på borgeren
5. **Uploader** arbejdsgangen som PDF samt eventuelle vedhæftede filer til forløbet
6. **Opretter henvendelsesskema og opgave** i Nexus, mappet til korrekt sagsområde og ansvarlig organisation via regelsættet (`Regler.xlsx`)
7. **Opretter sagsnotat og sagsbehandlingsskema** (springes over hvis hjælpemidlet er "Andet")
8. **Opdaterer og avancerer arbejdsgangen** i XFlow med resultatet (succes/fejl), så sagen kan fortsætte eller gå til manuel behandling

## Forudsætninger

- Python ≥ 3.13
- [`uv`](https://docs.astral.sh/uv/) til pakkehåndtering
- Adgang til **Automation Server** (arbejdskø)
- Adgang til **KMD Nexus** (produktion)
- Adgang til **XFlow** (produktion)
- En **Odense SQL Server**-konto til tracking

## Konfiguration

Kopiér `.env.example` til `.env` og udfyld variablerne ifølge `automation-server-client`-dokumentationen.

Følgende credentials skal være tilgængelige via Automation Server:

| Credential                    | Beskrivelse                          |
| ------------------------------ | ------------------------------------- |
| `KMD Nexus - produktion`      | Client ID/secret + Nexus-instans     |
| `Xflow - produktion`          | Token + XFlow-instans                |
| `Odense SQL Server`           | Bruger til aktivitetssporing         |

## Kørsel

```sh
# Fyld arbejdskøen med afsluttede XFlow-arbejdsgange
uv run python main.py --queue

# Behandl arbejdskøen
uv run python main.py
```

| Argument             | Beskrivelse                                                  |
| -------------------- | ------------------------------------------------------------- |
| `--excel-file <sti>` | Tilsidesæt stien til `Regler.xlsx` (default: `./Regler.xlsx`) |
| `--queue`            | Fyld arbejdskøen og afslut (kør ingen behandling)             |

## Regelopsætning (`Regler.xlsx`)

Excel-filen indeholder regneark der bruges som opslag ved kørsel:

- **XFlow - Nexus oversættelse** – Mapping fra hjælpemiddeltype til sagsområde/tag i Nexus
- **Opgaveansvarlig organisation** – Mapping fra hjælpemiddeltype til ansvarlig organisation for opgaven i Nexus

## Afhængigheder

| Pakke                       | Formål                        |
| ---------------------------- | ------------------------------ |
| `automation-server-client`  | Arbejdskø-håndtering           |
| `kmd-nexus-client`          | Integration med KMD Nexus      |
| `xflow-client`              | Integration med XFlow          |
| `odk-tools`                 | Aktivitetssporing              |
| `openpyxl`                  | Læsning af Excel-regelsæt      |

## Sikkerhed og persondata

Robotten behandler følsomme personoplysninger på vegne af Odense Kommune, herunder CPR-numre og oplysninger om funktionsnedsættelse (særlige kategorier jf. GDPR art. 9).

- Ingen personoplysninger må lægges i dette repository — hverken som testdata, i kode eller i kommentarer
- Legitimationsoplysninger håndteres udelukkende via miljøvariabler (`.env`) og Automation Server Credentials
