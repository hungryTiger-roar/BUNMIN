"""
공개 대학교 강의 PDF 다운로드 스크립트
MIT OpenCourseWare 공개 강의 자료 사용 (검증된 직접 URL)

한국어 강의(KOCW)는 직접 URL 제공이 불가하므로
https://www.kocw.net 에서 직접 다운로드 후 pdfs/ 폴더에 넣어주세요.
"""
import sys
import urllib.request
from pathlib import Path

BASE = "https://ocw.mit.edu"
OUTPUT_DIR = Path(__file__).parent / "pdfs"

# 분야별 MIT OCW 강의 PDF (직접 검증된 URL)
LECTURE_PDFS = [
    # ── 컴퓨터공학 ──────────────────────────────────────────────
    {
        "name": "cs_intro_lec1.pdf",
        "url": f"{BASE}/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/pages/lecture-slides-code/MIT6_0001F16_Lec1.pdf",
        "domain": "Computer Science",
    },
    {
        "name": "cs_intro_lec2.pdf",
        "url": f"{BASE}/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/pages/lecture-slides-code/MIT6_0001F16_Lec2.pdf",
        "domain": "Computer Science",
    },
    # ── 수학 ────────────────────────────────────────────────────
    {
        "name": "math_linear_algebra_lec1.pdf",
        "url": f"{BASE}/courses/18-06sc-linear-algebra-fall-2011/pages/ax-b-and-the-four-subspaces/the-geometry-of-linear-equations/MIT18_06SCF11_Ses1.1sum.pdf",
        "domain": "Mathematics",
    },
    {
        "name": "math_probability_lec1.pdf",
        "url": f"{BASE}/courses/6-041sc-probabilistic-systems-analysis-and-applied-probability-fall-2013/pages/unit-i/lecture-1/MIT6_041SCF13_L01.pdf",
        "domain": "Mathematics",
    },
    # ── 자연과학 - 물리 ─────────────────────────────────────────
    {
        "name": "physics_relativity_lec1.pdf",
        "url": f"{BASE}/courses/8-033-relativity-fall-2006/a69cf2a86e23b65de2c3dec674aa9dca_lecture1_overvie.pdf",
        "domain": "Physics",
    },
    # ── 자연과학 - 화학 ─────────────────────────────────────────
    {
        "name": "chem_physical_lec1.pdf",
        "url": f"{BASE}/courses/5-61-physical-chemistry-fall-2017/f3366d8aaa0e6d308e13802fec808362_MIT5_61F17_lec1.pdf",
        "domain": "Chemistry",
    },
    # ── 경제학 / 사회과학 ────────────────────────────────────────
    {
        "name": "econ_trade_lec1.pdf",
        "url": f"{BASE}/courses/14-54-international-trade-fall-2016/d631ef052c79f3c3da0572241459ae77_MIT14_54F16_Lecture_1.pdf",
        "domain": "Economics",
    },
    {
        "name": "econ_psychology_lec1.pdf",
        "url": f"{BASE}/courses/14-13-psychology-and-economics-spring-2020/8eca398458e9e0d17b1529088c7c2bf7_MIT14_13S20_lec1.pdf",
        "domain": "Behavioral Economics",
    },
    # ── 인문학 / 심리학 ──────────────────────────────────────────
    {
        "name": "psych_intro_lec1.pdf",
        "url": f"{BASE}/courses/9-00sc-introduction-to-psychology-fall-2011/568e0d32a2401684b5daca281261f210_MIT9_00SCF11_lec01.pdf",
        "domain": "Psychology",
    },
    {
        "name": "psych_intro_lec2.pdf",
        "url": f"{BASE}/courses/9-00sc-introduction-to-psychology-fall-2011/5ff7eb6785f0575799a65af146ea17d2_MIT9_00SCF11_lec02_scires.pdf",
        "domain": "Psychology",
    },
    {
        "name": "psych_intro_lec3.pdf",
        "url": f"{BASE}/courses/9-00sc-introduction-to-psychology-fall-2011/d152a8ad15228393cc7cba38353a6954_MIT9_00SCF11_lec03_brain1.pdf",
        "domain": "Psychology",
    },
    {
        "name": "psych_intro_lec9.pdf",
        "url": f"{BASE}/courses/9-00sc-introduction-to-psychology-fall-2011/a4eb1079226055a8b05fb1ce56f5d397_MIT9_00SCF11_lec09_learning.pdf",
        "domain": "Psychology",
    },
    {
        "name": "psych_intro_lec12.pdf",
        "url": f"{BASE}/courses/9-00sc-introduction-to-psychology-fall-2011/bad022a1cb7439ffbb6d65ec1ab9a54a_MIT9_00SCF11_lec12_lang.pdf",
        "domain": "Psychology / Language",
    },
    # ── 머신러닝 / 알고리즘 ─────────────────────────────────────
    {
        "name": "ml_lec1.pdf",
        "url": f"{BASE}/courses/6-867-machine-learning-fall-2006/pages/lecture-notes/lec1.pdf",
        "domain": "Machine Learning",
    },
    {
        "name": "algo_lec1.pdf",
        "url": f"{BASE}/courses/6-006-introduction-to-algorithms-fall-2011/pages/lecture-videos/MIT6_006F11_lec01.pdf",
        "domain": "Algorithms",
    },
]

KOCW_NOTICE = """
─────────────────────────────────────────────────────
[한국어 강의 추가 방법]
KOCW(https://www.kocw.net)에서 원하는 강의의 PDF 자료를
직접 다운로드한 후 pdfs/ 폴더에 넣어주세요.

추천 분야: 국어학, 한국사, 경영학, 생물학, 교육학 등
─────────────────────────────────────────────────────
"""


def download_pdf(name: str, url: str, output_dir: Path) -> bool:
    dest = output_dir / name
    if dest.exists():
        print(f"[SKIP] 이미 존재: {name}")
        return True

    print(f"[DOWN] {name} ...", end=" ", flush=True)
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(dest, "wb") as f:
                f.write(response.read())
        print("OK")
        return True
    except Exception as e:
        print(f"FAIL ({e})")
        return False


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    domains = {}
    success, fail = 0, 0

    for item in LECTURE_PDFS:
        ok = download_pdf(item["name"], item["url"], OUTPUT_DIR)
        if ok:
            success += 1
            domains[item["domain"]] = domains.get(item["domain"], 0) + 1
        else:
            fail += 1

    print(f"\n완료: {success}개 성공, {fail}개 실패")
    print(f"저장 위치: {OUTPUT_DIR}\n")
    print("분야별 현황:")
    for domain, count in sorted(domains.items()):
        print(f"  {domain}: {count}개")

    print(KOCW_NOTICE)

    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
