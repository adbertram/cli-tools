"""MyFitnessPal client wrapping the python-myfitnesspal library."""
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import quote, urlencode, urljoin

import requests

from cli_tools_shared.http_session import BrowserAuthState, BrowserAuthStateError
from cli_tools_shared.exceptions import ClientError

from .models import (
    AuthStatus,
    DiaryDay,
    DiaryEntry,
    DiaryMeal,
    ExerciseDay,
    ExerciseEntry,
    ExerciseGroup,
    FoodItemDetail,
    FoodSearchResult,
    MeasurementEntry,
    RecipeDetail,
    RecipeListItem,
    ReportEntry,
    SavedMealDetail,
    SavedMealListItem,
    ServingSize,
)


class _BrowserAuthStateConfig:
    """Provide BrowserAuthState the exact browser instance that must be closed."""

    def __init__(self, config, browser):
        self._browser = browser
        self._tool_name = getattr(config, "_tool_name", "fitnesspal")

    def get_browser(self):
        return self._browser


def _load_cookiejar():
    """Load live MyFitnessPal cookies into a CookieJar."""
    import requests.cookies
    from .config import get_config

    config = get_config()
    browser = config.get_browser()
    try:
        auth_state = BrowserAuthState.from_config(_BrowserAuthStateConfig(config, browser))
        cookies = auth_state.cookies_for_host(
            "www.myfitnesspal.com",
            allowed_domains=("myfitnesspal.com",),
        )
    finally:
        browser.close()

    if not cookies:
        raise BrowserAuthStateError("Saved MyFitnessPal browser state contains no myfitnesspal.com cookies.")

    jar = requests.cookies.RequestsCookieJar()
    for cookie in cookies:
        jar.set(
            cookie.name,
            cookie.value,
            domain=cookie.domain,
            path=cookie.path,
        )
    return jar


def _get_mfp_client():
    """Create and return a myfitnesspal.Client instance.

    Loads cookies from our saved browser session (from 'auth login')
    and passes them to the library client.

    Raises:
        ClientError: If no saved session or auth fails.
    """
    try:
        import myfitnesspal

        try:
            cookiejar = _load_cookiejar()
        except BrowserAuthStateError as exc:
            raise ClientError(
                "No saved browser session found. "
                "Run 'fitnesspal auth login' first."
            ) from exc
        return myfitnesspal.Client(cookiejar=cookiejar)
    except ClientError:
        raise
    except Exception as e:
        error_msg = str(e)
        if "cookie" in error_msg.lower() or "auth" in error_msg.lower():
            raise ClientError(
                "Browser session expired or invalid. "
                "Run 'fitnesspal auth login' to re-authenticate."
            )
        raise ClientError(f"Failed to initialize MyFitnessPal client: {error_msg}")


def _parse_date(date_str: str) -> date:
    """Parse a date string into a date object.

    Supports: 'today', 'yesterday', 'YYYY-MM-DD', 'MM/DD/YYYY'

    Raises:
        ClientError: If the date string cannot be parsed.
    """
    if date_str.lower() == "today":
        return date.today()
    if date_str.lower() == "yesterday":
        from datetime import timedelta

        return date.today() - timedelta(days=1)

    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue

    raise ClientError(
        f"Invalid date format: '{date_str}'. "
        "Use 'today', 'yesterday', or 'YYYY-MM-DD'."
    )


def _entry_to_model(entry) -> DiaryEntry:
    """Convert a myfitnesspal Entry object to our DiaryEntry model."""
    return DiaryEntry(
        name=entry.name,
        short_name=entry.short_name,
        quantity=entry.quantity,
        unit=entry.unit,
        nutrition_information=dict(entry.nutrition_information),
    )


def _meal_to_model(meal) -> DiaryMeal:
    """Convert a myfitnesspal Meal object to our DiaryMeal model."""
    return DiaryMeal(
        name=meal.name,
        entries=[_entry_to_model(e) for e in meal.entries],
        totals=dict(meal.totals),
    )


