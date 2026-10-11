"""Read-only, lossless archive of documented FreshBooks resources.

Endpoint sources: https://www.freshbooks.com/api/ (resource reference pages).
The manifest is deliberately partial whenever a request or coverage check fails.
"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import os
import re
from threading import RLock
from math import ceil
from urllib.parse import urlparse

import requests
from concurrent.futures import ThreadPoolExecutor
from .client import PAGE_SIZE
from cli_tools_shared.exceptions import ClientError


# name, API path, collection key, detail key, includes, visibility filtering
ACCOUNT_RESOURCES = [
    ("clients", "users/clients", "clients", "client", "recent_contacts,outstanding_balance,credit_balance,draft_balance,overdue_balance,grand_total_balance,last_activity,late_reminders,late_fee", True),
    ("invoices", "invoices/invoices", "invoices", "invoice", "lines,contacts,audit_logs,client_audits,comments,owner,latest_journal_entry,allowed_gateways,late_fee,presentation,project_total_amounts,late_reminders,system", True),
    ("payments", "payments/payments", "payments", "payment", "invoice", True),
    ("credits", "credit_notes/credit_notes", "credit_notes", "credit_note", "lines", True),
    ("expenses", "expenses/expenses", "expenses", "expense", "attachment,category,expense_profile,project,account", True),
    ("estimates", "estimates/estimates", "estimates", "estimate", "attachments,lines,contacts,audit_logs,comments,owner,presentation,project,invoices,system", True),
    ("invoice_profiles", "invoice_profiles/invoice_profiles", "invoice_profiles", "invoice_profile", "lines,contacts,allowed_gateways,presentation,system,tracking,next_issue_date", True),
    ("items", "items/items", "items", "item", "", True),
    ("taxes", "taxes/taxes", "taxes", "tax", "", False),
    ("expense_categories", "expenses/categories", "categories", "category", "", True),
    ("bills", "bills/bills", "bills", "bill", "", True),
    ("bill_vendors", "bill_vendors/bill_vendors", "bill_vendors", "bill_vendor", "", True),
    ("bill_payments", "bill_payments/bill_payments", "bill_payments", "bill_payment", "", True),
    ("other_income", "other_incomes/other_incomes", "other_income", "other_income", "", True),
    ("staff", "users/staffs", "staff", "staff", "", True),
    ("tasks", "projects/tasks", "tasks", "task", "", True),
    ("gateways", "systems/gateways", "gateways", None, "", False),
]


def safe_id(value):
    if value is None:
        raise ClientError("Missing resource identifier")
    value = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ClientError("Unsafe or missing resource identifier")
    return value


def payload(data):
    """Unwrap accounting endpoints; other documented APIs return a direct object."""
    if not isinstance(data, dict):
        raise ClientError("Expected JSON object")
    result = data.get("response", data)
    if isinstance(result, dict):
        result = result.get("result", result)
    if not isinstance(result, dict):
        raise ClientError("Expected response object")
    return result


class Exporter:
    def __init__(self, client, output, resume=False):
        self.client = client
        self.lock = RLock()
        self.root = Path(output).expanduser().absolute()
        self.cached_files = {}
        if resume:
            previous = json.loads((self.root / "manifest.json").read_text())
            if previous.get("schema_version") != 1:
                raise ClientError("Unsupported archive schema")
            self.cached_files = previous["files"]
            for name, metadata in self.cached_files.items():
                path = self.root / name
                if not path.resolve().is_relative_to(self.root.resolve()) or path.is_symlink():
                    raise ClientError("Unsafe archived path")
                if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
                    raise ClientError(f"Archived file checksum mismatch: {name}")
        else:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.manifest = {
            "schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running", "resources": [], "files": dict(self.cached_files), "gaps": [],
            "coverage": "Documented API resources accessible to the current OAuth identity; not a full FreshBooks database backup.",
            "decimal_encoding": "Raw response bytes are unchanged. Derived JSON arrays encode non-integer JSON numbers as exact decimal strings.",
        }
        self.save_manifest()

    def write(self, relative, data):
        with self.lock:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            for parent in path.parents:
                if parent == self.root.parent:
                    break
                parent.chmod(0o700)
            encoded = data if isinstance(data, bytes) else json.dumps(data, indent=2, ensure_ascii=False, default=str).encode()
            temporary = path.with_name(path.name + ".tmp")
            with temporary.open("wb") as stream:
                os.chmod(temporary, 0o600)
                stream.write(encoded)
            os.replace(temporary, path)
            if relative != "manifest.json":
                self.manifest["files"][relative] = {"bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}
            return path

    def save_manifest(self):
        self.write("manifest.json", self.manifest)

    def get(self, endpoint, relative, params=None):
        request = {"endpoint": endpoint, "params": list(params or [])}
        signature = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        # Reuse only responses with the exact recorded endpoint/query contract.
        # Identity is always refreshed to reject a different signed-in user.
        if relative != "identity.json" and self.cached_files.get(relative, {}).get("request_sha256") == signature:
            return json.loads((self.root / relative).read_bytes(), parse_float=Decimal)
        response = self.client._make_request("GET", endpoint, params=params, raw_response=True, extra_headers={"x-api-version": "2023-09-25"} if endpoint.endswith("/journal_entries") else None)
        if relative == "identity.json" and relative in self.cached_files:
            old = payload(json.loads((self.root / relative).read_bytes()))
            new = payload(json.loads(response.content))
            if old.get("id") != new.get("id") or new.get("id") is None:
                raise ClientError("Resume refused: signed-in FreshBooks identity differs from archive")
        self.write(relative, response.content)
        with self.lock:
            self.manifest["files"][relative]["request_sha256"] = signature
            self.manifest["files"][relative]["request"] = request
        return json.loads(response.content, parse_float=Decimal)

    def failure(self, entry, phase, exc):
        entry["status"] = "partial"
        entry.setdefault("failures", []).append({"phase": phase, "error": str(exc)})
        self.save_manifest()

    def collection(self, folder, endpoint, key, detail_key=None, includes="", variants=None, detail_endpoint=None, page_parameter="page", size_parameter="per_page"):
        entry = {"path": folder, "endpoint": endpoint, "status": "running", "count": 0, "variants": [], "detail_count": 0}
        self.manifest["resources"].append(entry)
        records = {}
        params = [("include[]", item) for item in includes.split(",") if item]
        for label, extra in (variants or [("default", [])]):
            variant = {"name": label, "pages": 0, "count": 0, "total": None}
            entry["variants"].append(variant)
            page = 1
            seen = set()
            try:
                while True:
                    data = self.get(endpoint, f"{folder}/pages/{label}-{page:05}.json", params + extra + [(page_parameter, page), (size_parameter, PAGE_SIZE)])
                    body = data if isinstance(data.get("response"), list) else payload(data)
                    batch = body.get(key)
                    if not isinstance(batch, list):
                        raise ClientError(f"Missing collection key: {key}; available keys: {sorted(body)}")
                    meta = body.get("meta", body.get("page") if isinstance(body.get("page"), dict) else body)
                    total, pages = meta.get("total"), meta.get("pages")
                    if pages is None and total is not None and meta.get("per_page"):
                        pages = ceil(int(total) / int(meta["per_page"]))
                    if total is None or pages is None:
                        raise ClientError("Missing pagination total/pages; cannot prove complete export")
                    total, pages = int(total), int(pages)
                    if variant["total"] is not None and total != variant["total"]:
                        raise ClientError("Collection total changed during export")
                    variant.update(total=total, pages=page)
                    for row in batch:
                        identifier = row.get("id", row.get("uuid"))
                        if identifier is None:
                            raise ClientError("Record has no id/uuid")
                        identifier = safe_id(identifier)
                        if identifier in seen:
                            raise ClientError("Repeated record across pages")
                        seen.add(identifier)
                        if identifier in records:
                            self.failure(entry, f"list:{label}", ClientError("Visibility variants overlap; server may have ignored filter"))
                        records[identifier] = row
                    variant["count"] = len(seen)
                    if page >= pages:
                        if len(seen) != total:
                            raise ClientError(f"Pagination count mismatch: received {len(seen)}, expected {total}")
                        break
                    if not batch:
                        raise ClientError("Empty page before final page")
                    page += 1
            except (ClientError, requests.RequestException, ValueError, TypeError) as exc:
                self.failure(entry, f"list:{label}", exc)
        self.write(f"{folder}/records.json", list(records.values()))
        entry["count"] = len(records)
        self.save_manifest()
        if detail_key:
            def read_detail(identifier):
                try:
                    data = self.get(f"{detail_endpoint or endpoint}/{identifier}", f"{folder}/details/{identifier}.json", params)
                    detail = payload(data).get(detail_key)
                    if not isinstance(detail, dict):
                        raise ClientError(f"Missing detail key: {detail_key}")
                    return identifier, detail, None
                except (ClientError, requests.RequestException, ValueError, TypeError) as exc:
                    return identifier, None, exc
            with ThreadPoolExecutor(max_workers=4) as pool:
                for identifier, detail, error in pool.map(read_detail, records):
                    if error:
                        self.failure(entry, f"detail:{identifier}", error)
                    else:
                        records[identifier] = detail
                        entry["detail_count"] += 1
                    if entry["detail_count"] % 50 == 0:
                        self.save_manifest()
            self.write(f"{folder}/records.json", list(records.values()))
        if entry["status"] == "running":
            entry["status"] = "exported"
        self.save_manifest()
        return list(records.values())

    def singleton(self, folder, endpoint, params=None):
        entry = {"path": folder, "endpoint": endpoint, "status": "exported"}
        self.manifest["resources"].append(entry)
        try:
            data = self.get(endpoint, folder + "/record.json", params)
            self.save_manifest()
            return data
        except (ClientError, requests.RequestException, ValueError) as exc:
            self.failure(entry, "get", exc)
            return None

    def reports(self, account, business, found, me):
        """Export report snapshots over the observed lifetime, in every source currency."""
        uuid = safe_id(business["business_uuid"])
        dates = [str(me.get("created_at", ""))[:10], datetime.now(timezone.utc).date().isoformat()]
        currencies = set()
        for rows in found.values():
            for row in rows:
                dates.extend(str(row.get(key, ""))[:10] for key in ("date", "create_date", "created_at"))
                code = row.get("currency_code") or (row.get("amount") or {}).get("code")
                if code:
                    currencies.add(code)
        dates = [date for date in dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)]
        self.manifest.setdefault("report_ranges", {})[account] = {"start_date": min(dates), "end_date": max(dates), "currencies": sorted(currencies)}
        self.collection(f"businesses/{business['id']}/journal_entries", f"/accounting/businesses/{uuid}/journal_entries", "manualJournalEntries", page_parameter="page_number", size_parameter="page_size")
        reports = {
            "payments_collected": f"/accounting/account/{account}/reports/accounting/payments_collected",
            "taxsummary": f"/accounting/account/{account}/reports/accounting/taxsummary",
            "invoice_details": f"/accounting/account/{account}/reports/accounting/invoice_details",
            "accounts_aging": f"/accounting/account/{account}/reports/accounting/accounts_aging",
        }
        for name in ("chart_of_accounts", "general_ledger", "manual_journal_entry_report", "profit_and_loss", "trial_balance", "balance_sheet", "cash_flow", "expense_details"):
            reports[name] = f"/accounting/businesses/{uuid}/reports/{name}"
        for code in sorted(currencies):
            for name, endpoint in reports.items():
                params = [("start_date", min(dates)), ("end_date", max(dates)), ("currency_code", code)]
                if name in ("chart_of_accounts", "profit_and_loss", "trial_balance", "balance_sheet"):
                    params.append(("use_ledger_entries", "true"))
                if name == "balance_sheet":
                    params = [("date1", max(dates)), ("currency_code", code), ("use_ledger_entries", "true")]
                self.singleton(f"accounts/{account}/reports/{name}/{safe_id(code)}", endpoint, params)

    def binaries(self, account, invoices, expenses, estimates):
        entry = {"path": f"accounts/{account}/documents", "status": "exported", "pdf_count": 0, "attachment_count": 0}
        self.manifest["resources"].append(entry)
        old_account = self.client.account_id
        self.client.account_id = account
        try:
            def read_pdf(invoice):
                identifier = safe_id(invoice.get("id", invoice.get("uuid")))
                try:
                    relative = f"{entry['path']}/invoices/{identifier}.pdf"
                    content = (self.root / relative).read_bytes() if relative in self.cached_files else self.client.download_invoice_pdf(identifier)
                    if not content.startswith(b"%PDF-"):
                        raise ClientError("Invoice document is not PDF")
                    self.write(relative, content)
                    return identifier, None
                except (ClientError, requests.RequestException) as exc:
                    return identifier, exc
            with ThreadPoolExecutor(max_workers=4) as pool:
                for identifier, error in pool.map(read_pdf, invoices):
                    if error:
                        self.failure(entry, f"pdf:{identifier}", error)
                    else:
                        entry["pdf_count"] += 1
                    self.save_manifest()
            jobs = []
            for kind, rows in [("invoices", invoices), ("expenses", expenses), ("estimates", estimates)]:
                for row in rows:
                    attachments = row.get("attachments") or ([row["attachment"]] if row.get("attachment") else [])
                    if not isinstance(attachments, list):
                        self.failure(entry, f"attachments:{kind}", ClientError("Expected attachment list; metadata preserved"))
                        continue
                    for index, attachment in enumerate(attachments):
                        jobs.append((kind, safe_id(row.get("id", row.get("uuid"))), index, attachment))

            def read_attachment(job):
                kind, identifier, index, attachment = job
                phase = f"attachment:{kind}:{identifier}:{index}"
                try:
                    if not isinstance(attachment, dict):
                        raise ClientError("Expected attachment object; metadata preserved")
                    url = attachment.get("url") or attachment.get("link")
                    if not url and attachment.get("jwt"):
                        # The official upload response documents this signed link
                        # shape; it serves PDF attachments as well as images.
                        url = "https://my.freshbooks.com/service/uploads/images/" + attachment["jwt"]
                    parsed = urlparse(url or "")
                    if parsed.scheme != "https" or not (parsed.hostname == "freshbooks.com" or (parsed.hostname or "").endswith(".freshbooks.com")):
                        raise ClientError("Attachment has no approved FreshBooks HTTPS download URL; metadata preserved")
                    suffix = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "text/html": ".html"}.get(attachment.get("media_type"), ".bin")
                    relative = f"{entry['path']}/{kind}/{identifier}-attachment-{index}{suffix}"
                    if relative not in self.cached_files:
                        response = requests.get(url, timeout=60)
                        response.raise_for_status()
                        if response.headers.get("Content-Type", "").split(";")[0] == "text/html" and attachment.get("media_type") != "text/html":
                            raise ClientError("Attachment returned HTML instead of document bytes")
                        self.write(relative, response.content)
                    return phase, None
                except (ClientError, requests.RequestException) as exc:
                    return phase, exc
            with ThreadPoolExecutor(max_workers=4) as pool:
                for phase, error in pool.map(read_attachment, jobs):
                    if error:
                        self.failure(entry, phase, error)
                    else:
                        entry["attachment_count"] += 1
                    self.save_manifest()
        finally:
            self.client.account_id = old_account
        self.save_manifest()

    def run(self):
        identity = self.get("/auth/api/v1/users/me", "identity.json")
        me = payload(identity)
        memberships = me.get("business_memberships")
        if not isinstance(memberships, list):
            raise ClientError("Identity lacks business_memberships")
        accounts = set()
        documents = []
        visibility = [(str(state), [("search[vis_state]", state)]) for state in (0, 1, 2)]
        for membership in memberships:
            business = membership["business"]
            bid = safe_id(business["id"])
            account = business.get("account_id")
            account = safe_id(account) if account else None
            if account and account not in accounts:
                accounts.add(account)
                found = {}
                for name, suffix, key, detail, includes, visible in ACCOUNT_RESOURCES:
                    variants = visibility[:2] if name in ("payments", "invoice_profiles") else visibility
                    found[name] = self.collection(f"accounts/{account}/{name}", f"/accounting/account/{account}/{suffix}", key, detail, includes, variants if visible else None)
                attachment_rows = self.collection(
                    f"accounts/{account}/invoice_attachments", f"/accounting/account/{account}/invoices/invoices",
                    "invoices", includes="attachments", variants=visibility,
                )
                attachments_by_id = {safe_id(row.get("id", row.get("uuid"))): row.get("attachments") for row in attachment_rows}
                for invoice in found["invoices"]:
                    if attachments_by_id.get(safe_id(invoice.get("id", invoice.get("uuid")))) is not None:
                        invoice["attachments"] = attachments_by_id[safe_id(invoice.get("id", invoice.get("uuid")))]
                self.write(f"accounts/{account}/invoices/records.json", found["invoices"])
                # System's identifier is its account ID per the Systems reference.
                self.singleton(f"accounts/{account}/system", f"/accounting/account/{account}/systems/systems/{account}")
                self.reports(account, business, found, me)
                documents.append((account, found["invoices"], found["expenses"], found["estimates"]))
            self.collection(f"businesses/{bid}/projects", f"/projects/business/{bid}/projects", "projects", "project", variants=[("active", [("active", "true")]), ("inactive", [("active", "false")])], detail_endpoint=f"/projects/business/{bid}/project")
            self.collection(f"businesses/{bid}/time_entries", f"/timetracking/business/{bid}/time_entries", "time_entries", "time_entry", variants=[("all", [("include_deleted", "true"), ("team", "true"), ("include_unlogged", "true")])])
            services = self.collection(f"businesses/{bid}/services", f"/comments/business/{bid}/services", "services", "service", detail_endpoint=f"/comments/business/{bid}/service")
            for service in services:
                sid = safe_id(service.get("id", service.get("uuid")))
                self.singleton(f"businesses/{bid}/service_rates/{sid}", f"/comments/business/{bid}/service/{sid}/rate")
            self.collection(f"businesses/{bid}/team_members", f"/auth/api/v1/businesses/{bid}/team_members", "response")
        self.manifest["resumed"] = bool(self.cached_files)
        self.manifest["account_count"] = len(accounts)
        self.manifest["business_count"] = len(memberships)
        for args in documents:
            self.binaries(*args)
        self.manifest["gaps"].extend([
            {"resource": "estimate_and_credit_pdfs", "status": "unsupported", "reason": "The official public API reference does not document original PDF download endpoints for estimates or credits. Complete raw records and included lines are archived; these document PDFs are not exported."},
            {"resource": "nonpublic_data", "status": "unsupported", "reason": "No universal API export exists. Bank reconciliation feeds, payroll, mileage, proposals, saved payment instruments, subscription history, account-wide audit history and nonpublic application settings are not covered by this resource catalog."},
            {"resource": "attachments", "status": "limited", "reason": "Downloads cover attachment URLs and signed JWT links returned with invoices, expenses and estimates; no standalone attachment inventory endpoint is documented."},
        ])
        self.manifest["status"] = "partial" if self.manifest["gaps"] or any(e["status"] != "exported" for e in self.manifest["resources"]) else "complete"
        self.manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.save_manifest()
        return {"output": str(self.root), "status": self.manifest["status"], "account_count": len(accounts), "resource_count": len(self.manifest["resources"]), "manifest": str(self.root / "manifest.json")}
