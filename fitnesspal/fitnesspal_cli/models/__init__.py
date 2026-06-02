"""MyFitnessPal CLI models."""
from .base import CLIModel
from .item import (
    # Diary
    DiaryEntry,
    DiaryMeal,
    DiaryDay,
    # Exercise
    ExerciseEntry,
    ExerciseGroup,
    ExerciseDay,
    # Measurement
    MeasurementEntry,
    # Report
    ReportEntry,
    # Food
    FoodSearchResult,
    ServingSize,
    FoodItemDetail,
    # Recipe
    RecipeListItem,
    RecipeDetail,
    # Saved Meal
    SavedMealListItem,
    SavedMealDetail,
    # Auth
    AuthStatus,
)

__all__ = [
    "CLIModel",
    "DiaryEntry",
    "DiaryMeal",
    "DiaryDay",
    "ExerciseEntry",
    "ExerciseGroup",
    "ExerciseDay",
    "MeasurementEntry",
    "ReportEntry",
    "FoodSearchResult",
    "ServingSize",
    "FoodItemDetail",
    "RecipeListItem",
    "RecipeDetail",
    "SavedMealListItem",
    "SavedMealDetail",
    "AuthStatus",
]