def _exercise_to_model(exercise) -> ExerciseGroup:
    """Convert a myfitnesspal Exercise object to our ExerciseGroup model."""
    entries = []
    for entry in exercise.entries:
        entries.append(
            ExerciseEntry(
                name=entry.name,
                nutrition_information=dict(entry.nutrition_information),
            )
        )
    return ExerciseGroup(name=exercise.name, entries=entries)


def _ensure_upper_lower_bound(lower_bound: Optional[date], upper_bound: Optional[date]) -> tuple[date, date]:
    """Mirror python-myfitnesspal's default 30-day date window behavior."""
    if upper_bound is None:
        upper_bound = date.today()
    if lower_bound is None:
        lower_bound = upper_bound - timedelta(days=30)
    if lower_bound > upper_bound:
        lower_bound, upper_bound = upper_bound, lower_bound
    return upper_bound, lower_bound


def _normalize_measurement_type(measurement: str) -> str:
    """Map supported CLI measurement names to the current API values."""
    normalized = measurement.strip().lower()
    if normalized != "weight":
        raise ClientError(
            "MyFitnessPal's current measurements API supports only Weight. "
            "Use --measurement Weight."
        )
    return normalized


def _get_api_session_and_headers() -> tuple[requests.Session, dict[str, str]]:
    """Create an authenticated API session from the saved browser cookies."""
    session = requests.Session()
    session.cookies.update(_load_cookiejar())
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/88.0.4324.104 Safari/537.36"
            )
        }
    )

    response = session.get(
        "https://www.myfitnesspal.com/user/auth_token?refresh=true",
        timeout=(10.0, 30.0),
    )
    if not response.ok:
        raise ClientError(
            f"Unable to fetch MyFitnessPal authentication token (HTTP {response.status_code}): "
            f"{response.text[:300]}"
        )

    auth_data = response.json()
    return session, {
        "Accept": "application/json",
        "Authorization": f"Bearer {auth_data['access_token']}",
        "mfp-client-id": "mfp-main-js",
        "mfp-user-id": str(auth_data["user_id"]),
    }


def _get_api_json(session: requests.Session, headers: dict[str, str], url: str) -> dict:
    """GET JSON from MyFitnessPal's API using explicit token headers."""
    response = session.get(url, headers=headers, timeout=(10.0, 30.0))
    if not response.ok:
        raise ClientError(
            f"MyFitnessPal request failed (HTTP {response.status_code}): {response.text[:300]}"
        )
    return response.json()


def _get_numeric(value: object) -> float:
    """Extract MyFitnessPal's numeric measurement value from API output."""
    return float(str(value).split()[0])


