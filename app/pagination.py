from dataclasses import dataclass, field
from typing import List, Optional

PAGE_SIZE = 20


@dataclass
class Page:
    items: List
    page: int
    page_size: int
    total: int
    pages: int = 0
    has_prev: bool = False
    has_next: bool = False
    prev_num: int = 0
    next_num: int = 0
    page_range: List[int] = field(default_factory=list)

    def __post_init__(self):
        self.pages = max(1, -(-self.total // self.page_size))
        self.has_prev = self.page > 1
        self.has_next = self.page < self.pages
        self.prev_num = self.page - 1 if self.has_prev else 1
        self.next_num = self.page + 1 if self.has_next else self.pages
        start = max(1, self.page - 2)
        end = min(self.pages, self.page + 2)
        self.page_range = list(range(start, end + 1))


def paginate(query, page: int = 1, page_size: int = PAGE_SIZE):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return Page(items=items, page=page, page_size=page_size, total=total)
