"""List MiniWoB tasks registered by the installed BrowserGym version."""

from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import asdict, dataclass

import browsergym.miniwob.all as miniwob_tasks
from browsergym.miniwob.base import AbstractMiniwobTask


@dataclass(frozen=True)
class TaskInfo:
    task_id: str
    description: str


def collect_tasks(query: str = "") -> list[TaskInfo]:
    query = query.casefold()
    tasks: list[TaskInfo] = []
    for _, task_class in inspect.getmembers(miniwob_tasks, inspect.isclass):
        if not issubclass(task_class, AbstractMiniwobTask):
            continue
        subdomain = getattr(task_class, "subdomain", None)
        if not subdomain:
            continue
        task = TaskInfo(
            task_id=f"browsergym/{task_class.get_task_id()}",
            description=getattr(task_class, "desc", ""),
        )
        if query and query not in f"{task.task_id} {task.description}".casefold():
            continue
        tasks.append(task)
    return sorted(tasks, key=lambda task: task.task_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search", default="", help="Filter by task ID or description")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()
    tasks = collect_tasks(args.search)

    if args.json:
        print(json.dumps([asdict(task) for task in tasks], ensure_ascii=False, indent=2))
        return

    print(f"MiniWoB tasks: {len(tasks)}")
    for task in tasks:
        print(f"{task.task_id:<52} {task.description}")


if __name__ == "__main__":
    main()