class FitnesspalClient:
    """Client for interacting with MyFitnessPal via the python-myfitnesspal library."""

    def __init__(self):
        self._mfp = None

    def _get_mfp(self):
        """Lazy-initialize the MFP client."""
        if self._mfp is None:
            self._mfp = _get_mfp_client()
        return self._mfp

    # ==================== Auth ====================

    def auth_status(self) -> AuthStatus:
        """Check authentication status by attempting to create a client."""
        try:
            mfp = self._get_mfp()
            username = mfp.effective_username
            user_id = mfp.user_id
            return AuthStatus(
                authenticated=True,
                username=username,
                user_id=user_id,
                message="Authenticated via browser cookies",
            )
        except ClientError:
            return AuthStatus(
                authenticated=False,
                message="Not authenticated. Log in to MyFitnessPal in your web browser.",
            )
        except Exception as e:
            return AuthStatus(
                authenticated=False,
                message=f"Authentication check failed: {e}",
            )

    def test_auth(self) -> dict:
        """Test browser authentication status.

        Returns:
            Dict with authenticated, url, cookies, and details.
        """
        from .config import get_config
        config = get_config()
        browser = config.get_browser()
        try:
            return browser.test_session()
        finally:
            browser.close()

    # ==================== Diary ====================

    def get_diary(self, date_str: str) -> DiaryDay:
        """Get the food diary for a specific date.

        Args:
            date_str: Date string ('today', 'yesterday', or 'YYYY-MM-DD')

        Returns:
            DiaryDay model with meals, totals, goals, notes, water
        """
        mfp = self._get_mfp()
        target_date = _parse_date(date_str)
        day = mfp.get_date(target_date)

        meals = [_meal_to_model(m) for m in day.meals]

        return DiaryDay(
            date=target_date.isoformat(),
            meals=meals,
            totals=dict(day.totals),
            goals=dict(day.goals),
            notes=day.notes or None,
            water=day.water,
            complete=day.complete,
        )

    # ==================== Exercises ====================

    def get_exercises(self, date_str: str) -> ExerciseDay:
        """Get exercises for a specific date.

        Args:
            date_str: Date string ('today', 'yesterday', or 'YYYY-MM-DD')

        Returns:
            ExerciseDay model with exercise groups
        """
        mfp = self._get_mfp()
        target_date = _parse_date(date_str)
        day = mfp.get_date(target_date)

        exercises = [_exercise_to_model(ex) for ex in day.exercises]

        return ExerciseDay(
            date=target_date.isoformat(),
            exercises=exercises,
        )

    # ==================== Measurements ====================

    def list_measurements(
        self,
        measurement: str = "Weight",
        lower_bound: Optional[str] = None,
        upper_bound: Optional[str] = None,
        limit: int = 100,
    ) -> List[MeasurementEntry]:
        """List measurements of a given type within a date range.

        Args:
            measurement: Measurement name (default: 'Weight')
            lower_bound: Start date (YYYY-MM-DD)
            upper_bound: End date (YYYY-MM-DD)
            limit: Maximum entries to return

        Returns:
            List of MeasurementEntry models sorted by date
        """
        session, headers = _get_api_session_and_headers()
        lb = _parse_date(lower_bound) if lower_bound else None
        ub = _parse_date(upper_bound) if upper_bound else None
        ub, lb = _ensure_upper_lower_bound(lb, ub)
        measurement_type = _normalize_measurement_type(measurement)

        entries = []
        for day_offset in range((ub - lb).days + 1):
            entry_date = ub - timedelta(days=day_offset)
            url = (
                urljoin("https://api.myfitnesspal.com/", "/v2/measurements")
                + "?"
                + urlencode(
                    {
                        "entry_date": entry_date.isoformat(),
                        "types": measurement_type,
                    }
                )
            )
            payload = _get_api_json(session, headers, url)
            for item in payload.get("items", []):
                value = item["value"]
                unit = item.get("unit")
                rendered_value = f"{value} {unit}" if unit else str(value)
                entries.append(
                    MeasurementEntry(
                        date=item["date"],
                        value=_get_numeric(rendered_value),
                    )
                )
                if len(entries) >= limit:
                    return entries

        return entries

    # ==================== Reports ====================

    def get_report(
        self,
        report_name: str = "Net Calories",
        report_category: str = "Nutrition",
        lower_bound: Optional[str] = None,
        upper_bound: Optional[str] = None,
        limit: int = 100,
    ) -> List[ReportEntry]:
        """Get report data for a given metric and date range.

        Args:
            report_name: Report metric name (default: 'Net Calories')
            report_category: Report category (default: 'Nutrition')
            lower_bound: Start date (YYYY-MM-DD)
            upper_bound: End date (YYYY-MM-DD)
            limit: Maximum entries to return

        Returns:
            List of ReportEntry models sorted by date
        """
        session, headers = _get_api_session_and_headers()
        lb = _parse_date(lower_bound) if lower_bound else None
        ub = _parse_date(upper_bound) if upper_bound else None
        ub, lb = _ensure_upper_lower_bound(lb, ub)

        url = (
            urljoin(
                "https://www.myfitnesspal.com/",
                f"api/services/reports/results/{report_category.lower()}/{quote(report_name, safe='')}",
            )
            + f"/{(date.today() - lb).days}.json"
        )
        payload = _get_api_json(session, headers, url)
        results = payload.get("outcome", {}).get("results")
        if results is None:
            raise ClientError("MyFitnessPal report response did not include outcome.results.")

        entries = []
        for index, item in enumerate(results):
            entry_date = date.today() - timedelta(days=len(results)) + timedelta(days=index + 1)
            if ub >= entry_date >= lb:
                entries.append(ReportEntry(date=entry_date.isoformat(), value=item["total"]))

        entries.sort(key=lambda item: item.date, reverse=True)
        return entries[:limit]

    # ==================== Food ====================

    def search_food(self, query: str, limit: int = 100) -> List[FoodSearchResult]:
        """Search the MFP food database.

        Args:
            query: Search query string
            limit: Maximum results to return

        Returns:
            List of FoodSearchResult models
        """
        mfp = self._get_mfp()

        results = mfp.get_food_search_results(query)

        items = []
        for food in results[:limit]:
            items.append(
                FoodSearchResult(
                    mfp_id=food.mfp_id,
                    name=food.name,
                    brand=food.brand,
                    verified=food.verified,
                    calories=food.calories,
                )
            )

        return items

    def get_food(self, mfp_id: int) -> FoodItemDetail:
        """Get detailed information about a specific food item.

        Args:
            mfp_id: MyFitnessPal food item ID

        Returns:
            FoodItemDetail model with full nutrition info
        """
        mfp = self._get_mfp()

        food = mfp.get_food_item_details(mfp_id)

        # Build servings list
        servings = []
        try:
            for s in food.servings:
                servings.append(
                    ServingSize(
                        id=s.id,
                        nutrition_multiplier=s.nutrition_multiplier,
                        value=s.value,
                        unit=s.unit,
                        index=s.index,
                    )
                )
        except Exception:
            pass

        # Get nutrition details
        nutrition = {}
        try:
            nutrition = dict(food.details)
        except Exception:
            pass

        return FoodItemDetail(
            mfp_id=food.mfp_id,
            name=food.name,
            brand=food.brand,
            verified=food.verified,
            calories=food.calories,
            confirmations=food.confirmations if hasattr(food, "_confirmations") and food._confirmations is not None else None,
            serving=food.serving,
            nutrition=nutrition,
            servings=servings,
        )

    # ==================== Recipes ====================

    def list_recipes(self, limit: int = 100) -> List[RecipeListItem]:
        """List all saved recipes.

        Args:
            limit: Maximum results to return

        Returns:
            List of RecipeListItem models
        """
        session, headers = _get_api_session_and_headers()
        url = "https://api.myfitnesspal.com/v2/recipes?" + urlencode({"limit": limit})
        payload = _get_api_json(session, headers, url)
        return [
            RecipeListItem(
                id=item["id"],
                name=item["name"],
            )
            for item in payload["items"][:limit]
        ]

    def _api_headers(self) -> dict:
        """Get authenticated headers for the MFP v2 API."""
        mfp = self._get_mfp()
        return {
            "Authorization": f"Bearer {mfp.access_token}",
            "mfp-client-id": "mfp-main-js",
            "mfp-user-id": str(mfp.user_id),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def create_recipe(
        self,
        name: str,
        servings: float,
        ingredients: List[dict],
    ) -> dict:
        """Create a new recipe via the MFP v2 API.

        Args:
            name: Recipe name
            servings: Number of servings
            ingredients: List of dicts, each with:
                - food_id: str - MFP food item ID
                - quantity: float - number of servings of the selected serving size
                - serving_unit: str - serving size unit (e.g. 'oz', 'cup', 'g')
                - serving_value: float - serving size value
                - nutrition_multiplier: float - multiplier for the serving size

        Returns:
            Dict with created recipe data including id, name, nutritional_contents
        """
        mfp = self._get_mfp()

        api_ingredients = []
        for ing in ingredients:
            api_ingredients.append({
                "food": {"id": str(ing["food_id"])},
                "serving_size": {
                    "nutrition_multiplier": ing["nutrition_multiplier"],
                    "unit": ing["serving_unit"],
                    "value": ing["serving_value"],
                },
                "servings": ing["quantity"],
            })

        payload = {
            "items": [{
                "name": name,
                "servings": servings,
                "ingredients": api_ingredients,
                "public": False,
                "country_code": "US",
            }]
        }

        resp = mfp.session.post(
            "https://api.myfitnesspal.com/v2/recipes",
            headers=self._api_headers(),
            json=payload,
        )

        if resp.status_code != 201:
            error_msg = resp.text[:300]
            raise ClientError(f"Failed to create recipe (HTTP {resp.status_code}): {error_msg}")

        data = resp.json()
        return data["items"][0]

    def delete_recipe(self, recipe_id: str) -> None:
        """Delete a recipe via the MFP v2 API.

        Args:
            recipe_id: Recipe ID to delete
        """
        mfp = self._get_mfp()

        resp = mfp.session.delete(
            f"https://api.myfitnesspal.com/v2/recipes/{recipe_id}",
            headers=self._api_headers(),
        )

        if resp.status_code != 204:
            raise ClientError(f"Failed to delete recipe (HTTP {resp.status_code}): {resp.text[:300]}")

    def get_recipe(self, recipe_id: int) -> RecipeDetail:
        """Get detailed recipe information.

        Args:
            recipe_id: Recipe ID

        Returns:
            RecipeDetail model
        """
        mfp = self._get_mfp()

        raw = mfp.get_recipe(recipe_id)

        nutrition = {}
        if "nutrition" in raw:
            nutrition = {
                k: v
                for k, v in raw["nutrition"].items()
                if k != "@type"
            }

        return RecipeDetail(
            id=recipe_id,
            name=raw.get("name", ""),
            author=raw.get("author"),
            url=raw.get("org_url"),
            yield_amount=raw.get("recipeYield"),
            ingredients=raw.get("recipeIngredient", []),
            nutrition=nutrition,
            instructions=raw.get("recipeInstructions"),
            tags=raw.get("tags", []),
        )

    # ==================== Saved Meals ====================

    def list_saved_meals(self, limit: int = 100) -> List[SavedMealListItem]:
        """List all saved meals.

        Args:
            limit: Maximum results to return

        Returns:
            List of SavedMealListItem models
        """
        mfp = self._get_mfp()

        raw = mfp.get_meals()

        items = []
        for meal_id, title in raw.items():
            items.append(SavedMealListItem(id=meal_id, name=title))

        return items[:limit]

    def get_saved_meal(self, meal_id: int, meal_title: str) -> SavedMealDetail:
        """Get detailed saved meal information.

        Args:
            meal_id: Meal ID
            meal_title: Meal title (required by the MFP API)

        Returns:
            SavedMealDetail model
        """
        mfp = self._get_mfp()

        raw = mfp.get_meal(meal_id, meal_title)

        nutrition = {}
        if "nutrition" in raw:
            nutrition = {
                k: v
                for k, v in raw["nutrition"].items()
                if k != "@type"
            }

        return SavedMealDetail(
            id=meal_id,
            name=raw.get("name", meal_title),
            author=raw.get("author"),
            url=raw.get("org_url"),
            yield_amount=raw.get("recipeYield"),
            ingredients=raw.get("recipeIngredient", []),
            nutrition=nutrition,
            instructions=raw.get("recipeInstructions"),
            tags=raw.get("tags", []),
        )


# Module-level client singleton
_client: Optional[FitnesspalClient] = None


def get_client() -> FitnesspalClient:
    """Get or create the global FitnesspalClient instance."""
    global _client
    if _client is None:
        _client = FitnesspalClient()
    return _client
