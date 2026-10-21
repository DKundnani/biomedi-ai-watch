from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Item:
    """One collected record: a paper, grant, or product/regulatory update."""

    id: str
    kind: str  # "paper" | "grant" | "product"
    source: str
    title: str
    url: str
    date: str  # ISO yyyy-mm-dd
    summary: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self, max_chars: int = 1200) -> str:
        """Compact text form fed to the model."""
        extras = "; ".join(f"{k}: {v}" for k, v in self.extra.items() if v)
        text = self.summary[:max_chars]
        return f"[{self.id}] ({self.source}, {self.date}) {self.title}\n{extras}\n{text}".strip()
