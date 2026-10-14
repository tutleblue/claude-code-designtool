"""디자인 스튜디오용 '가짜 학생' 데이터.

스튜디오는 진짜 화면(web/)과 진짜 서버 코드(web_ui)를 그대로 쓰고, 데이터 폴더만 이걸로 채운 임시 폴더로 바꾼다.
그래서 화면 모양은 설치 앱과 같고, 내용은 아무 계정 없이도 꽉 차 보인다.
날짜는 늘 '오늘' 기준으로 만든다 (마감이 지난 날짜로 굳어 화면이 비어 보이지 않게).

개인 정보는 하나도 없다. 이름·메일 주소는 모두 지어낸 것이다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path


def current_term(now: datetime) -> tuple[int, int]:
    # 2월~7월은 1학기, 8월~이듬해 1월은 2학기로 본다 (화면에 '이번 학기' 로 보이면 된다)
    if 2 <= now.month <= 7:
        return now.year, 1
    return (now.year if now.month >= 8 else now.year - 1), 2


def courses(year: int, term: int) -> list[dict]:
    roman = "Ⅰ" if term == 1 else "Ⅱ"
    tag = f"[ {year}_{term}학기 ]"
    rows = [
        # ko, en, 분반, 시간표 색, [(요일 0=월, 시작, 끝, 강의실)], 교수
        ("미적분학" + roman, "Calculus" + roman, "03", "coral",
         [(0, "09:00", "10:15", "E7-101"), (2, "09:00", "10:15", "E7-101")], "한지성"),
        ("일반물리" + roman, "General Physics" + roman, "02", "blue",
         [(1, "10:30", "11:45", "E7-L06"), (3, "10:30", "11:45", "E7-L06")], "오세린"),
        ("일반화학" + roman, "General Chemistry" + roman, "05", "green",
         [(0, "13:30", "14:45", "E6-105"), (2, "13:30", "14:45", "E6-105")], "문채원"),
        ("프로그래밍 기초", "Introduction to Programming", "01", "violet",
         [(1, "15:00", "16:15", "E5-B12"), (3, "15:00", "16:15", "E5-B12")], "박도윤"),
        ("학술 글쓰기", "Academic Writing", "04", "amber",
         [(4, "10:30", "12:15", "E2-212")], "윤하람"),
    ]
    return [
        {"ko": ko, "en": en, "sec": sec, "color": color, "slots": slots, "prof": prof,
         "full": f"{ko} ({en} )_{sec}{tag}", "label": en}
        for ko, en, sec, color, slots, prof in rows
    ]


# 과목마다 주차별 자료 (LMS 폴더 나무처럼 보이게 폴더 경로도 단다)
FILES = {
    0: [("강의계획서", "강의계획서_미적분학.pdf"), ("1주차", "Ch10_매개방정식.pdf"), ("2주차", "Ch10_극좌표.pdf"),
        ("3주차", "Ch11_수열과 급수.pdf"), ("4주차", "Ch11_비교판정법.pdf"), ("5주차", "Ch11_멱급수.pdf"),
        ("6주차", "Ch12_벡터와 공간기하.pdf"), ("과제", "HW3_급수의 수렴.pdf"), ("과제", "HW4_멱급수.pdf")],
    1: [("강의계획서", "Syllabus_GeneralPhysics.pdf"), ("1주차", "Lecture01_Electric Charge.pdf"),
        ("2주차", "Lecture02_Gauss Law.pdf"), ("3주차", "Lecture03_Electric Potential.pdf"),
        ("4주차", "Lecture04_Capacitance.pdf"), ("5주차", "Lecture05_Current and Resistance.pdf"),
        ("실험", "실험2_등전위선 측정.hwp"), ("실험", "실험3_RC회로.hwp")],
    2: [("강의계획서", "일반화학 강의계획서.pdf"), ("1주차", "Chapter 13 Kinetics.pptx"),
        ("2주차", "Chapter 14 Equilibrium.pptx"), ("3주차", "Chapter 15 Acids and Bases.pptx"),
        ("4주차", "Chapter 16 Buffers.pptx"), ("퀴즈", "Quiz2 해설.pdf")],
    3: [("강의계획서", "프로그래밍기초_syllabus.pdf"), ("1주차", "01_파이썬 시작하기.pdf"),
        ("2주차", "02_변수와 자료형.pdf"), ("3주차", "03_조건문과 반복문.pdf"), ("4주차", "04_함수.pdf"),
        ("5주차", "05_리스트와 딕셔너리.pdf"), ("실습", "lab05_starter.zip"), ("실습", "lab05_guide.ipynb")],
    4: [("강의계획서", "학술글쓰기_강의계획서.docx"), ("3주차", "3주차 문단 쓰기.pdf"),
        ("5주차", "5주차 논증 실습지.hwp"), ("6주차", "6주차 인용과 표절.pdf")],
}

DEADLINES = [
    # (과목 번호, 이름, 오늘부터 며칠·몇 시, 제출 상태, 만점)
    (0, "HW4 멱급수", (2, 23), None, 20),
    (1, "실험 보고서 3: RC 회로", (1, 18), None, 30),
    (2, "온라인 퀴즈 3", (4, 9), None, 10),
    (3, "Lab 5: 리스트와 딕셔너리", (0, 23), None, 10),
    (3, "Lab 4: 함수", (-5, 23), "Graded", 10),
    (4, "논증문 초고", (6, 17), None, 100),
    (0, "HW3 급수의 수렴", (-7, 23), "Graded", 20),
    (2, "실험 예비보고서 4", (9, 13), None, 15),
    (1, "중간고사 대비 문제", (-2, 23), None, 0),
]

EMAILS = [
    # (분류, 보낸 사람, 주소, 제목, 몇 시간 전, 안 읽음, 별, 본문)
    ("수업·LMS", "박도윤", "doyun.park@example.dgist.ac.kr", "[프로그래밍 기초] Lab 5 안내 및 제출 방법",
     2, True, False, "안녕하세요. 이번 주 Lab 5 는 리스트와 딕셔너리를 다룹니다.\n시작 코드는 LMS 5주차 폴더에 올려 두었습니다.\n제출은 금요일 23:59 까지입니다."),
    ("교수님", "한지성", "jisung.han@example.dgist.ac.kr", "미적분학 중간고사 범위 공지",
     5, True, True, "중간고사 범위는 10장 전체와 11장 6절까지입니다.\n시험 시간은 90분이고 계산기는 쓸 수 없습니다."),
    ("행정·학생팀", "학생팀", "student@example.dgist.ac.kr", "[학생팀] 2학기 장학금 신청 안내",
     20, False, False, "2학기 교내 장학금 신청을 아래와 같이 받습니다.\n신청 기간: 다음 주 금요일까지\n제출 서류: 신청서, 성적증명서"),
    ("세미나·행사", "기초학부", "ugs@example.dgist.ac.kr", "[기초학부] 진로 특강 - 연구실 인턴 이야기",
     28, True, False, "다음 주 수요일 18시, 학술정보관 1층에서 진로 특강이 열립니다.\n간식이 준비되어 있습니다."),
    ("학생회", "총학생회", "council@example.dgist.ac.kr", "가을 축제 부스 모집",
     50, False, False, "가을 축제 부스를 운영할 동아리·학생 단체를 모집합니다."),
    ("동아리·문화", "사진 동아리", "photo@example.dgist.ac.kr", "정기 출사 일정 안내",
     70, False, False, "이번 주 토요일 오전 10시, 정문 앞에서 출발합니다."),
    ("답신", "오세린", "serin.oh@example.dgist.ac.kr", "Re: 실험 보고서 제출 관련 문의",
     90, False, False, "네, 그래프는 손으로 그린 것을 찍어서 내도 됩니다."),
    ("취업·진로", "경력개발팀", "career@example.dgist.ac.kr", "겨울방학 연구 인턴십 모집",
     120, False, False, "학부생 겨울방학 연구 인턴십 신청을 받습니다."),
    ("기타", "도서관", "library@example.dgist.ac.kr", "대출 도서 반납 예정 알림",
     150, False, False, "대출하신 도서의 반납 예정일이 3일 남았습니다."),
]


def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")


def build(root: Path, version: str = "") -> None:
    """root 에 데이터 파일을 만든다. 이미 있으면 덮어쓴다(늘 오늘 기준으로 새로)."""
    now = datetime.now().astimezone()
    year, term = current_term(now)
    cs = courses(year, term)
    root.mkdir(parents=True, exist_ok=True)
    downloads = root / "downloads"
    downloads.mkdir(exist_ok=True)

    def write(name: str, data) -> None:
        (root / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    write("config.json", {
        # 비밀번호 칸은 파일·코드에 적지 않는다(CLAUDE.md 4). '연결됨' 으로 보이게 하는 값은
        # studio_server 가 demo 모드에서 실행할 때마다 무작위로 만들어 메모리에서만 넣는다.
        "LMS_ID": "202600000",
        "EMAIL_ADDRESS": "student@example.dgist.ac.kr",
        "DOWNLOAD_PATH": str(downloads),
        "SCHEDULE_TIME": "08:00",
    })

    # 강의자료 + 실제 파일(작은 빈 파일)을 두어 '내 컴퓨터에 있음' 상태로 보이게
    metadata, downloaded = {}, []
    for ci, items in FILES.items():
        course = cs[ci]
        for order, (folder, fname) in enumerate(items):
            local = f"{course['label']}__{fname}"
            stored = f"{year}-{term}학기/{course['ko']}/{folder}/{fname}"
            metadata[local] = {
                "course": course["full"],
                "folder_path": [folder],
                "original_name": fname,
                "lms_order": [order],
                "stored": stored,
            }
            path = downloads / stored
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"design studio demo file\n" * (40 + order * 37))
            downloaded.append(local)
    write("file_metadata.json", metadata)
    write("downloaded_files.json", downloaded)

    items = []
    for n, (ci, name, (days, hour), status, points) in enumerate(DEADLINES):
        due = (now + timedelta(days=days)).replace(hour=hour, minute=59 if hour == 23 else 0, second=0, microsecond=0)
        course = cs[ci]
        items.append({
            "course": course["full"], "courseLabel": course["label"], "courseId": f"_demo_{ci}",
            "columnId": f"_col_{n}", "name": name, "due": _iso(due), "scoreProvider": "resource/x-bb-assignment",
            "pointsPossible": points, "myStatus": status, "myScore": points if status == "Graded" else None,
        })
    write("deadlines.json", {"updatedAt": _iso(now - timedelta(minutes=12)), "items": items, "events": []})

    emails = []
    for n, (cat, name, addr, subject, hours, unread, star, body) in enumerate(EMAILS):
        uid = 5000 - n
        emails.append({
            "id": f"inbox:{uid}", "uid": uid, "folder": "inbox", "messageId": f"<demo-{uid}@example>",
            "subject": subject, "fromName": name, "fromEmail": addr,
            "toName": "김달링", "toEmail": "student@example.dgist.ac.kr",
            "date": _iso(now - timedelta(hours=hours)), "isReply": subject.startswith("Re:"),
            "unread": unread, "starred": star, "category": cat,
            "snippet": body.replace("\n", " ")[:300], "body": body,
            "bodyHtml": "<div style='font-family:sans-serif;line-height:1.6'>" + body.replace("\n", "<br>") + "</div>",
            "inlineImages": [], "attachments": [], "hasAttachment": False, "bodyVersion": 99,
        })
    write("emails.json", {"updatedAt": _iso(now - timedelta(minutes=3)), "briefing": "", "interests": "",
                          "contacts": [], "emails": emails})

    entries = []
    for ci, course in enumerate(cs):
        for si, (day, start, end, room) in enumerate(course["slots"]):
            entries.append({
                "id": f"tt-demo{ci}{si}", "title": course["ko"], "day": day, "start": start, "end": end,
                "room": room, "color": course["color"], "courseLabel": course["full"],
                "credit": "3", "courseNo": f"UGS{1100 + ci * 7}", "professor": course["prof"],
            })
    write("timetable.json", {"entries": entries, "semester": f"{year}_{term}"})

    today = now.date()
    write("my_events.json", [
        {"id": "ev-demo1", "title": "스터디 모임", "date": (today + timedelta(days=1)).isoformat(),
         "start": "19:00", "end": "21:00", "location": "학술정보관 2층", "color": "blue"},
        {"id": "ev-demo2", "title": "동아리 정기 모임", "date": (today + timedelta(days=3)).isoformat(),
         "start": "18:30", "end": "20:00", "location": "학생회관", "color": "green"},
    ])
    write("courses_state.json", {"pending": False, "added": [], "removed": [],
                                 "current": [c["full"] for c in cs], "updatedAt": _iso(now)})
    write("upload_selection.json", {"courses": {c["full"]: True for c in cs}, "hidden": [],
                                    "hiddenDeadlines": [], "hiddenFiles": []})
    # 첫 실행 소개·'새 업데이트' 카드는 디자인을 볼 때 가리기만 한다
    write("tutorial.json", {"done": True, "skipped": True, "step": 0, "at": _iso(now)})
    if version:
        write("whats_new.json", {"seen": version})
    write("health.json", {"lastSuccess": {"sync": _iso(now - timedelta(hours=3)),
                                          "deadlines": _iso(now - timedelta(minutes=12)),
                                          "emails": _iso(now - timedelta(minutes=3))}})
