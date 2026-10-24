from .._bytecode import load_module_bytecode
from cli_tools_shared.models import CLIModel as _CLIModel

load_module_bytecode(__name__, globals())
