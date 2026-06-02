"""Monarch Money client wrapping the monarchmoney Python SDK."""
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

from gql import gql
from monarchmoney import MonarchMoney
from monarchmoney.monarchmoney import RequireMFAException, LoginFailedException

from .config import get_config

# File to store last institution check timestamp
INSTITUTION_CHECK_FILE = Path.home() / ".config" / "monarch" / "institution_check.json"
INSTITUTION_CHECK_INTERVAL = timedelta(hours=24)
ACCOUNT_STALENESS_THRESHOLD = timedelta(hours=1)


class ClientError(Exception):
    """Custom exception for Monarch client errors."""
    pass


class MonarchClient:
    """Client for interacting with Monarch Money API via SDK."""

    def __init__(self, config=None):
        """Initialize Monarch client from configuration."""
        self.config = config or get_config()
        self._mm: Optional[MonarchMoney] = None
        self._institutions_checked: bool = False

    def _get_mm(self) -> MonarchMoney:
        """Get or create MonarchMoney instance with session loading."""
        if self._mm is None:
            self._mm = MonarchMoney(timeout=120)
            # Try to load existing session from our configured path
            if self.config.has_session():
                try:
                    self._mm.load_session(str(self.config.session_file))
                except Exception:
                    pass  # Session invalid, will need to login
        return self._mm

    def _run_async(self, coro):
        """Run an async coroutine synchronously."""
        return asyncio.run(coro)

    def _query_monarch(self, coro, check_institutions: bool = True) -> Any:
        """
        Central method for all Monarch API queries.

        Performs institution status check before running the query (once per day).
        All API methods should use this instead of _run_async directly.

        Args:
            coro: The async coroutine to execute
            check_institutions: Whether to check for disconnected institutions

        Returns:
            The API response
        """
        # Check status before querying (only once per day)
        if check_institutions and not self._institutions_checked:
            self._check_status()
            self._institutions_checked = True

        return self._run_async(coro)

    def _get_last_institution_check(self) -> Optional[datetime]:
        """Get the timestamp of the last institution check."""
        if not INSTITUTION_CHECK_FILE.exists():
            return None
        try:
            data = json.loads(INSTITUTION_CHECK_FILE.read_text())
            return datetime.fromisoformat(data.get("last_check", ""))
        except (json.JSONDecodeError, ValueError):
            return None

    def _save_institution_check(self) -> None:
        """Save the current timestamp as the last institution check."""
        INSTITUTION_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
        INSTITUTION_CHECK_FILE.write_text(json.dumps({
            "last_check": datetime.now().isoformat()
        }))

    def _check_status(self) -> None:
        """Check institution and account status if not checked recently (within 24 hours)."""
        last_check = self._get_last_institution_check()

        if last_check and (datetime.now() - last_check) < INSTITUTION_CHECK_INTERVAL:
            # Already checked recently, skip
            return

        # Perform the check
        mm = self._get_mm()
        institutions_data = self._run_async(mm.get_institutions())

        credentials = institutions_data.get("credentials", [])
        institutions_needing_update = [
            cred.get("institution", {}).get("name", "Unknown")
            for cred in credentials
            if cred.get("updateRequired", False)
        ]

        # Check for stale account data (last_updated > 1 hour old)
        accounts_data = self._run_async(mm.get_accounts())
        stale_accounts = self._get_stale_accounts(accounts_data)

        # Save check timestamp
        self._save_institution_check()

        if institutions_needing_update:
            inst_list = ", ".join(sorted(set(institutions_needing_update)))
            print(
                f"\n⚠️  WARNING: The following institution(s) require reconnection in Monarch: {inst_list}\n"
                f"   Transactions from these accounts may be incomplete or outdated.\n"
                f"   (Last checked: {datetime.now().strftime('%Y-%m-%d %H:%M')})\n",
                file=sys.stderr
            )

        if stale_accounts:
            acct_list = ", ".join(sorted(stale_accounts))
            print(
                f"🔄 Auto-syncing {len(stale_accounts)} stale account(s)...",
                file=sys.stderr
            )
            self._run_async(mm.request_accounts_refresh_and_wait([]))
            print("✓ Sync complete\n", file=sys.stderr)

    def _get_stale_accounts(self, accounts_data: Dict[str, Any]) -> List[str]:
        """
        Get list of account names with stale data (last_updated > 1 hour old).

        Args:
            accounts_data: Raw accounts data from API

        Returns:
            List of account names with stale data
        """
        from datetime import timezone

        stale_accounts = []
        now = datetime.now(timezone.utc)

        accounts = accounts_data.get("accounts", [])
        for account in accounts:
            if account.get("isHidden", False):
                continue

            last_updated_str = account.get("displayLastUpdatedAt")
            if not last_updated_str:
                continue

            try:
                last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                if (now - last_updated) > ACCOUNT_STALENESS_THRESHOLD:
                    stale_accounts.append(account.get("displayName", account.get("name", "Unknown")))
            except (ValueError, TypeError):
                continue

        return stale_accounts

    # ==================== Auth Methods ====================

    @staticmethod
    def _is_totp_secret(value: str) -> bool:
        """Check if a value looks like a TOTP secret (base32-encoded string).

        TOTP secrets are base32-encoded (A-Z, 2-7, optional = padding).
        One-time codes are typically 6-8 digit numeric strings.
        """
        import re
        stripped = value.strip().replace(" ", "")
        if re.fullmatch(r"\d{6,8}", stripped):
            return False  # Numeric one-time code
        if re.fullmatch(r"[A-Z2-7=]+", stripped, re.IGNORECASE) and len(stripped) >= 16:
            return True  # Base32 TOTP secret
        return False

    def login(self, email: Optional[str] = None, password: Optional[str] = None,
              mfa_code: Optional[str] = None) -> Dict[str, Any]:
        """
        Login to Monarch Money.

        Args:
            email: Email address (uses config if not provided)
            password: Password (uses config if not provided)
            mfa_code: MFA code if required

        Returns:
            Dict with success status and message
        """
        email = email or self.config.email
        password = password or self.config.password

        if not email or not password:
            raise ClientError("Email and password required. Set MONARCH_EMAIL and MONARCH_PASSWORD.")

        mm = self._get_mm()

        session_path = str(self.config.session_file)

        # Determine how to use MFA_SECRET: as TOTP secret key or as one-time code
        mfa_secret = self.config.mfa_secret
        totp_secret = None
        mfa_secret_as_code = None
        if mfa_secret:
            if self._is_totp_secret(mfa_secret):
                totp_secret = mfa_secret
            else:
                # Treat as a one-time MFA code
                mfa_secret_as_code = mfa_secret.strip()

        async def do_login():
            try:
                await mm.login(
                    email=email,
                    password=password,
                    use_saved_session=False,  # We handle session loading in _get_mm
                    save_session=False,  # We'll save manually to our path
                    mfa_secret_key=totp_secret
                )
                # Save session to our configured path
                self.config.session_file.parent.mkdir(parents=True, exist_ok=True)
                mm.save_session(session_path)
                return {"success": True, "message": "Login successful", "mfa_required": False}
            except RequireMFAException:
                # Try stored one-time code, then explicit mfa_code param
                code = mfa_code or mfa_secret_as_code
                if code:
                    await mm.multi_factor_authenticate(email, password, code)
                    # Save session to our configured path
                    self.config.session_file.parent.mkdir(parents=True, exist_ok=True)
                    mm.save_session(session_path)
                    return {"success": True, "message": "Login successful with MFA", "mfa_required": False}
                return {"success": False, "message": "MFA code required", "mfa_required": True}
            except LoginFailedException as e:
                raise ClientError(f"Login failed: {e}")

        return self._run_async(do_login())

    def logout(self) -> Dict[str, Any]:
        """Clear session and credentials."""
        self.config.clear_session()
        self._mm = None
        return {"success": True, "message": "Session cleared"}

    def get_subscription_details(self) -> Dict[str, Any]:
        """Get subscription status to verify authentication."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_subscription_details())

    # ==================== Account Methods ====================

    def get_accounts(self) -> Dict[str, Any]:
        """Get all accounts."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_accounts())

    def get_account_history(self, account_id: str) -> Dict[str, Any]:
        """Get balance history for an account."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_account_history(int(account_id)))

    def get_account_holdings(self, account_id: str) -> Dict[str, Any]:
        """Get securities holdings for a brokerage account."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_account_holdings(int(account_id)))

    def refresh_accounts(self, account_ids: Optional[List[str]] = None, wait: bool = False) -> Dict[str, Any]:
        """
        Trigger account refresh.

        Args:
            account_ids: Specific accounts to refresh (all if None)
            wait: If True, wait for refresh to complete
        """
        mm = self._get_mm()
        ids = account_ids or []
        if wait:
            result = self._query_monarch(mm.request_accounts_refresh_and_wait(ids))
        else:
            result = self._query_monarch(mm.request_accounts_refresh(ids))
        return {"success": True, "result": result}

    # ==================== Transaction Methods ====================

    def get_transactions(
        self,
        limit: int = 100,
        offset: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
        account_ids: Optional[List[str]] = None,
        tag_ids: Optional[List[str]] = None,
        search: str = "",
        needs_review: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Get transactions with server-side filtering.

        Args:
            limit: Max transactions to return
            offset: Pagination offset
            start_date: Filter by start date (YYYY-MM-DD)
            end_date: Filter by end date (YYYY-MM-DD)
            category_ids: Filter by category IDs
            account_ids: Filter by account IDs
            tag_ids: Filter by tag IDs
            search: Search string
            needs_review: If True, only transactions where needsReview == true.
                          If False, only where needsReview == false. If None, no filter.

        Returns:
            Transaction data from API
        """
        mm = self._get_mm()

        # The installed monarchmoney SDK does not forward `needsReview` through its
        # `get_transactions` filter dict. Monarch's GraphQL `TransactionFilterInput`
        # accepts `needsReview: Boolean` (camelCase) — the same pattern used by
        # `hasNotes`, `hideFromReports`, `isRecurring`, `isSplit`, all of which the
        # SDK already plumbs. When the caller asks for the review-status filter we
        # issue the same `GetTransactionsList` operation directly via `gql_call`
        # and inject the field server-side; otherwise we defer to the SDK method
        # so its filter-validation logic (start/end date pairing, etc.) keeps owning
        # the call.
        if needs_review is None:
            return self._query_monarch(mm.get_transactions(
                limit=limit,
                offset=offset,
                start_date=start_date,
                end_date=end_date,
                search=search,
                category_ids=category_ids or [],
                account_ids=account_ids or [],
                tag_ids=tag_ids or []
            ))

        return self._query_monarch(self._get_transactions_with_review(
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
            search=search,
            category_ids=category_ids or [],
            account_ids=account_ids or [],
            tag_ids=tag_ids or [],
            needs_review=needs_review,
        ))

    async def _get_transactions_with_review(
        self,
        limit: int,
        offset: int,
        start_date: Optional[str],
        end_date: Optional[str],
        search: str,
        category_ids: List[str],
        account_ids: List[str],
        tag_ids: List[str],
        needs_review: bool,
    ) -> Dict[str, Any]:
        """Issue GetTransactionsList directly so we can pass needsReview server-side.

        Mirrors `monarchmoney.MonarchMoney.get_transactions` query + variables shape;
        the only delta is the added `needsReview` entry in `filters`.
        """
        if bool(start_date) != bool(end_date):
            raise ClientError(
                "You must specify both --start and --end (or --days), not just one."
            )

        query = gql(
            """
          query GetTransactionsList($offset: Int, $limit: Int, $filters: TransactionFilterInput, $orderBy: TransactionOrdering) {
            allTransactions(filters: $filters) {
              totalCount
              results(offset: $offset, limit: $limit, orderBy: $orderBy) {
                id
                ...TransactionOverviewFields
                __typename
              }
              __typename
            }
            transactionRules {
              id
              __typename
            }
          }

          fragment TransactionOverviewFields on Transaction {
            id
            amount
            pending
            date
            hideFromReports
            plaidName
            notes
            isRecurring
            reviewStatus
            needsReview
            reviewedAt
            reviewedByUser {
              id
              name
              __typename
            }
            attachments {
              id
              extension
              filename
              originalAssetUrl
              publicId
              sizeBytes
              __typename
            }
            isSplitTransaction
            createdAt
            updatedAt
            category {
              id
              name
              __typename
            }
            merchant {
              name
              id
              transactionsCount
              __typename
            }
            account {
              id
              displayName
              __typename
            }
            tags {
              id
              name
              color
              order
              __typename
            }
            __typename
          }
        """
        )

        filters: Dict[str, Any] = {
            "search": search,
            "categories": category_ids,
            "accounts": account_ids,
            "tags": tag_ids,
            "needsReview": needs_review,
        }
        if start_date and end_date:
            filters["startDate"] = start_date
            filters["endDate"] = end_date

        variables = {
            "offset": offset,
            "limit": limit,
            "orderBy": "date",
            "filters": filters,
        }

        mm = self._get_mm()
        return await mm.gql_call(
            operation="GetTransactionsList",
            graphql_query=query,
            variables=variables,
        )

    def get_transaction_details(self, transaction_id: str) -> Dict[str, Any]:
        """Get details for a specific transaction."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_transaction_details(transaction_id))

    def get_recurring_transactions(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get recurring transactions."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_recurring_transactions(
            start_date=start_date,
            end_date=end_date
        ))

    def update_transaction(
        self,
        transaction_id: str,
        category_id: Optional[str] = None,
        merchant_name: Optional[str] = None,
        goal_id: Optional[str] = None,
        amount: Optional[float] = None,
        date: Optional[str] = None,
        hide_from_reports: Optional[bool] = None,
        needs_review: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update a transaction.

        Args:
            transaction_id: ID of the transaction to update
            category_id: New category ID (empty string to keep current)
            merchant_name: New merchant name
            goal_id: New goal ID (empty string to clear)
            amount: New amount
            date: New date (YYYY-MM-DD format)
            hide_from_reports: Whether to hide from reports
            needs_review: Whether transaction needs review
            notes: New notes (empty string to clear)

        Returns:
            Updated transaction data
        """
        mm = self._get_mm()
        return self._query_monarch(mm.update_transaction(
            transaction_id=transaction_id,
            category_id=category_id,
            merchant_name=merchant_name,
            goal_id=goal_id,
            amount=amount,
            date=date,
            hide_from_reports=hide_from_reports,
            needs_review=needs_review,
            notes=notes,
        ))

    # ==================== Category & Tag Methods ====================

    def get_categories(self) -> Dict[str, Any]:
        """Get all transaction categories."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_transaction_categories())

    def get_category_groups(self) -> Dict[str, Any]:
        """Get category groups."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_transaction_category_groups())

    def get_tags(self) -> Dict[str, Any]:
        """Get all transaction tags."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_transaction_tags())

    # ==================== Budget Methods ====================

    def get_budgets(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get budget data."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_budgets(
            start_date=start_date,
            end_date=end_date
        ))

    # ==================== Cashflow Methods ====================

    def get_cashflow(
        self,
        limit: int = 100,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get detailed cashflow data."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_cashflow(
            limit=limit,
            start_date=start_date,
            end_date=end_date
        ))

    def get_cashflow_summary(self) -> Dict[str, Any]:
        """Get cashflow summary (income/expense/savings)."""
        mm = self._get_mm()
        return self._query_monarch(mm.get_cashflow_summary())

    # ==================== Institution Methods ====================

    def get_institutions(self) -> Dict[str, Any]:
        """Get linked financial institutions."""
        mm = self._get_mm()
        # Skip institution check to avoid recursion
        return self._query_monarch(mm.get_institutions(), check_institutions=False)

    # ==================== Rule Methods ====================
    #
    # The monarchmoney SDK does not expose transaction-rule CRUD. We issue the
    # same named GraphQL operations the Monarch web client uses (against
    # `/graphql`) directly through `gql_call`. Create and update share the
    # same envelope shape and payload-error handling, so both go through
    # `_mutate_rule` driven by `_RULE_MUTATIONS`.

    _RULE_FIELDS_FRAGMENT = """
    fragment TransactionRuleFields on TransactionRuleV2 {
      id
      merchantCriteriaUseOriginalStatement
      merchantCriteria { operator value __typename }
      amountCriteria {
        operator isExpense value
        valueRange { lower upper __typename }
        __typename
      }
      categoryIds
      accountIds
      categories { id name icon __typename }
      accounts { id displayName icon logoUrl __typename }
      setMerchantAction { id name __typename }
      setCategoryAction { id name icon __typename }
      addTagsAction { id name color __typename }
      linkGoalAction { id name __typename }
      needsReviewByUserAction { id name __typename }
      unassignNeedsReviewByUserAction
      sendNotificationAction
      setHideFromReportsAction
      reviewStatusAction
      recentApplicationCount
      lastAppliedAt
      splitTransactionsAction {
        amountType
        splitsInfo {
          categoryId merchantName amount goalId tags
          hideFromReports reviewStatus needsReviewByUserId
          __typename
        }
        __typename
      }
      __typename
    }
    """

    _PAYLOAD_ERROR_FRAGMENT = """
    fragment PayloadErrorFields on PayloadError {
      fieldErrors { field messages __typename }
      message code __typename
    }
    """

    # (GraphQL key, Python kwarg) — applies to both create and update.
    _RULE_INPUT_KEYS = (
        ("merchantCriteria", "merchant_criteria"),
        ("amountCriteria", "amount_criteria"),
        ("categoryIds", "category_ids"),
        ("accountIds", "account_ids"),
        ("setCategoryAction", "set_category_action"),
        ("setMerchantAction", "set_merchant_action"),
        ("addTagsAction", "add_tags_action"),
        ("splitTransactionsAction", "split_transactions_action"),
        ("merchantCriteriaUseOriginalStatement", "merchant_criteria_use_original_statement"),
        ("applyToExistingTransactions", "apply_to_existing_transactions"),
    )

    _RULE_MUTATIONS = {
        "create": {
            "operation": "Common_CreateTransactionRuleMutationV2",
            "input_type": "CreateTransactionRuleInput",
            "payload_field": "createTransactionRuleV2",
            "action_label": "Rule creation",
            "include_none": True,
        },
        "update": {
            "operation": "Common_UpdateTransactionRuleMutationV2",
            "input_type": "UpdateTransactionRuleInput",
            "payload_field": "updateTransactionRuleV2",
            "action_label": "Rule update",
            "include_none": False,
        },
    }

    @staticmethod
    def _raise_on_payload_errors(errors: Optional[Dict[str, Any]], action: str) -> None:
        """Raise ClientError if a Monarch mutation's PayloadError block carries messages."""
        if not errors:
            return
        message = errors.get("message")
        field_errors = errors.get("fieldErrors") or []
        if not message and not field_errors:
            return
        if message:
            raise ClientError(f"{action} failed: {message}")
        detail = "; ".join(
            f"{fe.get('field')}: {', '.join(fe.get('messages') or [])}"
            for fe in field_errors
        )
        raise ClientError(f"{action} failed: {detail}")

    def get_transaction_rules(self) -> List[Dict[str, Any]]:
        """Return all transaction rules in priority order."""
        mm = self._get_mm()
        query = gql(
            """
            query GetTransactionRules {
              transactionRules { id order ...TransactionRuleFields __typename }
            }
            """
            + self._RULE_FIELDS_FRAGMENT
        )
        result = self._query_monarch(mm.gql_call(
            operation="GetTransactionRules",
            graphql_query=query,
        ))
        return result.get("transactionRules", []) or []

    def get_transaction_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """Return a single rule by id, or None if not present."""
        for rule in self.get_transaction_rules():
            if str(rule.get("id")) == str(rule_id):
                return rule
        return None

    # Action fields that must be re-sent on update for Monarch to actually
    # persist any change. The `Common_UpdateTransactionRuleMutationV2` mutation
    # silently no-ops when the input contains only criteria edits with no
    # action field present — verified by spying on gql_call variables and
    # confirming via a fresh `get_transaction_rule` that server state was
    # unchanged. Re-sending the rule's current action(s) makes criteria-only
    # updates take effect.
    _RULE_ACTION_FIELDS = (
        "set_category_action", "set_merchant_action",
        "add_tags_action", "split_transactions_action",
    )

    def _mutate_rule(self, kind: str, *, rule_id: Optional[str] = None, **fields: Any) -> Dict[str, Any]:
        """Run a create/update mutation. Driven by `_RULE_MUTATIONS`."""
        spec = self._RULE_MUTATIONS[kind]
        rule_input: Dict[str, Any] = {"id": rule_id} if rule_id else {}
        for gql_key, py_key in self._RULE_INPUT_KEYS:
            value = fields.get(py_key)
            if spec["include_none"] or value is not None:
                rule_input[gql_key] = value

        mm = self._get_mm()
        query = gql(
            f"""
            mutation {spec['operation']}($input: {spec['input_type']}!) {{
              {spec['payload_field']}(input: $input) {{
                errors {{ ...PayloadErrorFields __typename }}
                transactionRule {{ id ...TransactionRuleFields __typename }}
                __typename
              }}
            }}
            """
            + self._RULE_FIELDS_FRAGMENT
            + self._PAYLOAD_ERROR_FRAGMENT
        )
        result = self._query_monarch(mm.gql_call(
            operation=spec["operation"],
            graphql_query=query,
            variables={"input": rule_input},
        ))
        payload = result.get(spec["payload_field"]) or {}
        self._raise_on_payload_errors(payload.get("errors"), spec["action_label"])
        rule = payload.get("transactionRule")
        if not rule:
            raise ClientError(f"{spec['action_label']} returned no rule data")
        return rule

    def create_transaction_rule(self, **fields: Any) -> Dict[str, Any]:
        """Create a new transaction rule and return the server-confirmed rule."""
        return self._mutate_rule("create", **fields)

    def update_transaction_rule(self, rule_id: str, **fields: Any) -> Dict[str, Any]:
        """Update an existing rule; only fields whose value is non-None are sent.

        Monarch silently no-ops criteria-only updates, so we re-send the rule's
        current actions when the caller didn't specify any.
        """
        if not any(fields.get(k) is not None for k in self._RULE_ACTION_FIELDS):
            existing = self.get_transaction_rule(rule_id)
            if existing is None:
                raise ClientError(f"Rule {rule_id} not found")
            if existing.get("setCategoryAction"):
                fields["set_category_action"] = existing["setCategoryAction"]["id"]
            elif existing.get("setMerchantAction"):
                fields["set_merchant_action"] = existing["setMerchantAction"]["id"]
            elif existing.get("addTagsAction"):
                fields["add_tags_action"] = [t["id"] for t in existing["addTagsAction"]]
        return self._mutate_rule("update", rule_id=rule_id, **fields)

    def delete_transaction_rule(self, rule_id: str) -> bool:
        """Delete a transaction rule by id.

        The Monarch `deleteTransactionRule` mutation often returns
        `{deleted: false, errors: null}` even when the rule was actually
        removed; we verify by re-querying the rule list.
        """
        mm = self._get_mm()
        query = gql(
            """
            mutation Common_DeleteTransactionRule($id: ID!) {
              deleteTransactionRule(id: $id) {
                deleted
                errors { ...PayloadErrorFields __typename }
                __typename
              }
            }
            """
            + self._PAYLOAD_ERROR_FRAGMENT
        )
        result = self._query_monarch(mm.gql_call(
            operation="Common_DeleteTransactionRule",
            graphql_query=query,
            variables={"id": rule_id},
        ))
        payload = result.get("deleteTransactionRule") or {}
        self._raise_on_payload_errors(payload.get("errors"), "Rule delete")
        if self.get_transaction_rule(rule_id) is not None:
            raise ClientError(f"Rule delete failed: rule {rule_id} still exists")
        return True

    # ==================== Merchant Methods ====================

    def get_merchants(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get merchants from cashflow data.

        The Monarch API doesn't have a dedicated merchants endpoint,
        so we extract merchants from the cashflow byMerchant aggregates.

        Args:
            start_date: Filter by start date (YYYY-MM-DD)
            end_date: Filter by end date (YYYY-MM-DD)

        Returns:
            Dict with merchants and their transaction summaries
        """
        # Use cashflow which has byMerchant aggregates
        # High limit to capture all merchants across transaction history
        mm = self._get_mm()
        return self._query_monarch(mm.get_cashflow(
            limit=100000,
            start_date=start_date,
            end_date=end_date
        ))


# Module-level client instance - singleton pattern
_client: Optional[MonarchClient] = None


def get_client() -> MonarchClient:
    """Get or create the global Monarch client instance."""
    global _client
    if _client is None:
        _client = MonarchClient()
    return _client
