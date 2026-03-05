"""收集器基底類別"""

from abc import ABC, abstractmethod
from app.models.intel import IntelItem


class BaseCollector(ABC):
    """所有情報收集器的基底類別"""

    name: str = "base"

    @abstractmethod
    async def collect(self) -> list[IntelItem]:
        """收集情報，回傳 IntelItem 列表"""
        ...
