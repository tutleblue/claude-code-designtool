"""어디서든 스튜디오를 부르는 입구:  python <스튜디오 폴더>/run_studio.py [open|init|doctor|snapshot] ...

`python -m studio` 는 스튜디오 폴더에서만 된다. 앱 저장소에서 바로 부를 수 있게 이 파일이 경로를 잡아 준다.
"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
runpy.run_module("studio", run_name="__main__", alter_sys=True)
