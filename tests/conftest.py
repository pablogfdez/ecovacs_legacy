"""Load the HA-free modules of the integration without importing Home Assistant."""

from pathlib import Path
import sys
import types

PACKAGE_DIR = Path(__file__).parents[1] / "custom_components" / "ecovacs_legacy"

# Register an empty package so ``__init__.py`` (which needs Home Assistant) is skipped
package = types.ModuleType("ecovacs_legacy")
package.__path__ = [str(PACKAGE_DIR)]
sys.modules.setdefault("ecovacs_legacy", package)
