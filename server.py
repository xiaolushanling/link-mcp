"""从任意工作目录启动，默认读取项目根目录的 .env。"""

from pathlib import Path

from link_mcp.__main__ import main

if __name__ == "__main__":
    main(default_env_file=Path(__file__).with_name(".env"))
