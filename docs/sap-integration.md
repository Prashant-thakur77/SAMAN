# SAP integration: how SAMAN reaches the material master

SAMAN's consolidation is worth nothing until the buyer's own system carries
the national code. This document is the whole story of how that happens, what
is built, what is a contract for a basis team to fill, and what has not been
run against a live SAP system. It is written for the people who will ask.

## The three doors into SAP

A CPSE's SAP system offers three ways to change a material master, and a
rollout uses all three at different moments.

| Door | When | What SAMAN provides |
|---|---|---|
| **Load files** (LSMW recording or an LTMC / Migration Cockpit project) | The first bulk rollout, run by the basis team in a maintenance window | `GET /api/migration/loadfiles`: a zip of `crossref.csv`, `block.csv`, `held.csv` and a README, in SAP field names, one row per planned change |
| **RFC** (BAPIs over the SAP NetWeaver RFC SDK) | Ongoing batches after go-live, applied from the Migration screen | `RfcErpAdapter` in `app/erp.py`, selected with `SAMAN_ERP_ADAPTER=rfc` |
| **A hook at material creation** (BAdI on MM01 / Fiori "Create Material") | Every day, for every new material, to stop duplicates being born | `POST /api/smart-create/check`, called by the BAdI with an API key |

The mock SAP that ships with the demo is a SQLite file shaped like the five
tables a consolidation touches (MARA, MAKT, EKPO, MARD, MBEW). It exists so
the staged write-back (plan, dry run, impact, apply, verify, rollback) can be
demonstrated and tested end to end. Everything above the adapter is the same
code whichever door is used.

## The adapter contract

`ErpAdapter` (`app/erp.py`) names the eight operations a connector must
provide. The migration engine calls nothing else.

| Operation | Mock (SQLite) | RFC adapter (SAP) |
|---|---|---|
| `read_masters(matnrs)` | `SELECT * FROM mara` | `RFC_READ_TABLE` on MARA: MATNR, MTART, MEINS, LVORM and the two customer fields |
| `read_open_transactions(matnrs)` | EKPO open quantity, MARD stock, MBEW valuation | `RFC_READ_TABLE` on EKPO (`LOEKZ = ''` and `ELIKZ = ''`: not deleted, delivery not complete), MARD LABST, MBEW VERPR and SALK3 |
| `write_crossref(matnr, cnmc)` | `UPDATE mara SET zz_cnmc` | `BAPI_MATERIAL_SAVEDATA` with `EXTENSIONIN` carrying the customer field, then `BAPI_TRANSACTION_COMMIT` |
| `block_material(matnr, supersedes)` | `UPDATE mara SET lvorm = 'X', zz_supersedes` | `BAPI_MATERIAL_SAVEDATA` with `CLIENTDATA-DEL_FLAG = 'X'` and the customer field, then commit |
| `restore(matnr, before)` | Put the before-image back | The same BAPI with the before-image's flag and fields |
| `*_many` bulk forms | One transaction, one `executemany` | One BAPI call per material inside one logical unit of work, one commit per batch |

Two rules hold in both: a superseded material is **blocked, never deleted**
(the deletion flag is set; the row, its texts and its history stay), and a
material with open purchase order lines is **held**, never changed underneath
a live order.

### The customer fields

SAP has no standard field for "the national code this material maps to".
The convention used here is an append structure on MARA with two fields,
`ZZ_CNMC` (CHAR 20) and `ZZ_SUPERSEDES` (CHAR 18), exposed to the BAPI
through `BAPI_TE_MARA` / `BAPI_TE_MARAX`. Their names are configurable
(`SAP_CNMC_FIELD`, `SAP_SUPERSEDES_FIELD`) because every CPSE's namespace is
its own. An alternative some sites prefer is a classification characteristic
(CL20N); the adapter does not implement that today and the docs say so.

### Configuration

```
SAMAN_ERP_ADAPTER=rfc          # default: mock
SAP_ASHOST=sap.cpcl.internal   # application server
SAP_SYSNR=00
SAP_CLIENT=100
SAP_USER=SAMAN_RFC             # a technical user with S_RFC and MM authorisations
SAP_PASSWD=...
SAP_CNMC_FIELD=ZZ_CNMC
SAP_SUPERSEDES_FIELD=ZZ_SUPERSEDES
```

`pyrfc` (SAP's Python connector, Apache-2.0) needs the proprietary SAP
NetWeaver RFC SDK on the machine. It is not installed by `make setup` and
cannot be: the SDK is downloaded from SAP under the customer's own licence.
When `rfc` is requested and the connector or the SDK is missing, SAMAN falls
back to the mock and reports it at `/api/health` under `erp`, exactly as it
does for every other optional engine.

## The hook: stopping duplicates at MM01

Every other part of SAMAN cleans up duplicates that already exist. The hook
stops them being created, inside the transaction where they are created.

SAP MM ships the BAdI `BADI_MATERIAL_CHECK` (method `CHECK_DATA`), called on
every material master save. An implementation calls SAMAN's Smart-Create
check with the description being typed, and turns a strong match into a
warning or an error. The call is a plain HTTPS POST with an API key:

```
POST https://saman.cpcl.internal/api/smart-create/check
X-SAMAN-Key: <key>
Content-Type: application/json

{"description": "BRG,BALL,6205ZZ,SKF", "uom": "EA"}
```

The key is configured on the SAMAN side as `SAMAN_API_KEYS="<user email>=<key>"`,
mapped to a user created for the integration (a steward of that CPSE), so
every check the hook makes is attributed and scoped like a person's would be.

The ABAP shape, abridged:

```abap
METHOD if_ex_badi_material_check~check_data.
  DATA(lo_client) = cl_http_client=>create_by_url( 'https://saman.cpcl.internal/api/smart-create/check' ).
  lo_client->request->set_method( 'POST' ).
  lo_client->request->set_header_field( name = 'X-SAMAN-Key' value = lv_key ).
  lo_client->request->set_header_field( name = 'Content-Type' value = 'application/json' ).
  lo_client->request->set_cdata( |\{"description": "{ wmara-maktx }", "uom": "{ wmara-meins }"\}| ).
  lo_client->send( ).
  lo_client->receive( ).
  " parse recommendation.action; "reuse" with a strong match raises a warning
  " naming the existing material; the buyer may proceed with a reason, which
  " SAMAN records as an override in its audit chain.
ENDMETHOD.
```

The response carries the same three answers the Smart-Create screen shows:
already in the catalogue, interchangeable parts, and checked-and-ruled-out
with the attribute that refused each.

## Rollout sequence

1. **Onboard.** Each CPSE exports its material master (MARA + MAKT, plus
   EKPO/MARD/MBEW extracts for impact) and uploads it; column names in SAP
   style are recognised.
2. **Run and review.** The pipeline, the Workbench, and code issue at the
   registrar.
3. **Plan and dry-run** on the Migration screen. Held and conflicting rows
   are visible before anything is written.
4. **First rollout by load file.** Download the zip, hand it to the basis
   team, apply in a maintenance window through LSMW or LTMC. `verify` then
   re-reads the ERP against the journal.
5. **Switch on the hook** so no new duplicates are born.
6. **Ongoing batches by RFC**, applied and rolled back from the screen.

## What has not been done

The RFC adapter has been written against the connector's documented call
shapes and tested with a fake connection that records the calls. It has
**not** been run against a live SAP system; no SAP system was available to
this build. The load-file layout is a documented CSV in SAP field names, not
an LTMC template of a specific S/4HANA release; the first mapping is the basis
team's, done once. The BAdI code above is the shape, not a transport.
