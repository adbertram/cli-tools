"""MyFitnessPal entity models.

All models for MFP data: diary entries, meals, exercises,
measurements, reports, food items, recipes, and saved meals.
"""
from typing import Dict, List, Optional

from .base import CLIModel


# ==================== Diary Models ====================


class DiaryEntry(CLIModel):
    """A single food entry within a meal."""

    name: str
    short_name: Optional[str] = None
    quantity: Optional[str] = None
    unit: Optional[str] = None
    nutrition_information: Dict[str, float] = {}


class DiaryMeal(CLIModel):
    """A meal (e.g., Breakfast, Lunch) containing food entries."""

    name: str
    entries: List[DiaryEntry] = []
    totals: Dict[str, float] = {}


class DiaryDay(CLIModel):
    """A full day's food diary."""

    date: str
    meals: List[DiaryMeal] = []
    totals: Dict[str, float] = {}
    goals: Dict[str, float] = {}
    notes: Optional[str] = None
    water: float = 0.0
    complete: bool = False


# ==================== Exercise Models ====================


class ExerciseEntry(CLIModel):
    """A single exercise entry."""

    name: str
    nutrition_information: Dict[str, float] = {}


class ExerciseGroup(CLIModel):
    """A group of exercises (e.g., Cardiovascular, Strength)."""

    name: str
    entries: List[ExerciseEntry] = []


class ExerciseDay(CLIModel):
    """Exercises for a single day."""

    date: str
    exercises: List[ExerciseGroup] = []


# ==================== Measurement Models ====================


class MeasurementEntry(CLIModel):
    """A single measurement data point."""

    date: str
    value: float


# ==================== Report Models ====================


class ReportEntry(CLIModel):
    """A single report data point."""

    date: str
    value: float


# ==================== Food Models ====================


class FoodSearchResult(CLIModel):
    """A food item from search results."""

    mfp_id: int
    name: str
    brand: Optional[str] = None
    verified: bool = False
    calories: Optional[float] = None


class ServingSize(CLIModel):
    """A serving size option for a food item."""

    id: str
    nutrition_multiplier: float
    value: float
    unit: str
    index: int


class FoodItemDetail(CLIModel):
    """Full food item details with nutrition information."""

    mfp_id: int
    name: str
    brand: Optional[str] = None
    verified: bool = False
    calories: Optional[float] = None
    confirmations: Optional[int] = None
    serving: Optional[str] = None
    nutrition: Dict[str, float] = {}
    servings: List[ServingSize] = []


# ==================== Recipe Models ====================


class RecipeListItem(CLIModel):
    """A recipe summary from the recipes list."""

    id: int
    name: str


class RecipeDetail(CLIModel):
    """Full recipe details."""

    id: int
    name: str
    author: Optional[str] = None
    url: Optional[str] = None
    yield_amount: Optional[str] = None
    ingredients: List[str] = []
    nutrition: Dict[str, str] = {}
    instructions: Optional[str] = None
    tags: List[str] = []


# ==================== Saved Meal Models ====================


class SavedMealListItem(CLIModel):
    """A saved meal summary from the meals list."""

    id: int
    name: str


class SavedMealDetail(CLIModel):
    """Full saved meal details (uses Recipe schema from MFP)."""

    id: int
    name: str
    author: Optional[str] = None
    url: Optional[str] = None
    yield_amount: Optional[str] = None
    ingredients: List[str] = []
    nutrition: Dict[str, str] = {}
    instructions: Optional[str] = None
    tags: List[str] = []


# ==================== Auth Models ====================


class AuthStatus(CLIModel):
    """Authentication status."""

    authenticated: bool
    username: Optional[str] = None
    user_id: Optional[str] = None
    message: str = ""
