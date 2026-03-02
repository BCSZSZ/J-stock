from __future__ import annotations

"""Manual config sync utility.

`otherconfig.json` is an optional placeholder in the G-drive structure.
It may not exist yet, and pull will skip it gracefully.
"""

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SyncPaths:
    project_root: Path
    gdrive_root: Path

    @property
    def local_config(self) -> Path:
        return self.project_root / "config.json"

    @property
    def local_otherconfig(self) -> Path:
        return self.project_root / "otherconfig.json"

    @property
    def remote_config(self) -> Path:
        return self.gdrive_root / "config.json"

    @property
    def remote_otherconfig(self) -> Path:
        return self.gdrive_root / "otherconfig.json"

    @property
    def remote_old_dir(self) -> Path:
        return self.gdrive_root / "old"


def _validate_json_file(path: Path) -> None:
    with path.open("r", encoding="utf-8") as f:
        json.load(f)


def _safe_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copy2(src, tmp)
    _validate_json_file(tmp)
    tmp.replace(dst)


def _next_backup_path(old_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = old_dir / f"config_{ts}.json"
    if not candidate.exists():
        return candidate

    idx = 1
    while True:
        candidate = old_dir / f"config_{ts}_{idx}.json"
        if not candidate.exists():
            return candidate
        idx += 1


def _backup_remote_config(paths: SyncPaths) -> Path | None:
    if not paths.remote_config.exists():
        return None

    paths.remote_old_dir.mkdir(parents=True, exist_ok=True)
    backup_path = _next_backup_path(paths.remote_old_dir)
    shutil.move(str(paths.remote_config), str(backup_path))
    return backup_path


def pull_from_gdrive(paths: SyncPaths, sync_otherconfig: bool = True) -> None:
    if not paths.gdrive_root.exists():
        raise FileNotFoundError(f"G盘目录不存在: {paths.gdrive_root}")

    if not paths.remote_config.exists():
        raise FileNotFoundError(f"G盘配置不存在: {paths.remote_config}")

    _safe_copy(paths.remote_config, paths.local_config)
    print(f"✅ 已同步: {paths.remote_config} -> {paths.local_config}")

    if sync_otherconfig:
        if paths.remote_otherconfig.exists():
            _safe_copy(paths.remote_otherconfig, paths.local_otherconfig)
            print(
                f"✅ 已同步: {paths.remote_otherconfig} -> {paths.local_otherconfig}"
            )
        else:
            print(
                "ℹ️ otherconfig.json 为可选占位文件，当前不存在，已跳过: "
                f"{paths.remote_otherconfig}"
            )


def _confirm_twice(paths: SyncPaths) -> None:
    print("\n⚠️ 危险操作: 将用本地 config.json 覆盖 G盘 config.json")
    print(f"本地: {paths.local_config}")
    print(f"远端: {paths.remote_config}")

    first = input('第一确认: 输入 "PUSH" 继续: ').strip()
    if first != "PUSH":
        raise RuntimeError("已取消: 第一确认失败")

    second_phrase = "I_UNDERSTAND_OVERWRITE_GDRIVE_CONFIG"
    second = input(f'第二确认: 输入 "{second_phrase}" 继续: ').strip()
    if second != second_phrase:
        raise RuntimeError("已取消: 第二确认失败")


def push_to_gdrive(paths: SyncPaths) -> None:
    if not paths.local_config.exists():
        raise FileNotFoundError(f"本地配置不存在: {paths.local_config}")

    _validate_json_file(paths.local_config)
    paths.gdrive_root.mkdir(parents=True, exist_ok=True)

    _confirm_twice(paths)

    backup_path = _backup_remote_config(paths)
    if backup_path:
        print(f"🗂️ 已备份旧配置到: {backup_path}")
    else:
        print("ℹ️ G盘不存在旧 config.json，无需备份")

    _safe_copy(paths.local_config, paths.remote_config)
    print(f"✅ 已覆盖: {paths.local_config} -> {paths.remote_config}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "手动同步 config 工具。\n"
            "- pull: 从 G盘拉取 config.json 到本地（可选 otherconfig.json）\n"
            "- push: 本地 config.json 覆盖到 G盘；覆盖前会将 G盘旧 config 备份到 old/"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--gdrive-root",
        default=r"G:\My Drive\AI-Stock-Sync",
        help=r"G盘同步根目录（默认: G:\My Drive\AI-Stock-Sync）",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    pull_parser = subparsers.add_parser("pull", help="从 G盘同步到本地")
    pull_parser.add_argument(
        "--no-otherconfig",
        action="store_true",
        help="只同步 config.json，不同步 otherconfig.json",
    )

    subparsers.add_parser(
        "push",
        help=(
            "将本地 config.json 覆盖到 G盘。"
            "执行前会双重确认，并把旧版移动到 old/"
        ),
    )

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    paths = SyncPaths(project_root=project_root, gdrive_root=Path(args.gdrive_root))

    try:
        if args.command == "pull":
            pull_from_gdrive(paths, sync_otherconfig=not args.no_otherconfig)
            return 0

        if args.command == "push":
            push_to_gdrive(paths)
            return 0

        parser.print_help()
        return 2
    except KeyboardInterrupt:
        print("\n❌ 已取消")
        return 130
    except Exception as e:
        print(f"❌ 失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
