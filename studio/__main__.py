"""python -m studio [open|init|doctor|snapshot] ...

    open      (기본) 스튜디오 띄우기          python -m studio --project <앱 저장소>
    init      앱을 분석해 개인화 설정 초안 만들기 python -m studio init --project <앱 저장소>
    doctor    개인화 설정이 잘 맞는지 점검       python -m studio doctor --project <앱 저장소>
    snapshot  저장본 사진 (앱 저장소 폴더에서)    python -m studio snapshot <저장본 이름>
"""
import sys

cmd = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "open"
rest = sys.argv[2:] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else sys.argv[1:]

if cmd == "open":
    from .server import main
elif cmd == "init":
    from .init import main
elif cmd == "doctor":
    from .doctor import main
elif cmd == "snapshot":
    from .snapshot import main
    sys.argv = ["snapshot", *rest]
    rest = None
else:
    sys.exit(__doc__)

main(rest) if rest is not None else main()
