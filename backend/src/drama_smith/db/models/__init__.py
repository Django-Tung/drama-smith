"""ORM 模型聚合。

Alembic `env.py` 经此 import 全部模型,使其注册到 `Base.metadata`
(autogenerate 才能发现表,见 `design.md` D13)。新增表时在此 re-export。
"""

from drama_smith.db.models.analyses import Analysis
from drama_smith.db.models.dramas import Drama
from drama_smith.db.models.episode_characters import EpisodeCharacter
from drama_smith.db.models.episodes import Episode
from drama_smith.db.models.model_configs import ModelConfig
from drama_smith.db.models.refresh_tokens import RefreshToken
from drama_smith.db.models.script_versions import ScriptVersion
from drama_smith.db.models.scripts import Script
from drama_smith.db.models.shot_characters import ShotCharacter
from drama_smith.db.models.shots import Shot
from drama_smith.db.models.tasks import Task
from drama_smith.db.models.users import User

__all__ = [
    "Analysis",
    "Drama",
    "Episode",
    "EpisodeCharacter",
    "ModelConfig",
    "RefreshToken",
    "Script",
    "ScriptVersion",
    "Shot",
    "ShotCharacter",
    "Task",
    "User",
]
