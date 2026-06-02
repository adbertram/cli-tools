"""Filter mapping module for translating between CLI args, standard filters, and API parameters."""
from typing import List, Dict, Optional, Any, Callable

from .filters import parse_filter_string

class FilterMap:
    """
    Helper to map CLI arguments to standard filters, and standard filters to API parameters.
    """
    def __init__(self):
        # Maps CLI argument name -> (target_field, operator)
        self._arg_mappings: Dict[str, tuple] = {}

        # Maps field name -> transformation function(op, value) -> dict
        self._api_translators: Dict[str, Callable[[str, str], Dict[str, Any]]] = {}

        # Maps param name -> joiner function(existing_val, new_val) -> merged_val
        self._param_joiners: Dict[str, Callable[[Any, Any], Any]] = {}

    def add_argument_mapping(self, arg_name: str, field_name: Optional[str] = None, operator: str = 'eq') -> 'FilterMap':
        """
        Map a named argument (like from CLI kwargs) to a standard filter.

        Args:
            arg_name: The argument name in the CLI command
            field_name: The target field name (defaults to arg_name)
            operator: The operator to use (defaults to 'eq')

        Example:
            mapper.add_argument_mapping('status') # status='val' -> 'status:eq:val'
            mapper.add_argument_mapping('min_price', 'price', 'gte') # min_price=10 -> 'price:gte:10'
        """
        self._arg_mappings[arg_name] = (field_name or arg_name, operator)
        return self

    def register_api_translator(self, field_name: str, translator: Callable[[str, str], Dict[str, Any]]) -> 'FilterMap':
        """
        Register a function to translate a specific field's filter to API parameters.

        Args:
            field_name: The field name in the standard filter string
            translator: Function accepting (operator, value) and returning a dict of API params

        Example:
            def translate_price(op, val):
                if op == 'gte': return {'price_min': val}
                return {'price': val}
            mapper.register_api_translator('price', translate_price)
        """
        self._api_translators[field_name] = translator
        return self

    def set_param_joiner(self, param_name: str, joiner: Callable[[Any, Any], Any]) -> 'FilterMap':
        """
        Set a strategy for merging values when multiple filters map to the same API parameter.

        Args:
            param_name: The API parameter name (e.g. 'filter', 'sort')
            joiner: Function that takes (existing_val, new_val) and returns merged val

        Example:
            # Join multiple 'filter' params with commas
            mapper.set_param_joiner('filter', lambda a, b: f"{a},{b}")
        """
        self._param_joiners[param_name] = joiner
        return self

    def args_to_filters(self, **kwargs) -> List[str]:
        """
        Convert keyword arguments into standard filter strings based on mappings.
        Ignores None values.

        Returns:
            List of standard filter strings (e.g., ['status:eq:active'])
        """
        filters = []
        for key, value in kwargs.items():
            if value is None:
                continue

            if key in self._arg_mappings:
                field, op = self._arg_mappings[key]
                # If value is a list (e.g. from multiple args), join or iterate?
                # For now assume simple values.
                filters.append(f"{field}:{op}:{value}")

        return filters

    def to_api_params(self, filters: List[str]) -> Dict[str, Any]:
        """
        Convert standard filter strings to API parameters using registered translators.

        Args:
            filters: List of standard filter strings

        Returns:
            Dictionary of API parameters
        """
        if not filters:
            return {}

        params = {}
        for f_str in filters:
            conditions = parse_filter_string(f_str)
            for field, op, val in conditions:
                if field in self._api_translators:
                    translator = self._api_translators[field]
                    # val is Optional[str], but translators usually expect value.
                    # Handle null/notnull operators where val might be None
                    api_param = translator(op, val if val is not None else "")

                    if api_param:
                        for key, value in api_param.items():
                            if key in params and key in self._param_joiners:
                                params[key] = self._param_joiners[key](params[key], value)
                            else:
                                params[key] = value

        return params
