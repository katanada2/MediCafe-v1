# Capability and authority-transfer map

Status: planning inventory. V0 signals below summarize the historical discovery supplied for this project; current runtime wiring, production data, and migration completeness have not been re-audited. Target ownership is accepted direction, not evidence of a completed replacement.

Public code implements these owners. Their real data and operational credentials belong to private deployments.

| Capability / historical signal | V1 owner and handoff | Foundation evidence | Remaining decision or qualification |
| --- | --- | --- | --- |
| CSV/DOCX intake: normalization, filtering, source correlation | sources retains bytes, delivery keys, parser versions, locators and observations | F1 duplicate, changed source, malformed row, parser failure | Full real source-format inventory and retention policy |
| Identity: several external namespaces and ambiguous joins | records owns patients, aliases, distinct encounters and explicit resolution decisions | F1 exact alias suggestion, manual resolution, same-day distinct encounter, wrong organization | Historical alias collisions, patient merge/split and correction after downstream effects |
| Coverage: dated API observations and selected applicability | Future coverage responsibility initially colocated with records; accepted policy references flow to claims | F2 only explicitly synthetic policy fixtures | Source precedence, benefit-period applicability, expiry and payer rules |
| Service preparation: observed suggestions differ from accepted corrections | records owns approved service decisions and versioned corrections; claims consumes a fixed selection | F2 correction persists across reparse; Decimal amounts; stale approval | Actual coding, pricing, multiple-line and specialty semantics |
| Claims: selected membership and operation-specific routing matter | claims owns revision, approval, route and payload identity | F2 exact selected lines; F3 receiver independently observes bytes | Actual 837P mappings, payer enrollment and certified transport |
| Delivery: pre-dispatch and unknown effect differ | claims owns intent/attempt; adapter supplies observations, not permission | F3 crash, duplicate pickup, no-idempotency unknown result | Provider idempotency/readback contracts and authorized resubmission policy |
| Inbound lifecycle: status is distinct from payment evidence | outcomes owns received observations and attribution | F4 duplicate and mismatched acknowledgment/remittance | Provider response families, corrections, denials and follow-up policy |
| Financial results: ERA and reconciliation are not bank settlement | outcomes owns accepted postings, adjustments and reconciliation after cutover | F4 bounded synthetic posting and unmatched review | Opening balances, posting rules, reversals, COB and patient liability |
| Patient responsibility and communications: incomplete downstream capability | outcomes owns receivable decision; future communications adapter owns delivery observations | Explicitly absent from F1-F4 | Owner policy, consent/channel handling, approval and send recovery |
| Cash: no complete bank-settlement owner established by discovery | Future outcomes extension joins independent EFT/check/deposit evidence | Explicitly absent; no cash-confirmed claim from ERA | Source integration, allocation, deposits, refunds and reconciliation |
| Medisoft archive: current source of many authoritative facts | Adapter consumes versioned V1 projection and records item readback | F4 repeated/partial/unknown export and outage | Actual Medisoft mapping, correction protocol and XP qualification |
| Operations: evidence explanations and unresolved work matter | Each owner exposes queries; UI composes worklists without owning duplicate status | F1 restart, scoped views, reason codes and synthetic sensitive tokens | Production support, backups, monitoring and recovery procedures |

## Medisoft responsibility disposition

Every row remains pending private cutover evidence. No row authorizes querying or writing a live Medisoft installation.

| Responsibility | Target treatment |
| --- | --- |
| Patient demographics and external identifiers | One-time/delta migration into records; collisions go to explicit review |
| Payer and membership associations | Migration into coverage records with source and applicability |
| Diagnosis/procedure bridges and pricing | Reviewed versioned policy and service decisions; no blind migration of inferred rules |
| Service occurrences and charges | Migration into distinct encounters/services with opening-state reconciliation |
| Authoritative claim inputs | Replaced by accepted V1 records and approved claim revisions |
| Submission history and outstanding attempts | Migrate historical facts including unresolved effects; do not re-arm sends |
| Payments, adjustments, balances | Reconcile and migrate into outcomes before transferring financial authority |
| Patient invoice origin | Replacement capability remains a production blocker until specified |
| Medisoft-compatible representation | Delayed archive output and independent readback concern |
| Filesystem/XP discovery as current-truth authority | Obsolete after corresponding transfer; may remain inside archive adapter |

## Gap register

| Gap | Evidence / consequence | Blocks | Minimum resolution |
| --- | --- | --- | --- |
| G1 real intake and correction policy | Synthetic schema cannot prove clinic source coverage | Real intake qualification | Reviewed field examples and supersession decisions, kept private |
| G2 identity and migration population | Legacy aliases may collide; archive data is not automatically canonical | Identity cutover | Population inventory, mapping rules and unresolved-case disposition |
| G3 coding, pricing and coverage policy | Historical behavior does not establish general payer/clinical policy | Actual billable services | Owner-approved rules and independently reviewed examples |
| G4 transport and inbound semantics | Simulated receipts do not establish payer interoperability | Live delivery and automated recovery | Provider contracts, test enrollment, exact payload/receipt acceptance |
| G5 financial replacement | Posting, COB, balances, liability and cash are different authorities | Financial cutover and patient billing | Accepted financial policy and opening-state reconciliation |
| G6 production operations | No deployed IAM, retention, backup, egress or covered-service evidence | Real patient-data deployment | Separate private deployment and recovery qualification |

Independent synthetic F1 work may proceed with every gap open. Later cards must label their fixture policies and unsupported behavior explicitly; no gap is filled by a guessed business rule.
