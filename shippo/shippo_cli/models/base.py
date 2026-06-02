"""Shippo model base with Shippo object id normalization."""
from cli_tools_shared.models import CLIModel as SharedCLIModel


class CLIModel(SharedCLIModel):
    def model_dump(self, **kwargs) -> dict:
        """Convert model to dict, adding 'id' from 'object_id' if present."""
        data = super().model_dump(**kwargs)
        if "object_id" in data and "id" not in data:
            data["id"] = data["object_id"]
        return data
